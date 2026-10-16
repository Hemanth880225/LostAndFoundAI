/**
 * Foundly - Unified Reporting Form Handler
 * Handles structured Sections A (Attributes), B (Multi-Photo Uploader), C (Location & GPS), D (Submission)
 */

document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('#report-form');
  if (!form) return;

  const input = document.querySelector('#image-file');
  const box = document.querySelector('#upload-box');
  const previewGrid = document.querySelector('#image-preview-grid');
  const submitBtn = document.querySelector('#submit-report');
  const errorEl = document.querySelector('#form-error');

  const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MiB
  const MAX_IMAGES = 10;
  const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

  let selectedFiles = []; // Array of { id: string, file: File, url: string, status: 'ready'|'uploaded'|'error', error?: string }
  let createdId = null;

  // Set default event date to today if empty
  const dateInput = document.querySelector('#field-event-date');
  if (dateInput && !dateInput.value) {
    const today = new Date().toISOString().split('T')[0];
    dateInput.value = today;
  }

  // ---------------------------------------------------------------------------
  // 1. Campus Directory & Location Integration
  // ---------------------------------------------------------------------------
  const campusSelect = document.querySelector('#campus-location-select');
  const locInput = document.querySelector('#field-location-text');
  const latInput = document.querySelector('#field-latitude');
  const lonInput = document.querySelector('#field-longitude');
  const btnGps = document.querySelector('#btn-use-gps');
  const gpsLabel = document.querySelector('#gps-btn-label');

  // Load campus locations dynamically from API
  async function loadCampusLocations() {
    if (!campusSelect) return;
    try {
      const data = await Foundly.api('/api/campus/locations');
      if (data && data.zones && data.zones.length > 0) {
        campusSelect.innerHTML = '<option value="">Select campus zone…</option>';
        data.zones.forEach(zone => {
          const opt = document.createElement('option');
          opt.value = zone.zone_name;
          opt.textContent = `${zone.zone_name} (${zone.zone_code})`;
          opt.dataset.lat = zone.latitude || '';
          opt.dataset.lon = zone.longitude || '';
          campusSelect.appendChild(opt);
        });
        const otherOpt = document.createElement('option');
        otherOpt.value = 'Other / Off-Campus';
        otherOpt.textContent = 'Other / Off-Campus Location';
        campusSelect.appendChild(otherOpt);
      }
    } catch (_) {
      // Keep fallback hardcoded campus options in HTML
    }
  }

  loadCampusLocations();

  if (campusSelect && locInput) {
    campusSelect.addEventListener('change', () => {
      if (campusSelect.value && campusSelect.value !== 'Other / Off-Campus') {
        locInput.value = campusSelect.value;
        const selectedOpt = campusSelect.selectedOptions[0];
        if (selectedOpt && selectedOpt.dataset.lat && selectedOpt.dataset.lon) {
          if (latInput) latInput.value = selectedOpt.dataset.lat;
          if (lonInput) lonInput.value = selectedOpt.dataset.lon;
        }
      }
    });
  }

  // Optional GPS Location Button
  if (btnGps && locInput) {
    btnGps.addEventListener('click', () => {
      if (!navigator.geolocation) {
        Foundly.toast('Geolocation is not supported by your browser.', true);
        return;
      }

      btnGps.disabled = true;
      if (gpsLabel) gpsLabel.textContent = 'Locating…';

      navigator.geolocation.getCurrentPosition(
        async (position) => {
          const lat = position.coords.latitude;
          const lon = position.coords.longitude;
          if (latInput) latInput.value = lat.toFixed(6);
          if (lonInput) lonInput.value = lon.toFixed(6);

          if (gpsLabel) gpsLabel.textContent = 'Location set ✓';
          btnGps.disabled = false;

          // Attempt reverse geocode via backend safe handover service
          try {
            const geocodeResp = await Foundly.api(`/api/handover/nearby?lat=${lat}&lon=${lon}&radius_km=1.0&limit=1`);
            if (geocodeResp && geocodeResp.locations && geocodeResp.locations.length > 0) {
              const nearest = geocodeResp.locations[0];
              locInput.value = `Near ${nearest.name}, ${nearest.address || ''}`.trim();
              Foundly.toast(`Location set near ${nearest.name}`);
            } else {
              if (!locInput.value) {
                locInput.value = `GPS (${lat.toFixed(4)}, ${lon.toFixed(4)})`;
              }
              Foundly.toast('Coordinates acquired via GPS.');
            }
          } catch (_) {
            if (!locInput.value) {
              locInput.value = `Coordinates: ${lat.toFixed(4)}, ${lon.toFixed(4)}`;
            }
            Foundly.toast('Coordinates acquired via GPS.');
          }
        },
        (error) => {
          btnGps.disabled = false;
          if (gpsLabel) gpsLabel.textContent = 'Use GPS';
          let msg = 'Could not access GPS. Please type the location manually.';
          if (error.code === error.PERMISSION_DENIED) {
            msg = 'GPS permission denied. Please enter the location manually.';
          }
          Foundly.toast(msg, true);
        },
        { enableHighAccuracy: true, timeout: 8000 }
      );
    });
  }

  // ---------------------------------------------------------------------------
  // 2. Multi-Image Selection, Previews & Validation
  // ---------------------------------------------------------------------------
  function renderPreviews() {
    if (selectedFiles.length === 0) {
      previewGrid.style.display = 'none';
      previewGrid.innerHTML = '';
      return;
    }

    previewGrid.style.display = 'grid';
    previewGrid.innerHTML = selectedFiles.map((item, index) => {
      let statusBadge = '';
      if (item.status === 'uploaded') {
        statusBadge = '<span class="preview-card-status success">✓ Uploaded</span>';
      } else if (item.status === 'error') {
        statusBadge = `<span class="preview-card-status error" title="${Foundly.escape(item.error || 'Failed')}">⚠ Failed</span>`;
      } else {
        statusBadge = '<span class="preview-card-status ready">Ready to upload</span>';
      }

      const removeBtn = item.status === 'uploaded'
        ? ''
        : `<button type="button" class="preview-card-remove" data-index="${index}" aria-label="Remove ${Foundly.escape(item.file.name)}">×</button>`;

      return `
        <div class="preview-card">
          ${removeBtn}
          <div class="preview-card-thumb">
            <img src="${item.url}" alt="${Foundly.escape(item.file.name)}">
          </div>
          <div class="preview-card-meta">
            <span class="preview-card-name" title="${Foundly.escape(item.file.name)}">${Foundly.escape(item.file.name)}</span>
            <span class="preview-card-size">${Foundly.formatBytes(item.file.size)}</span>
            ${statusBadge}
            ${item.error ? `<small style="color:#b91c1c;font-size:9px;margin-top:2px">${Foundly.escape(item.error)}</small>` : ''}
          </div>
        </div>
      `;
    }).join('');

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

    const remainingSlots = MAX_IMAGES - selectedFiles.length;
    if (remainingSlots <= 0) {
      Foundly.toast(`You can upload at most ${MAX_IMAGES} photos.`, true);
      return;
    }

    const filesToAdd = Array.from(fileList).slice(0, remainingSlots);
    if (fileList.length > remainingSlots) {
      Foundly.toast(`Only the first ${remainingSlots} photos were added (max ${MAX_IMAGES}).`, true);
    }

    let addedCount = 0;
    for (const f of filesToAdd) {
      if (!ALLOWED_TYPES.includes(f.type)) {
        Foundly.toast(`"${f.name}" is not a supported format. Please use JPEG, PNG, or WebP.`, true);
        continue;
      }
      if (f.size > MAX_FILE_SIZE) {
        Foundly.toast(`"${f.name}" exceeds the 5 MiB size limit.`, true);
        continue;
      }

      // Check duplicate
      const isDuplicate = selectedFiles.some(existing =>
        existing.file.name === f.name && existing.file.size === f.size
      );
      if (isDuplicate) continue;

      const url = URL.createObjectURL(f);
      selectedFiles.push({
        id: Math.random().toString(36).substring(2, 9),
        file: f,
        url: url,
        status: 'ready',
      });
      addedCount++;
    }

    if (addedCount > 0) {
      renderPreviews();
    }
  }

  function removeFile(index) {
    if (index >= 0 && index < selectedFiles.length) {
      const removed = selectedFiles.splice(index, 1)[0];
      if (removed && removed.url) {
        URL.revokeObjectURL(removed.url);
      }
      renderPreviews();
    }
  }

  if (box && input) {
    box.addEventListener('click', () => {
      input.value = '';
      input.click();
    });

    box.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        input.value = '';
        input.click();
      }
    });

    input.addEventListener('change', () => {
      addFiles(input.files);
    });

    box.addEventListener('dragover', (e) => {
      e.preventDefault();
      box.classList.add('dragover');
    });

    box.addEventListener('dragleave', () => {
      box.classList.remove('dragover');
    });

    box.addEventListener('drop', (e) => {
      e.preventDefault();
      box.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files) {
        addFiles(e.dataTransfer.files);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // 3. E-Commerce Product Link Auto-fill
  // ---------------------------------------------------------------------------
  const productUrlInput = document.querySelector('#product-url-input');
  const btnEnrich = document.querySelector('#btn-enrich-product');
  const enrichStatus = document.querySelector('#enrich-status');

  if (btnEnrich && productUrlInput) {
    btnEnrich.addEventListener('click', async () => {
      const url = productUrlInput.value.trim();
      if (!url) {
        if (enrichStatus) enrichStatus.textContent = 'Please enter a product URL.';
        return;
      }
      btnEnrich.disabled = true;
      btnEnrich.textContent = 'Fetching…';
      if (enrichStatus) enrichStatus.textContent = 'Extracting product metadata safely…';

      try {
        const resp = await fetch('/api/product-links/enrich', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
        const data = await resp.json();

        if (data.extraction_status === 'failed' || data.error_message) {
          if (enrichStatus) enrichStatus.textContent = `Could not extract from link (${data.error_message || 'inaccessible'}). Enter details manually below.`;
        } else {
          const nameInput = form.querySelector('[name="item_name"]');
          const brandInput = form.querySelector('[name="brand"]');
          const colorSelect = form.querySelector('#field-primary-color');
          const categorySelect = form.querySelector('[name="category"]');

          if (data.title && nameInput && !nameInput.value) nameInput.value = data.title;
          if (data.brand && brandInput && !brandInput.value) brandInput.value = data.brand;
          if (data.color && colorSelect) {
            for (let opt of colorSelect.options) {
              if (opt.value && data.color.toLowerCase().includes(opt.value.toLowerCase())) {
                colorSelect.value = opt.value;
                break;
              }
            }
          }
          if (data.category && categorySelect && !categorySelect.value) {
            for (let opt of categorySelect.options) {
              if (opt.value && data.category.toLowerCase().includes(opt.value.toLowerCase())) {
                categorySelect.value = opt.value;
                break;
              }
            }
          }
          if (enrichStatus) enrichStatus.textContent = `✓ Details extracted from ${data.source_domain || 'link'}! Review and edit below.`;
          Foundly.toast('Product details auto-filled successfully.');
        }
      } catch (_) {
        if (enrichStatus) enrichStatus.textContent = 'Enrichment service unavailable. Reporting is unaffected; enter details below.';
      } finally {
        btnEnrich.disabled = false;
        btnEnrich.textContent = 'Auto-fill';
      }
    });
  }

  // ---------------------------------------------------------------------------
  // 4. Form Submission & Partial Image Upload Handling
  // ---------------------------------------------------------------------------
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (errorEl) errorEl.textContent = '';
    form.querySelectorAll('.field').forEach(f => f.classList.remove('invalid'));

    let valid = true;
    for (const el of form.querySelectorAll('input[required], select[required], textarea[required]')) {
      if (!el.checkValidity()) {
        valid = false;
        el.closest('.field')?.classList.add('invalid');
      }
    }

    if (!valid) {
      if (errorEl) errorEl.textContent = 'Please complete all required fields marked with *.';
      form.querySelector(':invalid')?.focus();
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = createdId ? 'Uploading remaining photos…' : 'Publishing report…';

    try {
      if (!createdId) {
        const fd = new FormData(form);

        // Synthesize multi-dimensional attributes into description for seamless human & AI extraction
        const primaryCol = (fd.get('primary_color') || '').trim();
        const secondaryCol = (fd.get('secondary_color') || '').trim();
        const shapeVal = (fd.get('shape') || '').trim();
        const sizeVal = (fd.get('size_category') || '').trim();
        const capVal = (fd.get('capacity_text') || '').trim();
        const matVal = (fd.get('material') || '').trim();
        const marksVal = (fd.get('distinctive_marks') || '').trim();
        const journeyVal = (fd.get('journey_context') || '').trim();

        // Build combined color string
        let combinedColor = primaryCol;
        if (primaryCol && secondaryCol) {
          combinedColor = `${primaryCol} with ${secondaryCol} accents`;
        }

        // Build enriched description
        const rawDesc = fd.get('description').trim();
        const extraTraits = [];
        if (shapeVal) extraTraits.push(`Shape: ${shapeVal}`);
        if (sizeVal) extraTraits.push(`Size: ${sizeVal}`);
        if (capVal) extraTraits.push(`Capacity: ${capVal}`);
        if (matVal) extraTraits.push(`Material: ${matVal}`);
        if (marksVal) extraTraits.push(`Distinctive marks: ${marksVal}`);
        if (journeyVal && journeyVal !== 'Walking / On-Foot') extraTraits.push(`Transit mode: ${journeyVal}`);

        let fullDesc = rawDesc;
        if (extraTraits.length > 0) {
          fullDesc = `${rawDesc}\n\n[Physical details: ${extraTraits.join(' · ')}]`;
        }

        // Validate latitude/longitude
        const latVal = latInput && latInput.value ? parseFloat(latInput.value) : null;
        const lonVal = lonInput && lonInput.value ? parseFloat(lonInput.value) : null;

        const payload = {
          report_type: form.dataset.type,
          item_name: fd.get('item_name').trim(),
          category: fd.get('category'),
          color: combinedColor || null,
          brand: (fd.get('brand') || '').trim() || null,
          model: null,
          description: fullDesc,
          event_date: fd.get('event_date'),
          location_text: fd.get('location_text').trim(),
          latitude: Number.isFinite(latVal) ? latVal : null,
          longitude: Number.isFinite(lonVal) ? lonVal : null,
        };

        const created = await Foundly.api('/api/reports', {
          method: 'POST',
          body: payload,
        });

        createdId = created.id;

        // Save report to local device storage
        Foundly.storage.addReport(createdId, payload.item_name, payload.report_type);
      }

      // Upload selected photos if present
      const pendingFiles = selectedFiles.filter(item => item.status !== 'uploaded');

      if (pendingFiles.length > 0) {
        submitBtn.textContent = `Uploading ${pendingFiles.length} photo(s)…`;

        const body = new FormData();
        pendingFiles.forEach(item => {
          body.append('files', item.file, item.file.name);
        });

        try {
          const uploadRes = await Foundly.api(`/api/reports/${createdId}/images/batch`, {
            method: 'POST',
            body: body,
          });

          // Check partial success
          if (uploadRes.failures && uploadRes.failures.length > 0) {
            const failureMap = new Map();
            uploadRes.failures.forEach(f => failureMap.set(f.filename, f.error));

            selectedFiles.forEach(item => {
              if (failureMap.has(item.file.name)) {
                item.status = 'error';
                item.error = failureMap.get(item.file.name);
              } else {
                item.status = 'uploaded';
                item.error = undefined;
              }
            });

            renderPreviews();

            const failedCount = uploadRes.failures.length;
            const successCount = uploadRes.successful_count || 0;
            submitBtn.disabled = false;
            submitBtn.textContent = 'Retry failed photos';
            if (errorEl) {
              errorEl.textContent = `Report #${createdId} was published and ${successCount} photo(s) saved, but ${failedCount} photo(s) failed. You can remove or retry them without creating a duplicate report.`;
            }
            return;
          }

          // All uploaded successfully
          selectedFiles.forEach(item => {
            item.status = 'uploaded';
            item.error = undefined;
          });
          renderPreviews();

        } catch (uploadError) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Retry photo upload';
          if (errorEl) {
            errorEl.textContent = `Report #${createdId} was created, but photo upload encountered an issue: ${uploadError.message}. You can retry without creating a duplicate report.`;
          }
          return;
        }
      }

      Foundly.toast(`Report #${createdId} published successfully!`);
      location.assign(`/reports/${createdId}`);

    } catch (err) {
      if (errorEl) {
        errorEl.textContent = err.message || 'An error occurred while saving the report.';
      }
      submitBtn.disabled = false;
      submitBtn.textContent = createdId ? 'Retry photo upload' : 'Publish Report ↗';
    }
  });
});
