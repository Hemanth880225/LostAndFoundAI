/**
 * Foundly - Matches Ranking & Explainable AI Reasoning Handler
 */

document.addEventListener('DOMContentLoaded', async () => {
  const root = document.querySelector('.matches-page');
  if (!root) return;
  const id = root.dataset.id;
  const list = document.querySelector('#matches-list');
  const state = document.querySelector('#matches-state');
  const intro = document.querySelector('#matches-intro');

  async function loadMatches() {
    state.style.display = 'block';
    list.style.display = 'none';
    state.className = 'state-panel';
    state.innerHTML = `
      <div class="skeleton card-skeleton" style="height:120px;margin-bottom:12px;"></div>
      <div class="skeleton card-skeleton" style="height:120px;"></div>
    `;

    try {
      const result = await Foundly.api(`/api/reports/${id}/matches`);
      const count = result.candidate_count || 0;
      if (intro) {
        intro.textContent = `${count} ${count === 1 ? 'possible candidate' : 'possible candidates'} compared with report #${id}.`;
      }

      if (!result.matches || !result.matches.length) {
        state.style.display = 'block';
        state.innerHTML = `
          <div class="empty-state">
            <div class="placeholder-icon">⌕</div>
            <h3>No similar reports found yet</h3>
            <p>Our AI matching engine checked all active listings. As new reports are filed, they will automatically be evaluated against your report.</p>
            <div style="display:flex;gap:10px;justify-content:center;margin-top:14px;">
              <a class="button button-small" href="/browse">Browse all reports</a>
              <a class="button button-small button-light" href="/reports/${id}">Back to report</a>
            </div>
          </div>
        `;
        return;
      }

      state.style.display = 'none';
      list.style.display = 'grid';

      list.innerHTML = result.matches.map((m, idx) => {
        const repId = Number(m.report_id);
        const name = Foundly.escape(m.item_name || 'Item');
        const cat = Foundly.escape(m.category || '');
        const type = Foundly.escape(m.report_type || 'report');
        const loc = Foundly.escape(m.location_text || 'Campus');
        const dt = Foundly.date(m.event_date);
        const score = Math.round(Number(m.match_score || 0));

        // Signal chips
        const componentLabels = {
          image: 'Visual photo',
          text: 'Description',
          attributes: 'Physical traits',
          location: 'Location',
          time: 'Date compatibility',
        };

        const signalChips = Object.entries(m.score_components || {})
          .filter(([_, val]) => val !== null && val !== undefined)
          .map(([k, v]) => {
            const label = componentLabels[k] || k;
            const pct = Math.round(Number(v) * 100);
            return `<span class="signal">${Foundly.escape(label)} ${pct}%</span>`;
          }).join('');

        // Explainable reasoning from backend match_explanation
        const explanation = m.match_explanation || {};
        const reasons = explanation.reasons || [];
        const sharedFeatures = explanation.shared_distinctive_features || [];
        const breakdown = explanation.attribute_breakdown || {};

        let reasonsHtml = '';
        if (reasons.length > 0) {
          reasonsHtml = `
            <div class="match-reasons-block">
              <strong>Match Evidence:</strong>
              <ul>
                ${reasons.map(r => `<li>${Foundly.escape(r)}</li>`).join('')}
              </ul>
            </div>
          `;
        }

        let sharedFeaturesHtml = '';
        if (sharedFeatures.length > 0) {
          sharedFeaturesHtml = `
            <div class="shared-features-tag">
              ★ Shared Distinctive Feature: <b>${Foundly.escape(sharedFeatures.join(', '))}</b>
            </div>
          `;
        }

        // Drawer toggle id
        const drawerId = `breakdown-drawer-${idx}`;
        let breakdownRows = '';
        if (Object.keys(breakdown).length > 0) {
          breakdownRows = Object.entries(breakdown).map(([k, v]) => `
            <tr>
              <td>${Foundly.escape(k.replace('_', ' '))}</td>
              <td>${Foundly.escape(v)}</td>
            </tr>
          `).join('');
        }

        return `
          <article class="match-card modern-match-card" data-report="${repId}">
            <div class="match-thumb">
              <span class="status-pill ${type}">${type}</span>
              <span class="image-placeholder">✳</span>
            </div>

            <div class="match-body">
              <div class="match-title-row">
                <h2>${name}</h2>
                <span class="match-score-badge">${score}/100 similarity</span>
              </div>
              <p class="match-meta-line">${cat} · ⌖ ${loc} · ${dt}</p>

              ${sharedFeaturesHtml}
              ${reasonsHtml}

              <div class="match-signals">
                ${signalChips}
              </div>

              ${breakdownRows ? `
                <button type="button" class="btn-toggle-breakdown" data-target="${drawerId}">
                  <span>View attribute comparison</span> ▾
                </button>
                <div id="${drawerId}" class="attribute-comparison-drawer" style="display:none">
                  <table class="comparison-table">
                    <tbody>${breakdownRows}</tbody>
                  </table>
                </div>
              ` : ''}
            </div>

            <div class="match-actions">
              <div class="score-bar-wrap">
                <small>Similarity score</small>
                <div class="score-bar">
                  <i style="width:${Math.max(5, Math.min(100, score))}%"></i>
                </div>
              </div>
              <a class="button button-small" href="/reports/${repId}">View Report →</a>
            </div>
          </article>
        `;
      }).join('');

      // Wire up attribute breakdown toggles
      list.querySelectorAll('.btn-toggle-breakdown').forEach(btn => {
        btn.addEventListener('click', () => {
          const targetId = btn.dataset.target;
          const drawer = document.getElementById(targetId);
          if (drawer) {
            const isHidden = drawer.style.display === 'none';
            drawer.style.display = isHidden ? 'block' : 'none';
            btn.querySelector('span').textContent = isHidden ? 'Hide attribute comparison' : 'View attribute comparison';
          }
        });
      });

      // Asynchronously load candidate report thumbnails
      await Promise.all(
        [...list.querySelectorAll('.match-card')].map(async card => {
          const repId = card.dataset.report;
          if (!repId) return;
          const url = await Foundly.imageFor(repId);
          if (url) {
            const thumb = card.querySelector('.match-thumb');
            if (thumb) {
              thumb.insertAdjacentHTML(
                'beforeend',
                `<img src="${Foundly.escape(url)}" alt="Candidate Photo" loading="lazy" onerror="this.remove()">`
              );
            }
          }
        })
      );

    } catch (err) {
      state.style.display = 'block';
      list.style.display = 'none';
      state.className = 'state-panel error';
      state.innerHTML = `
        <h3>Could not load matches</h3>
        <p>${Foundly.escape(err.message)}</p>
        <div style="display:flex;gap:10px;justify-content:center;margin-top:14px;">
          <button type="button" class="button button-small button-light" id="btn-retry-matches">Try Again</button>
          <a href="/reports/${id}" class="button button-small button-light">Back to report</a>
        </div>
      `;
      document.querySelector('#btn-retry-matches')?.addEventListener('click', loadMatches);
    }
  }

  loadMatches();
});
