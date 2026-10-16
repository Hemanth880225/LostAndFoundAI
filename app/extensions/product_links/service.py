"""Service layer for safe Product-Link Metadata Extraction and Enrichment."""

import html
import json
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
import httpx

from app.extensions.product_links.schemas import ProductMetadata
from app.extensions.product_links.security import validate_safe_url


COMMON_BRANDS = [
    "Apple", "Samsung", "Dell", "HP", "Lenovo", "Asus", "Acer", "Sony",
    "Bose", "JBL", "Boat", "OnePlus", "Xiaomi", "Realme", "Titan", "Fastrack",
    "Casio", "Fossil", "Wildcraft", "American Tourister", "Skybags", "Samsonite",
    "Nike", "Puma", "Adidas", "Ray-Ban", "Oakley", "Lenskart", "Logitech",
]

COMMON_COLORS = [
    "Black", "White", "Silver", "Grey", "Gray", "Blue", "Navy Blue", "Red",
    "Green", "Gold", "Rose Gold", "Brown", "Pink", "Yellow", "Orange", "Maroon",
]

CATEGORY_HINTS = {
    "Electronics": ["laptop", "phone", "headphone", "earphone", "charger", "mouse", "keyboard", "tablet", "watch", "camera", "power bank", "gadget"],
    "Bags & Luggage": ["bag", "backpack", "duffel", "suitcase", "tote", "pouch", "luggage", "rucksack", "briefcase"],
    "Clothing & Accessories": ["jacket", "shirt", "hoodie", "cap", "belt", "scarf", "coat", "shoes"],
    "Glasses & Optical": ["glasses", "sunglasses", "spectacles", "frames", "shades"],
    "Documents & Wallets": ["wallet", "purse", "cardholder", "folder", "passport"],
}


class _MetadataHTMLParser(HTMLParser):
    """Fast, safe HTML metadata extractor using standard library HTMLParser."""
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_json_ld = False
        self.title_text = []
        self.meta_tags: Dict[str, str] = {}
        self.json_ld_scripts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]):
        tag_lower = tag.lower()
        attr_dict = {k.lower(): v for k, v in attrs if v is not None}

        if tag_lower == "title":
            self.in_title = True
        elif tag_lower == "meta":
            prop = attr_dict.get("property") or attr_dict.get("name")
            content = attr_dict.get("content")
            if prop and content:
                self.meta_tags[prop.lower()] = content
        elif tag_lower == "script" and attr_dict.get("type") == "application/ld+json":
            self.in_json_ld = True

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self.in_title = False
        elif tag_lower == "script":
            self.in_json_ld = False

    def handle_data(self, data: str):
        if self.in_title:
            self.title_text.append(data)
        elif self.in_json_ld:
            self.json_ld_scripts.append(data)


def _clean_title(raw_title: Optional[str]) -> Optional[str]:
    """Clean commercial suffixes from page titles."""
    if not raw_title:
        return None
    cleaned = html.unescape(raw_title).strip()
    # Strip common site titles like " : Buy Online at Best Price in India - Amazon.in"
    cleaned = re.split(r"\s*[:|\-–]\s*(?:Buy|Amazon|Flipkart|Official|Online|Store)", cleaned, flags=re.IGNORECASE)[0]
    return cleaned.strip()[:150]


def _detect_brand(text: str) -> Optional[str]:
    """Identify recognized brand names from text."""
    for brand in COMMON_BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", text, re.IGNORECASE):
            return brand
    return None


def _detect_color(text: str) -> Optional[str]:
    """Identify common product color names from text, prioritizing earliest occurrence."""
    best_color = None
    best_pos = len(text) + 1
    # Check longer color names first so compound colors like 'Navy Blue', 'Rose Gold' are preserved
    for color in sorted(COMMON_COLORS, key=len, reverse=True):
        m = re.search(rf"\b{re.escape(color)}\b", text, re.IGNORECASE)
        if m and m.start() < best_pos:
            best_pos = m.start()
            best_color = color
    return best_color


def _detect_category(text: str) -> Optional[str]:
    """Classify product into one of the college lost-and-found categories."""
    lower = text.lower()
    for cat, keywords in CATEGORY_HINTS.items():
        if any(kw in lower for kw in keywords):
            return cat
    return "Personal Items"


async def extract_product_metadata(
    url: str,
    timeout_seconds: float = 4.0,
    client: Optional[httpx.AsyncClient] = None,
) -> ProductMetadata:
    """
    Safely fetch and parse product metadata from an external e-commerce URL.
    Enforces SSRF prevention and fails gracefully without raising exceptions to callers.
    """
    clean_url = url.strip()

    # 1. SSRF and URL validation
    try:
        parsed_url = validate_safe_url(clean_url)
    except Exception as exc:
        return ProductMetadata(
            canonical_url=clean_url,
            source_domain="unknown",
            extraction_status="failed",
            error_message=str(exc),
        )

    source_domain = getattr(parsed_url, "host", None) or getattr(parsed_url, "hostname", None) or "unknown"

    # 2. Fetch page with strict timeout and limits
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    html_content = ""
    try:
        if client is not None:
            resp = await client.get(clean_url, headers=headers, timeout=timeout_seconds, follow_redirects=True)
            if resp.status_code == 200:
                html_content = resp.text[:524288]  # Limit to 512KB
        else:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as local_client:
                resp = await local_client.get(clean_url, headers=headers)
                if resp.status_code == 200:
                    html_content = resp.text[:524288]
    except Exception as exc:
        return ProductMetadata(
            canonical_url=clean_url,
            source_domain=source_domain,
            extraction_status="failed",
            error_message=f"Network or timeout error while fetching product page: {exc}",
        )

    if not html_content:
        return ProductMetadata(
            canonical_url=clean_url,
            source_domain=source_domain,
            extraction_status="failed",
            error_message="Received empty response or non-200 HTTP status from product page.",
        )

    # 3. Parse HTML
    parser = _MetadataHTMLParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass

    # 4. Extract candidates from OpenGraph and meta tags
    meta = parser.meta_tags
    raw_title = (
        meta.get("og:title")
        or meta.get("twitter:title")
        or "".join(parser.title_text).strip()
        or meta.get("title")
    )
    title = _clean_title(raw_title)

    image_url = meta.get("og:image") or meta.get("twitter:image")
    description = meta.get("og:description") or meta.get("description") or ""

    brand = meta.get("og:brand") or meta.get("product:brand")
    price_val = meta.get("product:price:amount") or meta.get("og:price:amount")

    # 5. Check JSON-LD scripts for Product Schema
    ld_color = None
    for script_text in parser.json_ld_scripts:
        try:
            ld = json.loads(script_text)
            items = ld if isinstance(ld, list) else [ld]
            for it in items:
                if isinstance(it, dict) and it.get("@type") in ("Product", "IndividualProduct"):
                    if it.get("name"):
                        title = str(it.get("name"))
                    if it.get("color"):
                        ld_color = str(it.get("color"))
                    if not brand and it.get("brand"):
                        b = it.get("brand")
                        brand = b.get("name") if isinstance(b, dict) else str(b)
                    if not image_url and it.get("image"):
                        img = it.get("image")
                        image_url = img[0] if isinstance(img, list) else str(img)
                    if not price_val and it.get("offers"):
                        offers = it.get("offers")
                        if isinstance(offers, dict) and "price" in offers:
                            price_val = str(offers.get("price"))
        except Exception:
            continue

    # Fallback heuristic detections
    full_text = f"{title or ''} {description}"
    if not brand:
        brand = _detect_brand(full_text)
    color = ld_color or _detect_color(title or "") or _detect_color(full_text)
    category = _detect_category(full_text)

    est_price = None
    if price_val:
        try:
            cleaned_p = re.sub(r"[^\d.]", "", str(price_val))
            if cleaned_p:
                est_price = float(cleaned_p)
        except ValueError:
            pass

    return ProductMetadata(
        title=title,
        brand=brand,
        color=color,
        category=category,
        estimated_price_rupees=est_price,
        image_url=image_url,
        canonical_url=clean_url,
        source_domain=source_domain,
        extraction_status="success" if (title or brand) else "partial",
        error_message=None,
    )
