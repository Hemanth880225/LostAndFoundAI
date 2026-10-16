"""Location data provider integrations for the Safe Handover Finder."""

import abc
import asyncio
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core import config
from app.extensions.safe_handover.schemas import GeocodeResult

logger = logging.getLogger(__name__)


class BaseLocationProvider(abc.ABC):
    """Abstract interface for location, geocoding, and POI providers."""

    @abc.abstractmethod
    async def geocode(self, query: str, limit: int = 5) -> List[GeocodeResult]:
        """Geocode a place name, address, or landmark into coordinates."""
        pass

    @abc.abstractmethod
    async def reverse_geocode(self, lat: float, lon: float) -> Optional[str]:
        """Reverse geocode coordinates into a human-readable display address."""
        pass

    @abc.abstractmethod
    async def search_nearby(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        category: Optional[str] = "all",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search nearby facilities within a given radius."""
        pass


class SimpleTTLCache:
    """Thread-safe in-memory cache with time-to-live expiration."""

    def __init__(self, ttl_seconds: int = 300):
        self._ttl = ttl_seconds
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self._store:
            created_at, val = self._store[key]
            if time.time() - created_at < self._ttl:
                return val
            del self._store[key]
        return None

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)

    def clear(self) -> None:
        self._store.clear()


class OSMNominatimProvider(BaseLocationProvider):
    """OpenStreetMap Nominatim provider for geocoding and nearby POI search.
    
    Adheres to OpenStreetMap usage policies:
    - Sets an identifiable custom User-Agent.
    - Caches responses in-memory to prevent redundant queries.
    - Gracefully handles rate limits and network timeouts.
    """

    # Category to search query keyword mappings
    CATEGORY_QUERIES: Dict[str, List[str]] = {
        "police": ["police station", "police"],
        "lost_property": ["lost property office", "lost and found"],
        "transit": ["railway station", "train station", "bus station", "airport terminal"],
        "campus_security": ["campus security", "university security"],
        "public_service": ["town hall", "civic centre", "city hall"],
        "post_office": ["post office"],
    }

    def __init__(
        self,
        base_url: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[float] = None,
        cache_ttl: Optional[int] = None,
    ):
        self.base_url = (base_url or config.NOMINATIM_BASE_URL).rstrip("/")
        self.user_agent = user_agent or config.LOCATION_PROVIDER_USER_AGENT
        self.timeout = timeout if timeout is not None else config.LOCATION_REQUEST_TIMEOUT
        self.cache = SimpleTTLCache(ttl_seconds=cache_ttl if cache_ttl is not None else config.LOCATION_CACHE_TTL_SECONDS)

    def _get_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Language": "en",
        }

    async def geocode(self, query: str, limit: int = 5) -> List[GeocodeResult]:
        """Geocode a place name, city, or address into coordinates."""
        clean_q = query.strip()
        if not clean_q:
            return []

        cache_key = f"geo:{clean_q.lower()}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/search"
        params = {
            "q": clean_q,
            "format": "jsonv2",
            "addressdetails": "1",
            "limit": str(limit),
        }

        results: List[GeocodeResult] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params, headers=self._get_headers())
                if resp.status_code == 200:
                    raw_data = resp.json()
                    for item in raw_data:
                        try:
                            results.append(
                                GeocodeResult(
                                    display_name=item.get("display_name", ""),
                                    latitude=float(item["lat"]),
                                    longitude=float(item["lon"]),
                                    place_type=item.get("type") or item.get("class"),
                                    importance=float(item.get("importance", 0.0)) if item.get("importance") is not None else None,
                                )
                            )
                        except (KeyError, ValueError, TypeError) as parse_err:
                            logger.debug("Skipping malformed geocode item %s: %s", item, parse_err)
                            continue
                    self.cache.set(cache_key, results)
                else:
                    logger.warning("Nominatim geocode failed with HTTP %s: %s", resp.status_code, resp.text[:200])
        except (httpx.TimeoutException, httpx.RequestError) as net_err:
            logger.warning("Nominatim geocode network error for '%s': %s", clean_q, net_err)
        except Exception as exc:
            logger.error("Unexpected error in Nominatim geocode for '%s': %s", clean_q, exc)

        return results

    async def reverse_geocode(self, lat: float, lon: float) -> Optional[str]:
        """Reverse geocode coordinates into a display address string."""
        rounded_lat = round(lat, 4)
        rounded_lon = round(lon, 4)
        cache_key = f"rgeo:{rounded_lat}:{rounded_lon}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/reverse"
        params = {
            "lat": str(lat),
            "lon": str(lon),
            "format": "jsonv2",
        }

        display_name: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params, headers=self._get_headers())
                if resp.status_code == 200:
                    data = resp.json()
                    display_name = data.get("display_name")
                    if display_name:
                        self.cache.set(cache_key, display_name)
                else:
                    logger.warning("Nominatim reverse geocode failed with HTTP %s", resp.status_code)
        except (httpx.TimeoutException, httpx.RequestError) as net_err:
            logger.warning("Nominatim reverse geocode network error: %s", net_err)
        except Exception as exc:
            logger.error("Unexpected error in Nominatim reverse geocode: %s", exc)

        return display_name

    def _compute_viewbox(self, lat: float, lon: float, radius_km: float) -> str:
        """Compute Nominatim viewbox parameter: left,top,right,bottom."""
        delta_lat = radius_km / 111.0
        cos_lat = max(0.01, math.cos(math.radians(lat)))
        delta_lon = radius_km / (111.0 * cos_lat)

        left = lon - delta_lon
        right = lon + delta_lon
        top = lat + delta_lat
        bottom = lat - delta_lat
        return f"{left:.6f},{top:.6f},{right:.6f},{bottom:.6f}"

    async def _query_single_term(
        self,
        client: httpx.AsyncClient,
        term: str,
        viewbox: str,
        limit_per_query: int,
    ) -> List[Dict[str, Any]]:
        """Query Nominatim search for a specific term inside a viewbox."""
        url = f"{self.base_url}/search"
        params = {
            "q": term,
            "viewbox": viewbox,
            "bounded": "1",
            "format": "jsonv2",
            "extratags": "1",
            "addressdetails": "1",
            "limit": str(limit_per_query),
        }
        try:
            resp = await client.get(url, params=params, headers=self._get_headers())
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
            else:
                logger.warning("Nominatim query '%s' failed with status %s", term, resp.status_code)
        except Exception as err:
            logger.debug("Nominatim query error for term '%s': %s", term, err)
        return []

    async def search_nearby(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        category: Optional[str] = "all",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search nearby POIs inside the radius bounding box."""
        cat_key = (category or "all").lower()
        cache_key = f"nearby:{round(lat, 3)}:{round(lon, 3)}:{radius_km}:{cat_key}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        viewbox = self._compute_viewbox(lat, lon, radius_km)

        # Determine which search terms to query
        if cat_key in self.CATEGORY_QUERIES:
            terms = self.CATEGORY_QUERIES[cat_key]
        elif cat_key == "all":
            # Select key anchor terms across categories
            terms = ["police station", "railway station", "town hall", "post office"]
        else:
            terms = [cat_key]

        raw_items: List[Dict[str, Any]] = []
        limit_per_query = max(3, limit // max(1, len(terms)) + 2)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Query terms concurrently
                tasks = [
                    self._query_single_term(client, term, viewbox, limit_per_query)
                    for term in terms
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, list):
                        raw_items.extend(res)
        except Exception as exc:
            logger.error("Error executing nearby search in NominatimProvider: %s", exc)

        # Deduplicate raw items by place_id / osm_id
        seen_ids = set()
        deduped: List[Dict[str, Any]] = []
        for item in raw_items:
            osm_id = str(item.get("osm_id") or item.get("place_id") or "")
            if osm_id and osm_id in seen_ids:
                continue
            if osm_id:
                seen_ids.add(osm_id)
            deduped.append(item)

        self.cache.set(cache_key, deduped)
        return deduped


# Default singleton instance
default_provider = OSMNominatimProvider()
