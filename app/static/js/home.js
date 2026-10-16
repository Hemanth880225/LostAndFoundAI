/**
 * Foundly - Home Page Logic
 * Handles recent listings, integrated multi-modal AI search, photo dropzone, and attribute filtering.
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Recent Reports Section
  const recentGrid = document.querySelector('#recent-reports');
  const homeState = document.querySelector('#home-state');

  async function loadRecentReports() {
    if (!recentGrid) return;
    try {
      const reports = await Foundly.api('/api/reports?limit=6');
      if (!reports || !reports.length) {
        recentGrid.innerHTML = `
          <div class="empty-state">
            <div class="placeholder-icon">✳</div>
            <h3>The board is ready for its first report</h3>
            <p>Share a lost or found item to help someone reconnect.</p>
            <div style="display:flex;gap:10px;justify-content:center;margin-top:14px;">
              <a class="button button-small" href="/report/lost">Report a Lost Item</a>
              <a class="button button-small button-light" href="/report/found">Report a Found Item</a>
            </div>
          </div>
        `;
        return;
      }

      recentGrid.innerHTML = reports.map(Foundly.card).join('');

      // Asynchronously fetch thumbnails
      await Promise.all(
        [...recentGrid.querySelectorAll('.report-card')].map(async (card, idx) => {
          const item = reports[idx];
          if (!item) return;
          const url = await Foundly.imageFor(item.id);
          if (url) {
            const imgBox = card.querySelector('.report-image');
            if (imgBox) {
              imgBox.insertAdjacentHTML(
                'beforeend',
                `<img src="${Foundly.escape(url)}" alt="${Foundly.escape(item.item_name)}" loading="lazy" onerror="this.remove()">`
              );
            }
          }
        })
      );
    } catch (err) {
      if (recentGrid) recentGrid.innerHTML = '';
      if (homeState) {
        homeState.innerHTML = `Could not load recent listings. <button type="button" class="button-text-subtle" id="btn-retry-recent">Try again</button>`;
        document.querySelector('#btn-retry-recent')?.addEventListener('click', loadRecentReports);
      }
    }
  }

  loadRecentReports();

  // 2. Integrated AI Search Panel
  const queryInput = document.querySelector('#home-query-input');
  const searchBtn = document.querySelector('#btn-home-search');
  const dropzone = document.querySelector('#home-dropzone');
  const dropzoneTarget = document.querySelector('#dropzone-click-target');
  const photoInput = document.querySelector('#home-photo-input');
  const previewStrip = document.querySelector('#home-photo-previews');
  const detectedPanel = document.querySelector('#home-detected-attrs');
  const detectedChips = document.querySelector('#home-detected-chips');
  const btnToggleFilters = document.querySelector('#btn-toggle-filters');
  const filtersGrid = document.querySelector('#home-filters-grid');
  const resultsArea = document.querySelector('#home-results-area');
  const resultsGrid = document.querySelector('#home-results-grid');
  const resultsTitle = document.querySelector('#home-results-title');
  const clearResultsBtn = document.querySelector('#btn-clear-home-results');

  const catSelect = document.querySelector('#filter-category');
  const colorSelect = document.querySelector('#filter-color');
  const shapeSelect = document.querySelector('#filter-shape');
  const typeSelect = document.querySelector('#filter-target-type');

  let selectedPhotos = []; // Array of File objects

  // Mode switching tabs
  const tabAll = document.querySelector('#tab-all-search');
  const tabPhoto = document.querySelector('#tab-photo-only');
  const tabText = document.querySelector('#tab-text-only');
  const textGroup = document.querySelector('#field-text-group');

  if (tabAll && tabPhoto && tabText) {
    tabAll.addEventListener('click', () => {
      tabAll.classList.add('active');
      tabPhoto.classList.remove('active');
      tabText.classList.remove('active');
      if (textGroup) textGroup.style.display = 'flex';
      if (dropzone) dropzone.style.display = 'block';
    });

    tabPhoto.addEventListener('click', () => {
      tabPhoto.classList.add('active');
      tabAll.classList.remove('active');
      tabText.classList.remove('active');
      if (textGroup) textGroup.style.display = 'none';
      if (dropzone) dropzone.style.display = 'block';
    });

    tabText.addEventListener('click', () => {
      tabText.classList.add('active');
      tabAll.classList.remove('active');
      tabPhoto.classList.remove('active');
      if (textGroup) textGroup.style.display = 'flex';
      if (dropzone) dropzone.style.display = 'none';
    });
  }

  // Toggle Filters Accordion
  if (btnToggleFilters && filtersGrid) {
    btnToggleFilters.addEventListener('click', () => {
      const isExpanded = btnToggleFilters.getAttribute('aria-expanded') === 'true';
      btnToggleFilters.setAttribute('aria-expanded', !isExpanded);
      filtersGrid.style.display = isExpanded ? 'none' : 'grid';
    });
  }

  // Handle Dropzone Click & Keyboard Navigation
  if (dropzoneTarget && photoInput) {
    dropzoneTarget.addEventListener('click', () => photoInput.click());
    dropzoneTarget.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        photoInput.click();
      }
    });

    photoInput.addEventListener('change', () => {
      handleFilesSelected(photoInput.files);
    });

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
      dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files) {
        handleFilesSelected(e.dataTransfer.files);
      }
    });
  }

  function handleFilesSelected(fileList) {
    if (!fileList || !fileList.length) return;
    const MAX_PHOTOS = 4;
    const allowed = ['image/jpeg', 'image/png', 'image/webp'];

    for (const f of Array.from(fileList)) {
      if (!allowed.includes(f.type)) {
        Foundly.toast(`"${f.name}" is not a supported format. Please use JPEG, PNG, or WebP.`, true);
        continue;
      }
      if (f.size > 5 * 1024 * 1024) {
        Foundly.toast(`"${f.name}" exceeds 5 MiB.`, true);
        continue;
      }
      if (selectedPhotos.length >= MAX_PHOTOS) {
        Foundly.toast(`You can search with up to ${MAX_PHOTOS} photos.`, true);
        break;
      }
      // Check duplicate
      if (!selectedPhotos.some(x => x.name === f.name && x.size === f.size)) {
        selectedPhotos.push(f);
      }
    }

    renderPhotoPreviews();

    // Trigger AI attribute extraction on first selected photo
    if (selectedPhotos.length > 0) {
      extractPhotoAttributes(selectedPhotos[0]);
    }
  }

  function renderPhotoPreviews() {
    if (!previewStrip) return;
    if (selectedPhotos.length === 0) {
      previewStrip.style.display = 'none';
      previewStrip.innerHTML = '';
      if (detectedPanel) detectedPanel.style.display = 'none';
      return;
    }

    previewStrip.style.display = 'flex';
    previewStrip.innerHTML = selectedPhotos.map((f, i) => {
      const url = URL.createObjectURL(f);
      return `
        <div class="home-preview-thumb">
          <img src="${url}" alt="${Foundly.escape(f.name)}">
          <button type="button" class="btn-remove-thumb" data-index="${i}" title="Remove photo">×</button>
        </div>
      `;
    }).join('');

    previewStrip.querySelectorAll('.btn-remove-thumb').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = Number(btn.dataset.index);
        selectedPhotos.splice(idx, 1);
        renderPhotoPreviews();
        if (selectedPhotos.length > 0) {
          extractPhotoAttributes(selectedPhotos[0]);
        } else {
          if (detectedPanel) detectedPanel.style.display = 'none';
        }
      });
    });
  }

  async function extractPhotoAttributes(file) {
    if (!file || !detectedPanel || !detectedChips) return;
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await Foundly.api('/api/attributes/extract', {
        method: 'POST',
        body: fd,
      });

      if (res && res.attributes) {
        const chips = [];
        const a = res.attributes;
        if (a.category) chips.push(`<span class="attr-chip highlight">${Foundly.escape(a.category)}</span>`);
        if (a.primary_color) chips.push(`<span class="attr-chip">Color: ${Foundly.escape(a.primary_color)}</span>`);
        if (a.shape) chips.push(`<span class="attr-chip">Shape: ${Foundly.escape(a.shape)}</span>`);
        if (a.material) chips.push(`<span class="attr-chip">Material: ${Foundly.escape(a.material)}</span>`);

        if (chips.length > 0) {
          detectedChips.innerHTML = chips.join('');
          detectedPanel.style.display = 'flex';
        } else {
          detectedPanel.style.display = 'none';
        }
      }
    } catch (_) {
      // Attribute extraction is progressive enhancement; non-fatal
      detectedPanel.style.display = 'none';
    }
  }

  // Execute Search
  async function performHomeSearch() {
    const q = (queryInput?.value || '').trim();
    const hasPhotos = selectedPhotos.length > 0;
    const cat = catSelect?.value || '';
    const color = colorSelect?.value || '';
    const shape = shapeSelect?.value || '';
    const targetType = typeSelect?.value || '';

    if (!q && !hasPhotos && !cat && !color && !shape) {
      Foundly.toast('Please enter a description, select an attribute, or drop a photo.', true);
      queryInput?.focus();
      return;
    }

    if (!resultsArea || !resultsGrid) return;

    searchBtn.disabled = true;
    searchBtn.innerHTML = `<span>Searching…</span>`;
    resultsArea.style.display = 'block';
    resultsGrid.innerHTML = `
      <div class="skeleton card-skeleton"></div>
      <div class="skeleton card-skeleton"></div>
      <div class="skeleton card-skeleton"></div>
    `;
    resultsArea.scrollIntoView({ behavior: 'smooth', block: 'start' });

    try {
      let data;
      if (hasPhotos) {
        // Multi-modal attribute search with query images
        const fd = new FormData();
        selectedPhotos.forEach(f => fd.append('files', f, f.name));
        if (q) fd.append('nl_query', q);
        if (cat) fd.append('category', cat);
        if (color) fd.append('primary_color', color);
        if (shape) fd.append('shape', shape);
        if (targetType) fd.append('target_type', targetType);

        data = await Foundly.api('/api/attributes/search', {
          method: 'POST',
          body: fd,
        });
      } else {
        // Text and structured attribute search
        const payload = {};
        if (q) payload.nl_query = q;
        if (cat) payload.category = cat;
        if (color) payload.primary_color = color;
        if (shape) payload.shape = shape;
        if (targetType) payload.target_type = targetType;

        data = await Foundly.api('/api/attributes/search', {
          method: 'POST',
          body: payload,
        });
      }

      const matches = data.matches || [];
      const count = matches.length;
      resultsTitle.textContent = `${count} ${count === 1 ? 'Candidate Match' : 'Candidate Matches'} Found`;

      if (count === 0) {
        resultsGrid.innerHTML = `
          <div class="empty-state">
            <div class="placeholder-icon">🔍</div>
            <h3>No matching listings found</h3>
            <p>Try adjusting your search query, clearing specific filters, or checking back later as new reports arrive.</p>
            <div style="display:flex;gap:10px;justify-content:center;margin-top:12px;">
              <a class="button button-small" href="/browse">Browse All Listings</a>
              <a class="button button-small button-light" href="/report/lost">File a Lost Report</a>
            </div>
          </div>
        `;
        return;
      }

      resultsGrid.innerHTML = matches.map(m => {
        const type = Foundly.escape(m.report_type || 'report');
        const name = Foundly.escape(m.item_name || 'Unnamed Item');
        const cat = Foundly.escape(m.category || '');
        const score = Math.round(Number(m.match_score || 0));
        const dt = Foundly.date(m.event_date);
        const loc = Foundly.escape(m.location_text || 'Campus');
        const id = Number(m.report_id);

        const reasons = (m.explanation?.reasons || []).slice(0, 2);
        const reasonsHtml = reasons.length > 0 
          ? `<div class="match-reasons-preview">${reasons.map(r => `<span class="reason-tag">✓ ${Foundly.escape(r)}</span>`).join('')}</div>`
          : '';

        return `
          <div class="report-card match-result-card" data-id="${id}">
            <div class="report-image">
              <span class="status-pill ${type}">${type}</span>
              <span class="score-pill">${score}/100</span>
              <span class="image-placeholder">✳</span>
            </div>
            <div class="report-info">
              <h3>${name}</h3>
              <p>${cat} · ${loc}</p>
              ${reasonsHtml}
              <div class="report-location">
                <span>⌖</span>
                <span>${dt}</span>
                <a href="/reports/${id}" class="text-link" style="margin-left:auto;">View details →</a>
              </div>
            </div>
          </div>
        `;
      }).join('');

      // Asynchronously populate candidate thumbnails
      await Promise.all(
        [...resultsGrid.querySelectorAll('.match-result-card')].map(async (card, idx) => {
          const item = matches[idx];
          if (!item) return;
          const url = item.primary_image_url || await Foundly.imageFor(item.report_id);
          if (url) {
            const imgBox = card.querySelector('.report-image');
            if (imgBox) {
              imgBox.insertAdjacentHTML(
                'beforeend',
                `<img src="${Foundly.escape(url)}" alt="${Foundly.escape(item.item_name)}" loading="lazy" onerror="this.remove()">`
              );
            }
          }
        })
      );

    } catch (err) {
      resultsTitle.textContent = 'Search Error';
      resultsGrid.innerHTML = `
        <div class="empty-state error" style="grid-column:1/-1;">
          <h3>Could not complete search</h3>
          <p>${Foundly.escape(err.message)}</p>
          <button type="button" class="button button-small button-light" id="btn-retry-home-search">Try Again</button>
        </div>
      `;
      document.querySelector('#btn-retry-home-search')?.addEventListener('click', performHomeSearch);
    } finally {
      searchBtn.disabled = false;
      searchBtn.innerHTML = `<span>Search</span> <span aria-hidden="true">→</span>`;
    }
  }

  if (searchBtn) {
    searchBtn.addEventListener('click', performHomeSearch);
  }

  if (queryInput) {
    queryInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        performHomeSearch();
      }
    });
  }

  if (clearResultsBtn) {
    clearResultsBtn.addEventListener('click', () => {
      if (resultsArea) resultsArea.style.display = 'none';
      if (queryInput) queryInput.value = '';
      selectedPhotos = [];
      renderPhotoPreviews();
    });
  }
});
