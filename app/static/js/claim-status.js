/**
 * Claimant Status Portal Client Script
 */

document.addEventListener('DOMContentLoaded', async () => {
  const container = document.getElementById('claim-dossier');
  if (!container) return;

  const claimId = container.dataset.id;
  const stateNotice = document.getElementById('claim-state-notice');
  const actionCard = document.getElementById('action-required-card');
  const inquiryText = document.getElementById('inquiry-text-display');
  const respondForm = document.getElementById('respond-info-form');
  const uploadForm = document.getElementById('upload-evidence-form');
  const uploadFeedback = document.getElementById('upload-feedback');

  async function loadClaim() {
    try {
      const data = await Foundly.api(`/api/verification/claims/${claimId}/status`);
      renderClaim(data);
    } catch (err) {
      stateNotice.className = 'inline-state state-error';
      stateNotice.textContent = `Unable to load claim: ${err.message}`;
    }
  }

  function renderClaim(data) {
    stateNotice.hidden = true;
    container.hidden = false;

    // Status Pill
    const pillContainer = document.getElementById('status-pill-container');
    const statusMap = {
      submitted: { label: 'Submitted', class: 'status-pending' },
      under_review: { label: 'Under Review', class: 'status-under-review' },
      additional_information_required: { label: 'Info Required', class: 'status-action-required' },
      approved: { label: 'Approved', class: 'status-approved' },
      rejected: { label: 'Not Approved', class: 'status-rejected' },
      completed: { label: 'Recovery Completed', class: 'status-completed' },
      suspected_fraud_review: { label: 'Administrative Review', class: 'status-fraud' },
    };

    const sInfo = statusMap[data.verification_status] || { label: data.verification_status, class: 'status-pending' };
    pillContainer.innerHTML = `<span class="status-pill ${sInfo.class}">${Foundly.escape(sInfo.label)}</span>`;

    // Metadata
    document.getElementById('claim-created-date').textContent = Foundly.date(data.created_at);
    document.getElementById('public-status-message').textContent = data.public_status_message;
    document.getElementById('meta-claimant-name').textContent = data.claimant_name;
    document.getElementById('meta-contact-email').textContent = data.contact_email;

    const badge = document.getElementById('meta-verification-badge');
    if (data.email_verified || data.phone_verified) {
      badge.textContent = 'Verified Contact';
      badge.className = 'badge-verified';
    } else {
      badge.textContent = 'Unverified Contact';
      badge.className = 'badge-unverified';
    }

    const lostLink = document.getElementById('meta-lost-link');
    lostLink.href = `/reports/${data.lost_report_id}`;
    lostLink.textContent = `Report #${data.lost_report_id}`;

    // Additional info required prompt
    if (data.verification_status === 'additional_information_required' && data.additional_info_requested) {
      inquiryText.textContent = data.additional_info_requested;
      actionCard.hidden = false;
    } else {
      actionCard.hidden = true;
    }
  }

  // Handle Response to Information Request
  if (respondForm) {
    respondForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btn-submit-info');
      btn.disabled = true;
      btn.textContent = 'Submitting…';

      const fd = new FormData(respondForm);
      try {
        const res = await Foundly.api(`/api/verification/claims/${claimId}/additional-info`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ additional_info: fd.get('additional_info').trim() }),
        });
        Foundly.toast('Additional information submitted.');
        respondForm.reset();
        renderClaim(res);
      } catch (err) {
        Foundly.toast(`Submission failed: ${err.message}`, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = 'Submit Information';
      }
    });
  }

  // Handle Upload Evidence
  if (uploadForm) {
    uploadForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btn-upload-ev');
      btn.disabled = true;
      btn.textContent = 'Uploading securely…';
      uploadFeedback.hidden = true;

      const fd = new FormData(uploadForm);
      try {
        await Foundly.api(`/api/verification/claims/${claimId}/evidence`, {
          method: 'POST',
          body: fd,
        });
        uploadFeedback.className = 'form-feedback feedback-success';
        uploadFeedback.textContent = 'Ownership evidence uploaded successfully to private storage.';
        uploadFeedback.hidden = false;
        uploadForm.reset();
        Foundly.toast('Evidence uploaded.');
      } catch (err) {
        uploadFeedback.className = 'form-feedback feedback-error';
        uploadFeedback.textContent = `Upload failed: ${err.message}`;
        uploadFeedback.hidden = false;
      } finally {
        btn.disabled = false;
        btn.textContent = 'Upload Evidence';
      }
    });
  }

  loadClaim();
});
