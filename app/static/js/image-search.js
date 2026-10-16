document.addEventListener('DOMContentLoaded', () => {
  const box = document.querySelector('#query-upload-box');
  const input = document.querySelector('#query-image-input');
  const previewGrid = document.querySelector('#query-preview-grid');
  const targetSelect = document.querySelector('#target-type-select');
  const searchBtn = document.querySelector('#start-search-btn');
  const clearBtn = document.querySelector('#clear-search-btn');
  const errorEl = document.querySelector('#search-error');
  const statePanel = document.querySelector('#search-state');
  const resultsSection = document.querySelector('#search-results-section');
  const resultsGrid = document.querySelector('#results-grid');
  const resultsHeadline = document.querySelector('#results-headline');
  const resultsSubhead = document.querySelector('#results-subhead');

  // Attribute filter controls
  const toggleAttrBtn = document.querySelector('#toggle-attr-filter-btn');
  const attrContent = document.querySelector('#attribute-filter-content');
  const nlQueryInput = document.querySelector('#nl-query-input');
  const categorySelect = document.querySelector('#attr-category-select');
  const colorSelect = document.querySelector('#attr-color-select');
  const shapeSelect = document.querySelector('#attr-shape-select');
  const sizeSelect = document.querySelector('#attr-size-select');
  const materialSelect = document.querySelector('#attr-material-select');
  const distinctiveInput = document.querySelector('#attr-distinctive-input');
  const strictHardFilterChk = document.querySelector('#strict-hard-filter-chk');
  const attrPreviewPanel = document.querySelector('#query-attribute-preview');
  const attrChipsContainer = document.querySelector('#detected-attribute-chips');

  const MAX_FILE_SIZE = 5 * 1024 * 1024;
  const MAX_QUERY_IMAGES = 5;
  const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

  let queryFiles = []; // Array of { file: File, url: string }

  // Toggle attribute filter accordion
  if (toggleAttrBtn && attrContent) {
    toggleAttrBtn.addEventListener('click', () => {
      const isExpanded = toggleAttrBtn.getAttribute('aria-expanded') === 'true';
      toggleAttrBtn.setAttribute('aria-expanded', !isExpanded);
      attrContent.style.display = isExpanded ? 'none' : 'grid';
    });
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  async function analyzeQueryPhoto(file) {
    if (!file) {
      if (attrPreviewPanel) attrPreviewPanel.style.display = 'none';
      return;
    }
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await Foundly.api('/api/attributes/extract', {
        method: 'POST',
        body: fd,
      });

      if (res && res.attributes && attrPreviewPanel && attrChipsContainer) {
        const chips = [];
        const a = res.attributes;
        if (a.category) chips.push(`<span class="attr-chip highlight">${Foundly.escape(a.category)}</span>`);
        if (a.primary_color) chips.push(`<span class="attr-chip">Color: ${Foundly.escape(a.primary_color)}</span>`);
        if (a.shape) chips.push(`<span class="attr-chip">Shape: ${Foundly.escape(a.shape)}</span>`);
        if (a.size_category) chips.push(`<span class="attr-chip">Size: ${Foundly.escape(a.size_category)}</span>`);
        if (a.material) chips.push(`<span class="attr-chip">Material: ${Foundly.escape(a.material)}</span>`);
        if (a.distinctive_features && a.distinctive_features.length > 0) {
          a.distinctive_features.forEach(f => {
            chips.push(`<span class="attr-chip highlight">★ ${Foundly.escape(f)}</span>`);
          });
        }

        if (chips.length > 0) {
          attrChipsContainer.innerHTML = chips.join('');
          attrPreviewPanel.style.display = 'flex';
        } else {
          attrPreviewPanel.style.display = 'none';
        }
      }
    } catch (err) {
      console.warn('Could not analyze query photo attributes:', err);
    }
  }

  function renderPreviews() {
    if (queryFiles.length === 0) {
      previewGrid.style.display = 'none';
      previewGrid.innerHTML = '';
      clearBtn.style.display = 'none';
      if (attrPreviewPanel) attrPreviewPanel.style.display = 'none';
      return;
    }

    previewGrid.style.display = 'grid';
    clearBtn.style.display = 'inline-flex';

    previewGrid.innerHTML = queryFiles.map((item, index) => `
      <div class="preview-card">
        <button type="button" class="preview-card-remove" data-index="${index}" aria-label="Remove query photo">×</button>
        <div class="preview-card-thumb">
          <img src="${item.url}" alt="${Foundly.escape(item.file.name)}">
        </div>
        <div class="preview-card-meta">
          <span class="preview-card-name" title="${Foundly.escape(item.file.name)}">${Foundly.escape(item.file.name)}</span>
          <span class="preview-card-size">${formatBytes(item.file.size)}</span>
          <span class="preview-card-status ready">Query photo</span>
        </div>
      </div>
    `).join('');

    previewGrid.querySelectorAll('.preview-card-remove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = Number(btn.dataset.index);
        removeFile(idx);
      });
    });
  }

  function addFiles(fileList) {
    if (!fileList || fileList.length === 0) return;
    errorEl.textContent = '';

    const remainingSlots = MAX_QUERY_IMAGES - queryFiles.length;
    if (remainingSlots <= 0) {
      Foundly.toast(`You can upload at most ${MAX_QUERY_IMAGES} query photos.`, true);
      return;
    }

    const toAdd = Array.from(fileList).slice(0, remainingSlots);
    if (fileList.length > remainingSlots) {
      Foundly.toast(`Only the first ${remainingSlots} photos were added (max ${MAX_QUERY_IMAGES}).`, true);
    }

    let addedCount = 0;
    for (const f of toAdd) {
      if (!ALLOWED_TYPES.includes(f.type)) {
        Foundly.toast(`"${f.name}" is not supported. Use JPEG, PNG, or WebP.`, true);
        continue;
      }
      if (f.size > MAX_FILE_SIZE) {
        Foundly.toast(`"${f.name}" exceeds 5 MiB limit.`, true);
        continue;
      }

      const isDup = queryFiles.some(existing => existing.file.name === f.name && existing.file.size === f.size);
      if (isDup) continue;

      const url = URL.createObjectURL(f);
      queryFiles.push({ file: f, url: url });
      addedCount++;
    }

    if (addedCount > 0) {
      renderPreviews();
      // Analyze the first query photo for instant visual feedback
      if (queryFiles.length > 0) {
        analyzeQueryPhoto(queryFiles[0].file);
      }
    }
  }

  function removeFile(index) {
    if (index >= 0 && index < queryFiles.length) {
      URL.revokeObjectURL(queryFiles[index].url);
      queryFiles.splice(index, 1);
      renderPreviews();
      if (queryFiles.length > 0) {
        analyzeQueryPhoto(queryFiles[0].file);
      } else {
        if (attrPreviewPanel) attrPreviewPanel.style.display = 'none';
      }
    }
  }

  function clearAll() {
    queryFiles.forEach(item => URL.revokeObjectURL(item.url));
    queryFiles = [];
    if (input) input.value = '';
    renderPreviews();
    if (nlQueryInput) nlQueryInput.value = '';
    if (categorySelect) categorySelect.value = '';
    if (colorSelect) colorSelect.value = '';
    if (shapeSelect) shapeSelect.value = '';
    if (sizeSelect) sizeSelect.value = '';
    if (materialSelect) materialSelect.value = '';
    if (distinctiveInput) distinctiveInput.value = '';
    if (strictHardFilterChk) strictHardFilterChk.checked = false;
    if (attrPreviewPanel) attrPreviewPanel.style.display = 'none';

    statePanel.className = 'state-panel';
    statePanel.style.display = 'block';
    statePanel.innerHTML = `
      <div class="placeholder-icon">⌕</div>
      <h3>Ready to search</h3>
      <p>Select photos or enter physical attributes above to begin matching.</p>
    `;
    resultsSection.style.display = 'none';
    resultsGrid.innerHTML = '';
  }

  if (clearBtn) clearBtn.addEventListener('click', clearAll);

  if (box && input) {
    box.addEventListener('click', () => input.click());
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        input.click();
      }
    });

    input.addEventListener('change', () => {
      addFiles(input.files);
      input.value = '';
    });

    ['dragenter', 'dragover'].forEach(name => {
      box.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        box.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(name => {
      box.addEventListener(name, (e) => {
        e.preventDefault();
        e.stopPropagation();
        box.classList.remove('dragover');
      });
    });

    box.addEventListener('drop', (e) => {
      if (e.dataTransfer && e.dataTransfer.files) {
        addFiles(e.dataTransfer.files);
      }
    });
  }

  // Handle Search Submission
  searchBtn.addEventListener('click', async () => {
    errorEl.textContent = '';
    searchBtn.disabled = true;
    searchBtn.textContent = 'Searching database…';

    statePanel.style.display = 'block';
    statePanel.className = 'state-panel';
    statePanel.innerHTML = `
      <div class="placeholder-icon">✳</div>
      <h3>Analyzing multi-modal attributes & CLIP vectors…</h3>
      <p>Comparing visual embeddings, physical traits, and distinctive features against active reports.</p>
    `;
    resultsSection.style.display = 'none';

    try {
      const fd = new FormData();
      queryFiles.forEach(item => {
        fd.append('files', item.file, item.file.name);
      });

      const target = targetSelect.value;
      if (target) fd.append('target_type', target);

      const qText = nlQueryInput ? nlQueryInput.value.trim() : '';
      if (qText) fd.append('query_text', qText);

      const cat = categorySelect ? categorySelect.value : '';
      if (cat) fd.append('category', cat);

      const pColor = colorSelect ? colorSelect.value : '';
      if (pColor) fd.append('primary_color', pColor);

      const shape = shapeSelect ? shapeSelect.value : '';
      if (shape) fd.append('shape', shape);

      const size = sizeSelect ? sizeSelect.value : '';
      if (size) fd.append('size_category', size);

      const mat = materialSelect ? materialSelect.value : '';
      if (mat) fd.append('material', mat);

      const dist = distinctiveInput ? distinctiveInput.value.trim() : '';
      if (dist) fd.append('distinctive_features', dist);

      if (strictHardFilterChk && strictHardFilterChk.checked) {
        const hardList = [];
        if (cat) hardList.push('category');
        if (pColor) hardList.push('primary_color');
        if (shape) hardList.push('shape');
        if (size) hardList.push('size_category');
        if (mat) hardList.push('material');
        fd.append('hard_filters', JSON.stringify(hardList));
      }

      const res = await Foundly.api('/api/attributes/search', {
        method: 'POST',
        body: fd,
      });

      searchBtn.disabled = false;
      searchBtn.innerHTML = 'Search matching items <span>⌕</span>';

      if (!res.matches || res.matches.length === 0) {
        statePanel.innerHTML = `
          <div class="empty-state">
            <div class="placeholder-icon">⌕</div>
            <h3>No matching reports found</h3>
            <p>We searched all active ${target ? target + ' ' : ''}reports, but found no candidates meeting the criteria. Try loosening filters or uploading an alternative photo.</p>
            <a class="button button-small" href="/browse">Browse all reports</a>
          </div>
        `;
        return;
      }

      statePanel.style.display = 'none';
      resultsSection.style.display = 'block';

      const count = res.matches.length;
      resultsHeadline.textContent = `${count} potential ${count === 1 ? 'match' : 'matches'} found`;
      resultsSubhead.textContent = `Ranked by multi-modal AI matching (CLIP embeddings + physical and visual attributes).`;

      resultsGrid.innerHTML = res.matches.map(m => {
        const photoUrl = m.best_image_url || null;
        const photoCountBadge = m.candidate_image_count > 1 
          ? `<span style="position:absolute;bottom:8px;right:8px;background:rgba(23,35,60,0.8);color:#fff;font-size:10px;padding:2px 6px;border-radius:4px;">+${m.candidate_image_count - 1} photos</span>` 
          : '';

        const imageHtml = photoUrl
          ? `<img src="${Foundly.escape(photoUrl)}" alt="${Foundly.escape(m.item_name)}" onerror="this.remove()">`
          : '<span class="image-placeholder">✳</span>';

        // Reason tags
        const reasons = (m.explanation && m.explanation.reasons) ? m.explanation.reasons : [];
        const sharedFeatures = (m.explanation && m.explanation.shared_distinctive_features) ? m.explanation.shared_distinctive_features : [];

        const tagsHtml = [
          ...sharedFeatures.map(f => `<span class="reason-tag feature">★ ${Foundly.escape(f)}</span>`),
          ...reasons.slice(0, 3).map(r => `<span class="reason-tag match">✓ ${Foundly.escape(r)}</span>`),
        ].join('');

        // Breakdown items
        const breakdown = (m.explanation && m.explanation.attribute_breakdown) ? m.explanation.attribute_breakdown : {};
        const breakdownItems = Object.entries(breakdown).map(([k, v]) => `<li><b>${Foundly.escape(k)}:</b> ${Foundly.escape(v)}</li>`).join('');

        const calibrationNote = (m.explanation && m.explanation.confidence_calibration_note) ? m.explanation.confidence_calibration_note : '';

        return `
          <article class="report-card">
            <div class="report-image">
              <span class="status-pill ${Foundly.escape(m.report_type)}">${Foundly.escape(m.report_type)}</span>
              ${imageHtml}
              ${photoCountBadge}
            </div>
            <div class="report-info">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
                <h3>${Foundly.escape(m.item_name)}</h3>
                <span class="similarity-pill">${Foundly.escape(m.match_score)}% match</span>
              </div>
              <p>${Foundly.escape(m.category)}${m.color ? ' · ' + Foundly.escape(m.color) : ''}</p>
              <div class="report-location">
                <span>⌖</span>${Foundly.escape(m.location_text)} <span>·</span> ${Foundly.date(m.event_date)}
              </div>

              ${tagsHtml ? `<div class="match-reasons-container">${tagsHtml}</div>` : ''}

              <div style="margin-top:8px">
                <button type="button" class="explanation-details-toggle" onclick="const d = this.nextElementSibling; d.style.display = d.style.display === 'none' ? 'block' : 'none';">
                  View attribute breakdown ▾
                </button>
                <div class="explanation-drawer" style="display:none">
                  <ul>${breakdownItems}</ul>
                  ${calibrationNote ? `<small class="calibration-note">${Foundly.escape(calibrationNote)}</small>` : ''}
                </div>
              </div>

              <div style="margin-top:12px">
                <a class="button button-small button-light" style="width:100%" href="/reports/${m.report_id}">
                  View report details <span>↗</span>
                </a>
              </div>
            </div>
          </article>
        `;
      }).join('');

    } catch (err) {
      searchBtn.disabled = false;
      searchBtn.innerHTML = 'Search matching items <span>⌕</span>';
      statePanel.className = 'state-panel error';
      statePanel.innerHTML = `
        <h3>Search failed</h3>
        <p>${Foundly.escape(err.message || 'Could not perform attribute search.')}</p>
      `;
      errorEl.textContent = err.message || 'Attribute search error.';
    }
  });
});
