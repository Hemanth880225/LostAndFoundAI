/**
 * Foundly - Central Frontend Utilities & Shared Application State
 * Polished, defensive, vanilla JavaScript foundation.
 */

(function () {
  'use strict';

  const STORAGE_KEYS = {
    REPORTS: 'foundly_user_reports',
    CLAIMS: 'foundly_user_claims',
    GUEST_CASES: 'foundly_guest_cases',
  };

  const Foundly = {
    /**
     * Unified HTTP API client for all backend endpoints.
     * Safely handles JSON, plain text, and multipart FormData.
     */
    api: async (url, options = {}) => {
      const fetchOpts = { ...options };
      const headers = { ...(options.headers || {}) };

      // Do NOT set Content-Type if body is FormData (browser needs to set multipart boundary)
      if (options.body instanceof FormData) {
        delete headers['Content-Type'];
      } else if (options.body && typeof options.body === 'object' && !(options.body instanceof Blob)) {
        headers['Content-Type'] = 'application/json';
        fetchOpts.body = JSON.stringify(options.body);
      }

      fetchOpts.headers = headers;

      let response;
      try {
        response = await fetch(url, fetchOpts);
      } catch (networkErr) {
        throw new Error('Network connection failed. Please check your connection and try again.');
      }

      const contentType = response.headers.get('content-type') || '';
      let data = null;

      if (contentType.includes('application/json')) {
        try {
          data = await response.json();
        } catch (_) {
          data = null;
        }
      } else {
        try {
          data = await response.text();
        } catch (_) {
          data = null;
        }
      }

      if (!response.ok) {
        let errorMsg = `Request failed with status ${response.status}.`;
        if (data && typeof data === 'object') {
          if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map(d => (d.msg ? `${d.loc ? d.loc.slice(-1) + ': ' : ''}${d.msg}` : JSON.stringify(d))).join(', ');
          } else if (data.detail) {
            errorMsg = data.detail;
          } else if (data.message) {
            errorMsg = data.message;
          }
        } else if (typeof data === 'string' && data.trim()) {
          errorMsg = data.slice(0, 200);
        }
        throw new Error(errorMsg);
      }

      return data;
    },

    /**
     * Safe HTML entity escaping to prevent XSS.
     */
    escape: (s = '') => {
      return String(s || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }[c]));
    },

    /**
     * Locale-aware date formatting.
     */
    date: (dateStr) => {
      if (!dateStr) return 'Date unavailable';
      try {
        const d = new Date(dateStr.includes('T') ? dateStr : `${dateStr}T00:00:00`);
        if (Number.isNaN(d.getTime())) return dateStr;
        return new Intl.DateTimeFormat(undefined, {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
        }).format(d);
      } catch (_) {
        return dateStr;
      }
    },

    /**
     * File size formatter in bytes / KB / MB.
     */
    formatBytes: (bytes) => {
      if (typeof bytes !== 'number' || bytes < 0) return '0 B';
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    },

    /**
     * Flash toast notification.
     */
    toast: (msg, isError = false) => {
      let region = document.querySelector('.toast-region');
      if (!region) {
        region = document.createElement('div');
        region.className = 'toast-region';
        region.setAttribute('aria-live', 'polite');
        region.setAttribute('aria-atomic', 'true');
        document.body.appendChild(region);
      }
      const t = document.createElement('div');
      t.className = 'toast' + (isError ? ' error' : '');
      t.textContent = msg;
      region.appendChild(t);
      setTimeout(() => {
        t.style.opacity = '0';
        t.style.transform = 'translateY(8px)';
        setTimeout(() => t.remove(), 300);
      }, 4200);
    },

    /**
     * Standard responsive item card HTML string.
     */
    card: (item) => {
      const type = Foundly.escape(item.report_type || 'report');
      const name = Foundly.escape(item.item_name || 'Unnamed Item');
      const cat = Foundly.escape(item.category || '');
      const color = item.color ? ` · ${Foundly.escape(item.color)}` : '';
      const loc = Foundly.escape(item.location_text || 'Location unavailable');
      const dt = Foundly.date(item.event_date);
      const id = Number(item.id);

      return `
        <a class="report-card" href="/reports/${id}" data-id="${id}">
          <div class="report-image">
            <span class="status-pill ${type}">${type}</span>
            <span class="image-placeholder">✳</span>
          </div>
          <div class="report-info">
            <h3>${name}</h3>
            <p>${cat}${color}</p>
            <div class="report-location">
              <span>⌖</span>
              <span>${loc}</span>
              <span>·</span>
              <span>${dt}</span>
            </div>
          </div>
        </a>
      `;
    },

    /**
     * Retrieve the primary image thumbnail URL for a report ID.
     */
    imageFor: async (reportId) => {
      try {
        const imgs = await Foundly.api(`/api/reports/${reportId}/images`);
        return imgs && imgs.length > 0 ? (imgs[0].url || `/uploads/${imgs[0].image_path.replace(/^uploads\//, '')}`) : null;
      } catch (_) {
        return null;
      }
    },

    /**
     * Local device storage for user's own reports, claims, and guest cases.
     * Preserves privacy without requiring an account.
     */
    storage: {
      getReports: () => {
        try {
          return JSON.parse(localStorage.getItem(STORAGE_KEYS.REPORTS) || '[]');
        } catch (_) {
          return [];
        }
      },
      addReport: (id, name, type) => {
        try {
          const list = Foundly.storage.getReports().filter(r => r.id !== id);
          list.unshift({ id, name, type, date: new Date().toISOString() });
          localStorage.setItem(STORAGE_KEYS.REPORTS, JSON.stringify(list.slice(0, 30)));
        } catch (_) {}
      },
      getClaims: () => {
        try {
          return JSON.parse(localStorage.getItem(STORAGE_KEYS.CLAIMS) || '[]');
        } catch (_) {
          return [];
        }
      },
      addClaim: (claimId, foundReportId, claimantName) => {
        try {
          const list = Foundly.storage.getClaims().filter(c => c.id !== claimId);
          list.unshift({ id: claimId, foundReportId, claimantName, date: new Date().toISOString() });
          localStorage.setItem(STORAGE_KEYS.CLAIMS, JSON.stringify(list.slice(0, 30)));
        } catch (_) {}
      },
      getGuestCases: () => {
        try {
          return JSON.parse(localStorage.getItem(STORAGE_KEYS.GUEST_CASES) || '[]');
        } catch (_) {
          return [];
        }
      },
      addGuestCase: (caseRef, secretKey, name, type) => {
        try {
          const list = Foundly.storage.getGuestCases().filter(c => c.caseRef !== caseRef);
          list.unshift({ caseRef, secretKey, name, type, date: new Date().toISOString() });
          localStorage.setItem(STORAGE_KEYS.GUEST_CASES, JSON.stringify(list.slice(0, 30)));
        } catch (_) {}
      },
    },
  };

  window.Foundly = Foundly;

  // Initialize responsive navigation toggle
  document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.querySelector('.menu-toggle');
    const nav = document.querySelector('.nav');
    if (toggle && nav) {
      toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = nav.classList.toggle('open');
        toggle.setAttribute('aria-expanded', String(isOpen));
      });

      // Close menu when clicking outside
      document.addEventListener('click', (e) => {
        if (!nav.contains(e.target) && !toggle.contains(e.target) && nav.classList.contains('open')) {
          nav.classList.remove('open');
          toggle.setAttribute('aria-expanded', 'false');
        }
      });
    }
  });
})();
