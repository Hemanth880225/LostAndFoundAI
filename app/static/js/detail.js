/**
 * Foundly - Report Detail View Handler
 * Multi-photo gallery, detected attributes chips, verified claim submission & evidence upload.
 */

document.addEventListener('DOMContentLoaded', async () => {
  const content = document.querySelector('#detail-content');
  const state = document.querySelector('#detail-state');
  if (!content) return;
  const id = content.dataset.id;

  try {
    const r = await Foundly.api(`/api/reports/${id}`);
    document.title = `${r.item_name} — Foundly`;

    // 1. Photos & Multi-Image Gallery
    const imgs = await Foundly.api(`/api/reports/${id}/images`).catch(() => []);
    const detailImageContainer = content.querySelector('#detail-image');
    const galleryContainer = content.querySelector('#gallery-container');

    if (imgs && imgs.length > 0) {
      detailImageContainer.innerHTML = `
        <img src="${Foundly.escape(imgs[0].url)}" alt="${Foundly.escape(r.item_name)}" onerror="this.remove()">
      `;

      if (imgs.length > 1 && galleryContainer) {
        galleryContainer.innerHTML = `
          <div class="gallery-strip">
            ${imgs.map((img, idx) => `
              <div class="gallery-thumb ${idx === 0 ? 'active' : ''}" data-index="${idx}" tabindex="0" role="button">
                <img src="${Foundly.escape(img.url)}" alt="Thumbnail ${idx + 1}">
              </div>
            `).join('')}
          </div>
          <div class="image-counter">Photo 1 of ${imgs.length}</div>
        `;

        const counter = galleryContainer.querySelector('.image-counter');
        galleryContainer.querySelectorAll('.gallery-thumb').forEach(thumb => {
          function selectThumb() {
            const idx = Number(thumb.dataset.index);
            galleryContainer.querySelectorAll('.gallery-thumb').forEach(t => t.classList.remove('active'));
            thumb.classList.add('active');
            detailImageContainer.innerHTML = `
              <img src="${Foundly.escape(imgs[idx].url)}" alt="${Foundly.escape(r.item_name)}" onerror="this.remove()">
            `;
            if (counter) counter.textContent = `Photo ${idx + 1} of ${imgs.length}`;
          }

          thumb.addEventListener('click', selectThumb);
          thumb.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              selectThumb();
            }
          });
        });
      }
    }

    // 2. Badge, Title & Meta
    content.querySelector('#detail-badge').innerHTML = `
      <span class="status-pill ${Foundly.escape(r.report_type)}">${Foundly.escape(r.report_type)}</span>
    `;
    content.querySelector('#detail-name').textContent = r.item_name;
    content.querySelector('#detail-meta').textContent = `${r.category} · Event date: ${Foundly.date(r.event_date)}`;
    content.querySelector('#detail-description').textContent = r.description;

    // 3. Physical Traits / Attributes Extraction
    const attrCard = content.querySelector('#detail-attributes-section');
    const attrChips = content.querySelector('#detail-attributes-chips');
    try {
      const attrData = await Foundly.api(`/api/attributes/reports/${id}`);
      if (attrData && attrData.attributes && attrCard && attrChips) {
        const a = attrData.attributes;
        const chips = [];
        if (a.category) chips.push(`<span class="attr-chip highlight">${Foundly.escape(a.category)}</span>`);
        if (a.primary_color) chips.push(`<span class="attr-chip">Color: ${Foundly.escape(a.primary_color)}</span>`);
        if (a.secondary_color) chips.push(`<span class="attr-chip">Accent: ${Foundly.escape(a.secondary_color)}</span>`);
        if (a.shape) chips.push(`<span class="attr-chip">Shape: ${Foundly.escape(a.shape)}</span>`);
        if (a.size_category) chips.push(`<span class="attr-chip">Size: ${Foundly.escape(a.size_category)}</span>`);
        if (a.capacity_text) chips.push(`<span class="attr-chip">Volume: ${Foundly.escape(a.capacity_text)}</span>`);
        if (a.material) chips.push(`<span class="attr-chip">Material: ${Foundly.escape(a.material)}</span>`);
        if (a.distinctive_features && a.distinctive_features.length > 0) {
          a.distinctive_features.forEach(f => {
            chips.push(`<span class="attr-chip highlight">★ ${Foundly.escape(f)}</span>`);
          });
        }

        if (chips.length > 0) {
          attrChips.innerHTML = chips.join('');
          attrCard.style.display = 'block';
        }
      }
    } catch (_) {
      // Attributes progressive enhancement
    }

    // 4. Facts Table
    const facts = [
      ['Location', r.location_text],
      ['Date', Foundly.date(r.event_date)],
      ['Color', r.color],
      ['Brand / Model', [r.brand, r.model].filter(Boolean).join(' ')],
      ['Listing Status', r.status],
    ].filter(x => x[1]);

    content.querySelector('#detail-facts').innerHTML = facts.map(([k, v]) => `
      <div class="fact">
        <small>${Foundly.escape(k)}</small>
        <b>${Foundly.escape(v)}</b>
      </div>
    `).join('');

    // 5. Action Buttons
    content.querySelector('#detail-actions').innerHTML = `
      <a class="button" href="/reports/${r.id}/matches">See potential matches <span>↗</span></a>
      <a class="button button-light" href="/browse">Directory listings</a>
      <a class="button button-subtle" href="/travel-handover?search=${encodeURIComponent(r.location_text || '')}">Nearby safe handover 📍</a>
    `;

    // 6. Verified Claim Submission (Found items only)
    if (r.report_type === 'found') {
      const claimForm = content.querySelector('#claim-form');
      if (claimForm) {
        claimForm.hidden = false;
        claimForm.addEventListener('submit', async (e) => {
          e.preventDefault();
          const fd = new FormData(claimForm);
          const errEl = claimForm.querySelector('#claim-error');
          const submitBtn = claimForm.querySelector('#btn-submit-claim');
          errEl.textContent = '';
          submitBtn.disabled = true;
          submitBtn.textContent = 'Submitting verified claim…';

          try {
            const lostIdVal = Number(fd.get('lost_report_id'));
            if (!lostIdVal || Number.isNaN(lostIdVal)) {
              throw new Error('Please enter a valid numeric Lost Report ID.');
            }

            const payload = {
              lost_report_id: lostIdVal,
              claimant_name: (fd.get('claimant_name') || '').trim(),
              contact_email: (fd.get('contact_email') || '').trim(),
              contact_phone: (fd.get('contact_phone') || '').trim() || null,
              claim_message: (fd.get('claim_message') || '').trim(),
              serial_number: (fd.get('serial_number') || '').trim() || null,
              distinctive_marks: (fd.get('distinctive_marks') || '').trim() || null,
              privacy_consent: fd.get('privacy_consent') === 'on' || fd.get('privacy_consent') === 'true',
            };

            const claimRes = await Foundly.api(`/api/verification/claims/${r.id}`, {
              method: 'POST',
              body: payload,
            });

            // Save claim to local device storage
            Foundly.storage.addClaim(claimRes.id, r.id, payload.claimant_name);

            // Upload optional evidence file if selected
            const fileInput = claimForm.querySelector('input[name="evidence_file"]');
            if (fileInput && fileInput.files && fileInput.files.length > 0) {
              submitBtn.textContent = 'Uploading ownership evidence…';
              const evData = new FormData();
              evData.append('file', fileInput.files[0]);
              evData.append('evidence_type', 'purchase_receipt');
              evData.append('description', 'Initial claim proof document');
              evData.append('is_sensitive', 'false');

              await Foundly.api(`/api/verification/claims/${claimRes.id}/evidence`, {
                method: 'POST',
                body: evData,
              });
            }

            Foundly.toast(`Claim #${claimRes.id} submitted for review!`);
            location.assign(`/claims/${claimRes.id}`);

          } catch (err) {
            errEl.textContent = err.message || 'An error occurred while submitting your claim.';
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit Verified Claim ↗';
          }
        });
      }
    }

    content.hidden = false;
    state.hidden = true;

  } catch (err) {
    state.className = 'state-panel error';
    state.innerHTML = `
      <h3>Could not load report details</h3>
      <p>${Foundly.escape(err.message)}</p>
      <a class="button button-light" href="/browse">Return to directory</a>
    `;
  }
});
