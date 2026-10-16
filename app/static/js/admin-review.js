/**
 * Reviewer Operations & Claim Verification Dashboard
 */

document.addEventListener('DOMContentLoaded', () => {
  const keyInput = document.getElementById('input-reviewer-key');
  const btnSaveKey = document.getElementById('btn-save-key');
  const authIcon = document.getElementById('auth-status-icon');
  const authTitle = document.getElementById('auth-status-title');
  const authDesc = document.getElementById('auth-status-desc');
  const filterPills = document.querySelectorAll('#admin-status-filters .category-pill');
  const claimsContainer = document.getElementById('claims-list-container');
  const claimsHeading = document.getElementById('claims-count-heading');
  const btnRefresh = document.getElementById('btn-refresh-claims');
  const dossierPlaceholder = document.getElementById('dossier-placeholder');
  const dossierContent = document.getElementById('dossier-content');

  let currentKey = sessionStorage.getItem('foundly_reviewer_key') || '';
  let activeStatusFilter = 'all';
  let activeClaimId = null;

  if (currentKey) {
    keyInput.value = currentKey;
    updateAuthUI(true);
    loadClaims();
  }

  function updateAuthUI(isAuth) {
    if (isAuth) {
      authIcon.textContent = '🔓';
      authTitle.textContent = 'Reviewer Key Connected';
      authDesc.textContent = 'Authorized reviewer session active in browser memory.';
      btnSaveKey.textContent = 'Disconnect';
    } else {
      authIcon.textContent = '🔒';
      authTitle.textContent = 'Reviewer Key Required';
      authDesc.textContent = 'Provide your authorized X-Reviewer-Key to unlock administrative endpoints.';
      btnSaveKey.textContent = 'Authenticate';
    }
  }

  btnSaveKey.addEventListener('click', () => {
    if (currentKey) {
      // Disconnect
      currentKey = '';
      sessionStorage.removeItem('foundly_reviewer_key');
      keyInput.value = '';
      updateAuthUI(false);
      claimsContainer.innerHTML = '<div class="inline-state">Enter reviewer key and click Authenticate to load claims.</div>';
      dossierContent.hidden = true;
      dossierPlaceholder.hidden = false;
    } else {
      const val = keyInput.value.trim();
      if (!val) {
        Foundly.toast('Please enter a reviewer API key.', 'warning');
        return;
      }
      currentKey = val;
      sessionStorage.setItem('foundly_reviewer_key', currentKey);
      updateAuthUI(true);
      loadClaims();
    }
  });

  // Filter clicks
  filterPills.forEach((pill) => {
    pill.addEventListener('click', () => {
      filterPills.forEach((p) => p.classList.remove('active'));
      pill.classList.add('active');
      activeStatusFilter = pill.dataset.status;
      loadClaims();
    });
  });

  btnRefresh.addEventListener('click', () => loadClaims());

  async function apiReviewer(url, options = {}) {
    options.headers = options.headers || {};
    options.headers['X-Reviewer-Key'] = currentKey;
    return Foundly.api(url, options);
  }

  async function loadClaims() {
    if (!currentKey) return;

    claimsContainer.innerHTML = '<div class="inline-state">Loading claims…</div>';
    try {
      const claims = await apiReviewer(`/api/admin/claims?status_filter=${activeStatusFilter}&limit=50`);
      renderClaimsList(claims);
    } catch (err) {
      claimsContainer.innerHTML = `<div class="inline-state state-error">Failed to load claims: ${Foundly.escape(err.message)}</div>`;
    }
  }

  function renderClaimsList(claims) {
    claimsHeading.textContent = `${claims.length} Claim${claims.length === 1 ? '' : 's'}`;

    if (claims.length === 0) {
      claimsContainer.innerHTML = '<div class="inline-state">No claims found in this category.</div>';
      return;
    }

    claimsContainer.innerHTML = claims.map((c) => `
      <div class="admin-claim-card ${activeClaimId === c.claim_id ? 'active' : ''}" data-id="${c.claim_id}">
        <div class="claim-card-top">
          <span class="claim-card-id">#${c.claim_id}</span>
          <span class="status-pill status-${c.verification_status}">${Foundly.escape(c.verification_status.replace(/_/g, ' '))}</span>
        </div>
        <h4 class="claim-item-name">${Foundly.escape(c.item_name)}</h4>
        <div class="claim-claimant-info">
          <span>Claimant: <strong>${Foundly.escape(c.claimant_name)}</strong></span>
          <span class="claim-evidence-badge">📎 ${c.evidence_count} evidence file${c.evidence_count === 1 ? '' : 's'}</span>
        </div>
        <small class="claim-time">${Foundly.date(c.created_at)}</small>
      </div>
    `).join('');

    claimsContainer.querySelectorAll('.admin-claim-card').forEach((card) => {
      card.addEventListener('click', () => {
        claimsContainer.querySelectorAll('.admin-claim-card').forEach((c) => c.classList.remove('active'));
        card.classList.add('active');
        const id = parseInt(card.dataset.id, 10);
        inspectClaim(id);
      });
    });
  }

  async function inspectClaim(claimId) {
    activeClaimId = claimId;
    dossierPlaceholder.hidden = true;
    dossierContent.hidden = false;
    dossierContent.innerHTML = '<div class="inline-state">Loading claim verification dossier…</div>';

    try {
      const data = await apiReviewer(`/api/admin/claims/${claimId}`);
      renderDossier(data);
    } catch (err) {
      dossierContent.innerHTML = `<div class="inline-state state-error">Error loading dossier: ${Foundly.escape(err.message)}</div>`;
    }
  }

  function renderDossier(d) {
    const claim = d.claim;
    const v = d.verification_detail || {};
    const found = d.found_report || {};
    const lost = d.lost_report || {};

    const evidenceListHtml = d.evidence_files && d.evidence_files.length > 0
      ? d.evidence_files.map((ev) => `
          <div class="evidence-row">
            <div>
              <strong>${Foundly.escape(ev.description)}</strong>
              <small>${Foundly.escape(ev.evidence_type)} · ${ev.original_filename || 'File'} (${Math.round((ev.file_size_bytes || 0) / 1024)} KB)</small>
            </div>
            <a href="/api/admin/claims/${claim.id}/evidence/${ev.id}/file" target="_blank" class="button button-small button-subtle" download>
              Inspect File ↗
            </a>
          </div>
        `).join('')
      : '<p class="text-muted">No private evidence documents uploaded for this claim.</p>';

    const auditHtml = d.audit_logs && d.audit_logs.length > 0
      ? d.audit_logs.map((a) => `
          <div class="audit-item">
            <span class="audit-action">${Foundly.escape(a.action)}</span>
            <small>${Foundly.escape(a.actor_label)} · ${Foundly.date(a.timestamp)}</small>
            <p>${Foundly.escape(a.notes || '')}</p>
          </div>
        `).join('')
      : '<p class="text-muted">No audit logs recorded yet.</p>';

    dossierContent.innerHTML = `
      <div class="dossier-header-bar">
        <div>
          <h2>Claim Dossier #${claim.id}</h2>
          <span class="status-pill status-${v.verification_status || claim.status}">
            ${Foundly.escape((v.verification_status || claim.status).replace(/_/g, ' '))}
          </span>
        </div>
        <small>Submitted: ${Foundly.date(claim.created_at)}</small>
      </div>

      <!-- Comparison: Found Item vs Lost Item -->
      <div class="comparison-grid">
        <div class="comparison-col">
          <h4>Found Property Report #${found.id || ''}</h4>
          <p><strong>Item:</strong> ${Foundly.escape(found.item_name || 'N/A')}</p>
          <p><strong>Category:</strong> ${Foundly.escape(found.category || 'N/A')}</p>
          <p><strong>Location:</strong> ${Foundly.escape(found.location_text || 'N/A')}</p>
          <p><strong>Status:</strong> ${Foundly.escape(found.status || 'N/A')}</p>
        </div>
        <div class="comparison-col">
          <h4>Claimant's Lost Report #${lost.id || ''}</h4>
          <p><strong>Item:</strong> ${Foundly.escape(lost.item_name || 'N/A')}</p>
          <p><strong>Category:</strong> ${Foundly.escape(lost.category || 'N/A')}</p>
          <p><strong>Location:</strong> ${Foundly.escape(lost.location_text || 'N/A')}</p>
          <p><strong>Status:</strong> ${Foundly.escape(lost.status || 'N/A')}</p>
        </div>
      </div>

      <!-- Claimant Statement & Private Ownership Evidence -->
      <div class="dossier-section">
        <h3>Claimant Details & Private Identifiers</h3>
        <p><strong>Claimant:</strong> ${Foundly.escape(claim.claimant_name)} (${Foundly.escape(claim.contact_email)})</p>
        <p><strong>Phone:</strong> ${Foundly.escape(v.contact_phone || 'Not provided')} (${v.phone_verified ? 'Verified' : 'Unverified'})</p>
        <p><strong>Claim Statement:</strong> "${Foundly.escape(claim.claim_message)}"</p>
        <p><strong>Serial Number:</strong> ${Foundly.escape(v.serial_number || 'None provided')}</p>
        <p><strong>Distinctive Marks / Scratches:</strong> ${Foundly.escape(v.distinctive_marks || 'None provided')}</p>
        <p><strong>Private Identifying Features:</strong> ${Foundly.escape(v.identifying_features || 'None provided')}</p>
        ${v.additional_info_provided ? `<div class="info-provided-box"><strong>Additional Info Provided by Claimant:</strong><p>${Foundly.escape(v.additional_info_provided)}</p></div>` : ''}
      </div>

      <!-- Uploaded Evidence Files -->
      <div class="dossier-section">
        <h3>Secure Evidence Documents</h3>
        <div class="evidence-list">${evidenceListHtml}</div>
      </div>

      <!-- Reviewer Action Suite -->
      <div class="dossier-section action-suite-section">
        <h3>Reviewer Decision & Actions</h3>
        <div class="action-buttons-row">
          <button type="button" class="button button-small" id="btn-open-approve">Approve / Reject</button>
          <button type="button" class="button button-small button-light" id="btn-open-inquiry">Request Info</button>
          <button type="button" class="button button-small button-subtle" id="btn-open-fraud">Flag Suspected Fraud</button>
          <button type="button" class="button button-small button-subtle" id="btn-open-police">Police Draft</button>
          <button type="button" class="button button-small button-light" id="btn-open-reward">Credit Rewards</button>
        </div>

        <div id="action-form-container" class="action-form-container" hidden></div>
      </div>

      <!-- Audit History -->
      <div class="dossier-section">
        <h3>Audit Trail</h3>
        <div class="audit-list">${auditHtml}</div>
      </div>
    `;

    attachDossierActionHandlers(claim.id, d);
  }

  function attachDossierActionHandlers(claimId, d) {
    const container = document.getElementById('action-form-container');

    // 1. Approve / Reject
    document.getElementById('btn-open-approve').addEventListener('click', () => {
      container.hidden = false;
      container.innerHTML = `
        <form id="form-decide-claim" class="panel inner-action-panel">
          <h4>Record Review Decision</h4>
          <label class="field">
            <span>Decision</span>
            <select name="decision" required>
              <option value="approved">Approve Claim</option>
              <option value="rejected">Reject Claim</option>
            </select>
          </label>
          <label class="field">
            <span>Review Note (Factual justification recorded in audit log)</span>
            <textarea name="review_note" rows="3" required minlength="5" placeholder="e.g. Serial number and purchase invoice verified against found property."></textarea>
          </label>
          <button type="submit" class="button button-small">Submit Decision</button>
        </form>
      `;
      document.getElementById('form-decide-claim').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
          await apiReviewer(`/api/admin/claims/${claimId}/decide`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              decision: fd.get('decision'),
              review_note: fd.get('review_note'),
            }),
          });
          Foundly.toast('Claim decision recorded.');
          inspectClaim(claimId);
          loadClaims();
        } catch (err) {
          Foundly.toast(`Error: ${err.message}`, 'error');
        }
      });
    });

    // 2. Request Info
    document.getElementById('btn-open-inquiry').addEventListener('click', () => {
      container.hidden = false;
      container.innerHTML = `
        <form id="form-request-info" class="panel inner-action-panel">
          <h4>Request Additional Information</h4>
          <label class="field">
            <span>Inquiry Note to Claimant</span>
            <textarea name="request_note" rows="3" required minlength="5" placeholder="e.g. Please upload original packaging or state the contents of the front pocket."></textarea>
          </label>
          <button type="submit" class="button button-small">Send Request to Claimant</button>
        </form>
      `;
      document.getElementById('form-request-info').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
          await apiReviewer(`/api/admin/claims/${claimId}/request-info`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_note: fd.get('request_note') }),
          });
          Foundly.toast('Information requested from claimant.');
          inspectClaim(claimId);
          loadClaims();
        } catch (err) {
          Foundly.toast(`Error: ${err.message}`, 'error');
        }
      });
    });

    // 3. Flag Fraud
    document.getElementById('btn-open-fraud').addEventListener('click', () => {
      container.hidden = false;
      container.innerHTML = `
        <form id="form-flag-fraud" class="panel inner-action-panel">
          <h4>Escalate for Suspected Fraud Review</h4>
          <p class="text-muted"><small>This moves the claim to suspected_fraud_review. It is NOT made public.</small></p>
          <label class="field">
            <span>Documented Fraud Indicators</span>
            <textarea name="fraud_reason" rows="3" required minlength="10" placeholder="e.g. Claimant provided digitally altered invoice; serial number mismatch with device hardware."></textarea>
          </label>
          <button type="submit" class="button button-small" style="background:#dc2626;color:#fff">Escalate to Fraud Review</button>
        </form>
      `;
      document.getElementById('form-flag-fraud').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
          await apiReviewer(`/api/admin/claims/${claimId}/flag-fraud`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fraud_reason: fd.get('fraud_reason') }),
          });
          Foundly.toast('Claim escalated to fraud review.');
          inspectClaim(claimId);
          loadClaims();
        } catch (err) {
          Foundly.toast(`Error: ${err.message}`, 'error');
        }
      });
    });

    // 4. Police Draft
    document.getElementById('btn-open-police').addEventListener('click', () => {
      container.hidden = false;
      container.innerHTML = `
        <form id="form-police-draft" class="panel inner-action-panel">
          <h4>Generate Police Complaint Draft Packet</h4>
          <label class="field">
            <span>Target Police Jurisdiction</span>
            <input type="text" name="target_station" placeholder="e.g. Pune Cyber Crime Cell / Shivajinagar Police Station">
          </label>
          <button type="submit" class="button button-small">Generate Formal Draft Packet</button>
        </form>
        <div id="police-draft-preview" class="police-draft-preview" hidden></div>
      `;
      document.getElementById('form-police-draft').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
          const draft = await apiReviewer(`/api/admin/claims/${claimId}/police-draft`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_station: fd.get('target_station') || null }),
          });
          const preview = document.getElementById('police-draft-preview');
          preview.hidden = false;
          preview.innerHTML = `
            <div class="draft-box">
              <h4>Police Complaint Draft Packet [Ref: ${Foundly.escape(draft.draft_reference)}]</h4>
              <p><strong>Incident Summary:</strong> ${Foundly.escape(draft.incident_summary)}</p>
              <pre class="draft-pre">${Foundly.escape(draft.reviewer_observations)}\n\nTimeline:\n${Foundly.escape(draft.event_timeline)}</pre>
              <small>Status: ${Foundly.escape(draft.status)} (Ready for authorized human submission)</small>
            </div>
          `;
          Foundly.toast('Police complaint draft generated.');
        } catch (err) {
          Foundly.toast(`Error: ${err.message}`, 'error');
        }
      });
    });

    // 5. Credit Finder Rewards
    document.getElementById('btn-open-reward').addEventListener('click', () => {
      container.hidden = false;
      container.innerHTML = `
        <form id="form-credit-reward" class="panel inner-action-panel">
          <h4>Credit Verified Finder Recovery Reward</h4>
          <p class="text-muted"><small>Note: Handover must be completed before points can be credited. 5 points = ₹1.</small></p>
          <label class="field">
            <span>Verified Item Value in INR (₹)</span>
            <input type="number" step="0.01" min="50" name="verified_item_value" id="reward-item-val" required placeholder="e.g. 5000">
          </label>
          <div id="reward-preview-calc" class="reward-preview-calc"><small>Enter item value to preview reward points</small></div>
          <label class="field">
            <span>Finder / Helper Email</span>
            <input type="email" name="recipient_email" required placeholder="finder@college.edu">
          </label>
          <label class="field">
            <span>Reviewer Justification Note</span>
            <textarea name="notes" rows="2" required minlength="5" placeholder="e.g. Verified return of laptop. Value assessed based on verified invoice."></textarea>
          </label>
          <button type="submit" class="button button-small" style="background:#15803d;color:#fff">Credit Reward Points</button>
        </form>
      `;

      const valInput = document.getElementById('reward-item-val');
      const calcBox = document.getElementById('reward-preview-calc');
      valInput.addEventListener('input', async () => {
        const v = parseFloat(valInput.value);
        if (v > 0) {
          try {
            const p = await Foundly.api('/api/rewards/calculate-preview', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ item_value: v }),
            });
            calcBox.innerHTML = `<strong>Eligible Reward: ₹${p.eligible_reward_rupees} = ${p.points_awarded} Points</strong> ${p.is_capped ? '(Capped at max limit)' : ''}`;
          } catch (e) {
            calcBox.textContent = '';
          }
        }
      });

      document.getElementById('form-credit-reward').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
          const res = await apiReviewer('/api/rewards/credit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              claim_id: claimId,
              verified_item_value: parseFloat(fd.get('verified_item_value')),
              recipient_email: fd.get('recipient_email'),
              notes: fd.get('notes'),
            }),
          });
          Foundly.toast(`Success: Credited ${res.points} points to ${res.recipient_email}!`);
          container.hidden = true;
        } catch (err) {
          Foundly.toast(`Reward Credit Failed: ${err.message}`, 'error');
        }
      });
    });
  }
});
