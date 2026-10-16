/**
 * Travel Mode & Safe Handover Finder
 * LostAndFoundAI client-side mapping and discovery logic.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const btnUseGps = document.getElementById('btn-use-gps');
  const gpsLabel = document.getElementById('gps-label');
  const searchForm = document.getElementById('handover-search-form');
  const inputPlace = document.getElementById('input-place');
  const suggestionsBox = document.getElementById('geocode-suggestions');
  const activeLocBar = document.getElementById('active-location-bar');
  const activeLocName = document.getElementById('active-loc-name');
  const activeLocCoords = document.getElementById('active-loc-coords');
  const btnClearLoc = document.getElementById('btn-clear-loc');
  const selectContext = document.getElementById('select-travel-context');
  const selectRadius = document.getElementById('select-radius');
  const categoryPillsContainer = document.getElementById('category-pills');
  const noticeEl = document.getElementById('handover-notice');
  const resultsList = document.getElementById('handover-results-list');
  const resultsCountHeading = document.getElementById('results-count-heading');
  const resultsMetaBadge = document.getElementById('results-meta-badge');

  // State
  let currentCoords = null; // { lat, lon, name }
  let currentCategory = 'all';
  let currentTravelContext = 'general';
  let currentRadiusKm = 5.0;
  let map = null;
  let userMarker = null;
  let facilityMarkers = [];
  let isSearching = false;

  // Initialize Map
  function initMap() {
    if (typeof L === 'undefined') {
      console.warn('Leaflet library not loaded.');
      return;
    }

    // Default center (Pune / configured campus coordinates)
    const defaultCenter = [18.5204, 73.8567];
    map = L.map('handover-map', {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView(defaultCenter, 13);

    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    }).addTo(map);

    // Allow user to click on map to set search location manually
    map.on('click', (e) => {
      const lat = e.latlng.lat;
      const lon = e.latlng.lng;
      setLocation(lat, lon, `Selected point (${lat.toFixed(4)}, ${lon.toFixed(4)})`);
    });
  }

  function showNotice(msg, type = 'info') {
    noticeEl.textContent = msg;
    noticeEl.className = `handover-notice notice-${type}`;
    noticeEl.hidden = false;
  }

  function hideNotice() {
    noticeEl.hidden = true;
    noticeEl.textContent = '';
  }

  // Update Active Location Indicator
  function updateLocationBar(name, lat, lon) {
    activeLocName.textContent = name || 'Selected Location';
    activeLocCoords.textContent = `${lat.toFixed(5)}° N, ${lon.toFixed(5)}° E`;
    activeLocBar.hidden = false;
  }

  // Set Current Location and Run Search
  function setLocation(lat, lon, name = null) {
    currentCoords = { lat, lon, name: name || 'Selected Location' };
    updateLocationBar(currentCoords.name, lat, lon);
    hideNotice();

    if (map) {
      if (userMarker) {
        userMarker.setLatLng([lat, lon]);
      } else {
        const userIcon = L.divIcon({
          className: 'user-location-pin',
          html: '<div class="pin-pulse"></div><div class="pin-center">📍</div>',
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        });
        userMarker = L.marker([lat, lon], { icon: userIcon }).addTo(map);
      }
      userMarker.bindPopup(`<b>Your Search Location</b><br>${Foundly.escape(currentCoords.name)}`).openPopup();
      map.setView([lat, lon], getZoomLevelForRadius(currentRadiusKm));
    }

    fetchHandoverLocations();
  }

  function getZoomLevelForRadius(radiusKm) {
    if (radiusKm <= 2) return 15;
    if (radiusKm <= 5) return 14;
    if (radiusKm <= 10) return 13;
    return 12;
  }

  // Clear Location
  function clearLocation() {
    currentCoords = null;
    activeLocBar.hidden = true;
    if (userMarker && map) {
      map.removeLayer(userMarker);
      userMarker = null;
    }
    clearFacilityMarkers();
    resultsCountHeading.textContent = 'Nearby Facilities';
    resultsMetaBadge.textContent = 'Choose a location to search';
    resultsList.innerHTML = `
      <div class="handover-empty-state">
        <div class="empty-icon">📍</div>
        <h3>Find safe handover points nearby</h3>
        <p>Click <strong>"Use my current location"</strong> or enter a city, street, or landmark above to discover verified police stations, transit desks, and campus repositories.</p>
      </div>
    `;
    inputPlace.value = '';
    hideNotice();
  }

  function clearFacilityMarkers() {
    facilityMarkers.forEach((m) => {
      if (map) map.removeLayer(m);
    });
    facilityMarkers = [];
  }

  // Handle GPS Geolocation
  btnUseGps.addEventListener('click', () => {
    if (!navigator.geolocation) {
      showNotice('Geolocation is not supported by your browser. Please search manually by city or address.', 'error');
      return;
    }

    hideNotice();
    btnUseGps.disabled = true;
    gpsLabel.textContent = 'Detecting GPS position…';

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        btnUseGps.disabled = false;
        gpsLabel.textContent = 'Use my current location';
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        setLocation(lat, lon, 'Current GPS Location');
        Foundly.toast('Location identified via GPS.');
      },
      (err) => {
        btnUseGps.disabled = false;
        gpsLabel.textContent = 'Use my current location';
        let msg = 'Unable to retrieve location.';
        if (err.code === 1) {
          msg = 'Location permission was denied. You can search by entering your city, address, or landmark in the search box.';
        } else if (err.code === 2) {
          msg = 'Current location is unavailable. Please check device location settings or search manually.';
        } else if (err.code === 3) {
          msg = 'Location request timed out. Please try again or search by address.';
        }
        showNotice(msg, 'warning');
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 60000,
      }
    );
  });

  // Handle Manual Place Search Submit
  searchForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = inputPlace.value.trim();
    if (!query) {
      showNotice('Please enter a city, street, or landmark to search.', 'warning');
      return;
    }

    hideNotice();
    suggestionsBox.hidden = true;
    const submitBtn = document.getElementById('btn-search-place');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Searching…';

    try {
      const res = await Foundly.api(`/api/handover/geocode?q=${encodeURIComponent(query)}&limit=5`);
      submitBtn.disabled = false;
      submitBtn.textContent = 'Search';

      if (!res.results || res.results.length === 0) {
        showNotice(`No matching locations found for "${query}". Please check the spelling or try a larger city name.`, 'warning');
        return;
      }

      if (res.results.length === 1) {
        // Auto-select single result
        const r = res.results[0];
        setLocation(r.latitude, r.longitude, r.display_name);
      } else {
        // Show selection dropdown
        renderSuggestions(res.results);
      }
    } catch (err) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Search';
      showNotice(`Location search failed: ${err.message}`, 'error');
    }
  });

  function renderSuggestions(candidates) {
    suggestionsBox.innerHTML = '';
    candidates.forEach((c) => {
      const item = document.createElement('div');
      item.className = 'geocode-suggestion-item';
      item.innerHTML = `
        <span class="suggestion-icon">📍</span>
        <div class="suggestion-text">
          <strong>${Foundly.escape(c.display_name.split(',')[0])}</strong>
          <small>${Foundly.escape(c.display_name)}</small>
        </div>
      `;
      item.addEventListener('click', () => {
        suggestionsBox.hidden = true;
        inputPlace.value = c.display_name.split(',')[0];
        setLocation(c.latitude, c.longitude, c.display_name);
      });
      suggestionsBox.appendChild(item);
    });
    suggestionsBox.hidden = false;
  }

  // Dismiss suggestions dropdown when clicking outside
  document.addEventListener('click', (e) => {
    if (!searchForm.contains(e.target)) {
      suggestionsBox.hidden = true;
    }
  });

  btnClearLoc.addEventListener('click', () => {
    clearLocation();
  });

  // Filter Changes
  selectContext.addEventListener('change', () => {
    currentTravelContext = selectContext.value;
    if (currentCoords) fetchHandoverLocations();
  });

  selectRadius.addEventListener('change', () => {
    currentRadiusKm = parseFloat(selectRadius.value);
    if (currentCoords) {
      if (map) map.setZoom(getZoomLevelForRadius(currentRadiusKm));
      fetchHandoverLocations();
    }
  });

  categoryPillsContainer.querySelectorAll('.category-pill').forEach((btn) => {
    btn.addEventListener('click', () => {
      categoryPillsContainer.querySelectorAll('.category-pill').forEach((b) => {
        b.classList.remove('active');
        b.setAttribute('aria-checked', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-checked', 'true');
      currentCategory = btn.dataset.category;
      if (currentCoords) fetchHandoverLocations();
    });
  });

  // Fetch Handover Locations from API
  async function fetchHandoverLocations() {
    if (!currentCoords || isSearching) return;
    isSearching = true;

    resultsCountHeading.textContent = 'Searching nearby facilities…';
    resultsMetaBadge.textContent = 'Contacting location provider…';
    resultsList.innerHTML = `
      <div class="handover-loading-skeleton">
        <div class="skeleton card-skeleton"></div>
        <div class="skeleton card-skeleton"></div>
        <div class="skeleton card-skeleton"></div>
      </div>
    `;

    try {
      const payload = {
        latitude: currentCoords.lat,
        longitude: currentCoords.lon,
        radius_km: currentRadiusKm,
        category: currentCategory,
        travel_context: currentTravelContext,
        limit: 25,
      };

      const res = await Foundly.api('/api/handover/nearby', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      renderResults(res);
    } catch (err) {
      showNotice(`Failed to retrieve nearby handover locations: ${err.message}`, 'error');
      resultsCountHeading.textContent = 'Search Error';
      resultsMetaBadge.textContent = 'Error';
      resultsList.innerHTML = `
        <div class="handover-empty-state">
          <div class="empty-icon">⚠️</div>
          <h3>Unable to load handover locations</h3>
          <p>${Foundly.escape(err.message)}</p>
          <button type="button" class="button button-small" onclick="document.dispatchEvent(new CustomEvent('retry-handover'))">Retry search</button>
        </div>
      `;
    } finally {
      isSearching = false;
    }
  }

  document.addEventListener('retry-handover', () => {
    if (currentCoords) fetchHandoverLocations();
  });

  // Render Handover Results and Map Markers
  function renderResults(data) {
    clearFacilityMarkers();

    const count = data.locations ? data.locations.length : 0;
    resultsCountHeading.textContent = `${count} Safe Handover Point${count === 1 ? '' : 's'}`;
    resultsMetaBadge.textContent = `Within ${data.search_radius_km} km`;

    if (count === 0) {
      resultsList.innerHTML = `
        <div class="handover-empty-state">
          <div class="empty-icon">🔍</div>
          <h3>No handover locations found</h3>
          <p>No verified facilities matched your filter within <strong>${data.search_radius_km} km</strong>.</p>
          <p>Try selecting <strong>"All"</strong> categories, expanding the search radius to <strong>10 km or 20 km</strong>, or selecting a nearby town centre.</p>
        </div>
      `;
      return;
    }

    const cardsHtml = data.locations.map((loc, idx) => buildLocationCard(loc, idx)).join('');
    resultsList.innerHTML = cardsHtml;

    // Attach card event listeners
    resultsList.querySelectorAll('.btn-show-map').forEach((btn) => {
      btn.addEventListener('click', () => {
        const index = parseInt(btn.dataset.index, 10);
        const loc = data.locations[index];
        if (loc && map) {
          map.setView([loc.latitude, loc.longitude], 16);
          const marker = facilityMarkers[index];
          if (marker) marker.openPopup();
          window.scrollTo({ top: document.querySelector('.map-column').offsetTop - 60, behavior: 'smooth' });
        }
      });
    });

    // Add Markers to Leaflet Map
    if (map) {
      const bounds = L.latLngBounds();
      if (userMarker) bounds.extend(userMarker.getLatLng());

      data.locations.forEach((loc, idx) => {
        const markerColor = getMarkerColor(loc.category);
        const markerIcon = L.divIcon({
          className: `facility-pin pin-${loc.category}`,
          html: `<div class="facility-pin-badge" style="background-color: ${markerColor}"><span>${idx + 1}</span></div>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        });

        const marker = L.marker([loc.latitude, loc.longitude], { icon: markerIcon }).addTo(map);

        const popupContent = `
          <div class="map-popup-card">
            <div class="popup-header">
              <span class="popup-badge badge-${loc.category}">${Foundly.escape(loc.category_label)}</span>
              <strong>${Foundly.escape(loc.name)}</strong>
            </div>
            <div class="popup-dist">${Foundly.escape(loc.distance_label)}</div>
            <div class="popup-addr">${Foundly.escape(loc.address)}</div>
            <div class="popup-status status-${loc.acceptance_status}">
              ${Foundly.escape(loc.acceptance_status === 'likely' ? '✓ Custody Intake Likely' : 'ℹ Staff Inquiry Required')}
            </div>
            <div class="popup-actions">
              <a href="${Foundly.escape(loc.directions_url_google)}" target="_blank" rel="noopener" class="button button-small">Google Maps ↗</a>
              <a href="${Foundly.escape(loc.directions_url_osm)}" target="_blank" rel="noopener" class="button button-small button-light">OSM ↗</a>
            </div>
          </div>
        `;
        marker.bindPopup(popupContent);
        facilityMarkers.push(marker);
        bounds.extend([loc.latitude, loc.longitude]);
      });

      // Fit map to show all markers with padding
      if (facilityMarkers.length > 0) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
      }
    }
  }

  function getMarkerColor(cat) {
    switch (cat) {
      case 'police': return '#1d4ed8'; // Navy Blue
      case 'campus_security': return '#15803d'; // Green
      case 'transit': return '#d97706'; // Amber
      case 'lost_property': return '#7c3aed'; // Purple
      case 'post_office': return '#64748b'; // Slate Gray
      default: return '#0284c7'; // Sky Blue
    }
  }

  function buildLocationCard(loc, index) {
    const isPostOffice = loc.category === 'post_office';
    const isPrimary = loc.recommendation_tier === 'primary';

    const phoneHtml = loc.phone
      ? `<div class="fact-row">
           <span class="fact-label">Phone:</span>
           <a href="tel:${Foundly.escape(loc.phone)}" class="fact-value link-phone">📞 ${Foundly.escape(loc.phone)}</a>
         </div>`
      : `<div class="fact-row fact-missing">
           <span class="fact-label">Phone:</span>
           <span class="fact-value">Not listed in public directory</span>
         </div>`;

    const hoursHtml = loc.operating_hours
      ? `<div class="fact-row">
           <span class="fact-label">Hours:</span>
           <span class="fact-value">🕒 ${Foundly.escape(loc.operating_hours)}</span>
         </div>`
      : `<div class="fact-row fact-missing">
           <span class="fact-label">Hours:</span>
           <span class="fact-value">Operating hours unconfirmed — daytime visit advised</span>
         </div>`;

    const caveatClass = isPostOffice
      ? 'policy-box policy-post-office'
      : isPrimary
      ? 'policy-box policy-primary'
      : 'policy-box policy-secondary';

    const caveatIcon = isPostOffice ? '⚠️' : isPrimary ? '🛡️' : 'ℹ️';

    return `
      <article class="handover-card panel" id="loc-card-${index}">
        <div class="card-top-row">
          <div class="card-title-group">
            <span class="card-index-pill">${index + 1}</span>
            <div>
              <h3 class="facility-name">${Foundly.escape(loc.name)}</h3>
              <div class="badge-cluster">
                <span class="category-pill-badge badge-${Foundly.escape(loc.category)}">${Foundly.escape(loc.category_label)}</span>
                <span class="tier-pill-badge tier-${Foundly.escape(loc.recommendation_tier)}">
                  ${Foundly.escape(loc.recommendation_tier === 'primary' ? 'Primary Handover Point' : loc.recommendation_tier === 'secondary' ? 'Secondary Facility' : 'Conditional Handover')}
                </span>
              </div>
            </div>
          </div>
          <div class="distance-badge" title="Calculated as direct line between coordinates">
            <strong>${Foundly.escape(loc.distance_label)}</strong>
          </div>
        </div>

        <div class="facility-details-grid">
          <div class="fact-row">
            <span class="fact-label">Address:</span>
            <span class="fact-value address-value">📍 ${Foundly.escape(loc.address)}</span>
          </div>
          ${phoneHtml}
          ${hoursHtml}
        </div>

        <!-- Policy & Acceptance Caveat Box -->
        <div class="${caveatClass}">
          <span class="policy-icon">${caveatIcon}</span>
          <div class="policy-copy">
            <strong>Handover Guidance:</strong>
            <p>${Foundly.escape(loc.acceptance_note)}</p>
            <small class="rationale-note">Basis: ${Foundly.escape(loc.recommendation_reason)}</small>
          </div>
        </div>

        <div class="card-actions-row">
          <a href="${Foundly.escape(loc.directions_url_google)}" target="_blank" rel="noopener" class="button button-small">
            Google Maps Directions ↗
          </a>
          <a href="${Foundly.escape(loc.directions_url_osm)}" target="_blank" rel="noopener" class="button button-small button-light">
            OpenStreetMap ↗
          </a>
          <button type="button" class="button button-small button-subtle btn-show-map" data-index="${index}">
            Show on Map
          </button>
        </div>
      </article>
    `;
  }

  // Initialize Map
  initMap();

  // Check URL Parameters for Deep-Linking
  const params = new URLSearchParams(window.location.search);
  const qParam = params.get('search') || params.get('q');
  const latParam = parseFloat(params.get('lat'));
  const lonParam = parseFloat(params.get('lon') || params.get('lng'));

  if (!isNaN(latParam) && !isNaN(lonParam)) {
    setLocation(latParam, lonParam, qParam || 'Selected Location');
  } else if (qParam) {
    inputPlace.value = qParam;
    searchForm.dispatchEvent(new Event('submit'));
  }
});
