/**
 * Rewards Programme & Points Calculator Client Script
 */

document.addEventListener('DOMContentLoaded', () => {
  const calcForm = document.getElementById('calc-form');
  const calcInput = document.getElementById('calc-item-val');
  const resRupees = document.getElementById('res-rupees');
  const resPoints = document.getElementById('res-points');

  const lookupForm = document.getElementById('lookup-form');
  const lookupEmail = document.getElementById('lookup-email');
  const balanceResult = document.getElementById('balance-result');
  const balPoints = document.getElementById('bal-total-points');
  const balRupees = document.getElementById('bal-total-rupees');
  const balCount = document.getElementById('bal-approved-count');
  const txContainer = document.getElementById('tx-history-container');

  // Calculator Submit
  if (calcForm) {
    calcForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const val = parseFloat(calcInput.value);
      if (isNaN(val) || val <= 0) return;

      try {
        const res = await Foundly.api('/api/rewards/calculate-preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ item_value: val }),
        });
        resRupees.textContent = `₹${res.eligible_reward_rupees.toFixed(2)}`;
        resPoints.textContent = `${res.points_awarded.toLocaleString()} Points`;
      } catch (err) {
        Foundly.toast(`Calculation error: ${err.message}`, 'error');
      }
    });

    // Auto calculate on input
    calcInput.addEventListener('input', () => {
      const val = parseFloat(calcInput.value);
      if (val > 0) {
        // Local estimation preview
        const raw = val * 0.10;
        const capped = Math.max(50, Math.min(raw, 2000));
        const pts = Math.floor(capped * 5);
        resRupees.textContent = `₹${capped.toFixed(2)}`;
        resPoints.textContent = `${pts.toLocaleString()} Points`;
      }
    });
  }

  // Balance Lookup
  if (lookupForm) {
    lookupForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = lookupEmail.value.trim();
      if (!email) return;

      const btn = document.getElementById('btn-lookup');
      btn.disabled = true;
      btn.textContent = 'Checking…';

      try {
        const res = await Foundly.api(`/api/rewards/balance/${encodeURIComponent(email)}`);
        balPoints.textContent = res.total_points.toLocaleString();
        balRupees.textContent = `₹${res.estimated_programme_value_rupees.toFixed(2)}`;
        balCount.textContent = res.approved_rewards_count;

        if (res.transactions && res.transactions.length > 0) {
          txContainer.innerHTML = res.transactions.map((t) => `
            <div class="tx-row ${t.points < 0 ? 'tx-negative' : 'tx-positive'}">
              <div class="tx-info">
                <strong>${t.points > 0 ? '+' : ''}${t.points} Points</strong>
                <small>${Foundly.escape(t.transaction_type)} · Report #${t.found_report_id}</small>
                <p>${Foundly.escape(t.notes)}</p>
              </div>
              <div class="tx-meta">
                <span class="tx-date">${Foundly.date(t.created_at)}</span>
                <small class="tx-id">${t.transaction_id.slice(0, 8)}…</small>
              </div>
            </div>
          `).join('');
        } else {
          txContainer.innerHTML = '<p class="text-muted">No reward transactions recorded for this email yet.</p>';
        }

        balanceResult.hidden = false;
      } catch (err) {
        Foundly.toast(`Lookup failed: ${err.message}`, 'error');
        balanceResult.hidden = true;
      } finally {
        btn.disabled = false;
        btn.textContent = 'Check Balance';
      }
    });
  }
});
