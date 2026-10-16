/**
 * Foundly - Directory & Browse Page Handler
 * Multi-filter search (type, category, campus zone, keywords) with thumbnail loading and pagination.
 */

document.addEventListener('DOMContentLoaded', async () => {
  const grid = document.querySelector('#report-list');
  const typeFilter = document.querySelector('#type-filter');
  const categoryFilter = document.querySelector('#category-filter');
  const campusFilter = document.querySelector('#campus-filter');
  const searchInput = document.querySelector('#search-input');
  const countEl = document.querySelector('#result-count');
  const stateEl = document.querySelector('#browse-state');
  const loadMoreBtn = document.querySelector('#load-more');
  const clearBtn = document.querySelector('#clear-filters');

  let allLoaded = [];
  let offset = 0;
  let isBusy = false;
  const BATCH_SIZE = 24;

  function syncUrlParams() {
    const params = new URLSearchParams(location.search);
    if (typeFilter.value) params.set('report_type', typeFilter.value);
    else params.delete('report_type');

    if (categoryFilter.value) params.set('category', categoryFilter.value);
    else params.delete('category');

    if (campusFilter.value) params.set('campus', campusFilter.value);
    else params.delete('campus');

    if (searchInput.value.trim()) params.set('q', searchInput.value.trim());
    else params.delete('q');

    history.replaceState(null, '', `${location.pathname}${params.size ? '?' + params.toString() : ''}`);
  }

  function renderListings() {
    const q = (searchInput.value || '').trim().toLowerCase();
    const campus = (campusFilter.value || '').trim().toLowerCase();

    const filtered = allLoaded.filter(item => {
      // Keyword match
      if (q) {
        const hay = [
          item.item_name,
          item.category,
          item.description,
          item.location_text,
          item.color,
          item.brand,
        ].filter(Boolean).join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }

      // Campus zone match
      if (campus) {
        const loc = String(item.location_text || '').toLowerCase();
        if (!loc.includes(campus)) return false;
      }

      return true;
    });

    if (filtered.length === 0) {
      grid.innerHTML = '';
      stateEl.innerHTML = `
        <div class="empty-state">
          <div class="placeholder-icon">⌕</div>
          <h3>No reports matching your criteria</h3>
          <p>Try adjusting your search terms, changing the category, or clearing filters.</p>
          <button type="button" class="button button-small button-light" id="btn-empty-clear">Clear all filters</button>
        </div>
      `;
      document.querySelector('#btn-empty-clear')?.addEventListener('click', clearAll);
      countEl.textContent = '0 reports found';
      loadMoreBtn.hidden = true;
      return;
    }

    stateEl.innerHTML = '';
    grid.innerHTML = filtered.map(Foundly.card).join('');
    countEl.textContent = `Showing ${filtered.length} ${filtered.length === 1 ? 'report' : 'reports'}${q || campus ? ' matching filters' : ''}`;
    loadMoreBtn.hidden = allLoaded.length < offset;

    // Load thumbnails asynchronously
    Promise.all(
      [...grid.querySelectorAll('.report-card')].map(async card => {
        const id = card.dataset.id;
        if (!id) return;
        const url = await Foundly.imageFor(id);
        if (url) {
          const imgBox = card.querySelector('.report-image');
          if (imgBox) {
            imgBox.insertAdjacentHTML(
              'beforeend',
              `<img src="${Foundly.escape(url)}" alt="Item Photo" loading="lazy" onerror="this.remove()">`
            );
          }
        }
      })
    );
  }

  async function loadData(reset = false) {
    if (isBusy) return;
    isBusy = true;

    if (reset) {
      offset = 0;
      allLoaded = [];
      grid.innerHTML = `
        <div class="skeleton card-skeleton"></div>
        <div class="skeleton card-skeleton"></div>
        <div class="skeleton card-skeleton"></div>
      `;
    }

    stateEl.textContent = 'Loading listings…';

    try {
      const params = new URLSearchParams({
        limit: String(BATCH_SIZE),
        offset: String(offset),
      });

      if (typeFilter.value) params.set('report_type', typeFilter.value);
      if (categoryFilter.value) params.set('category', categoryFilter.value);

      const batch = await Foundly.api(`/api/reports?${params.toString()}`);
      allLoaded = allLoaded.concat(batch || []);
      offset += (batch || []).length;
      renderListings();

    } catch (err) {
      grid.innerHTML = '';
      stateEl.className = 'state-panel error';
      stateEl.innerHTML = `
        <h3>Could not load directory listings</h3>
        <p>${Foundly.escape(err.message)}</p>
        <button type="button" class="button button-light" id="btn-retry-browse">Try Again</button>
      `;
      document.querySelector('#btn-retry-browse')?.addEventListener('click', () => loadData(true));
    } finally {
      isBusy = false;
    }
  }

  function clearAll() {
    typeFilter.value = '';
    categoryFilter.value = '';
    campusFilter.value = '';
    searchInput.value = '';
    syncUrlParams();
    loadData(true);
  }

  // Restore state from URL query
  const queryParams = new URLSearchParams(location.search);
  if (queryParams.get('report_type')) typeFilter.value = queryParams.get('report_type');
  if (queryParams.get('category')) categoryFilter.value = queryParams.get('category');
  if (queryParams.get('campus')) campusFilter.value = queryParams.get('campus');
  if (queryParams.get('q')) searchInput.value = queryParams.get('q');

  typeFilter.addEventListener('change', () => {
    syncUrlParams();
    loadData(true);
  });

  categoryFilter.addEventListener('change', () => {
    syncUrlParams();
    loadData(true);
  });

  campusFilter.addEventListener('change', () => {
    syncUrlParams();
    renderListings();
  });

  searchInput.addEventListener('input', () => {
    syncUrlParams();
    renderListings();
  });

  if (clearBtn) clearBtn.addEventListener('click', clearAll);
  if (loadMoreBtn) loadMoreBtn.addEventListener('click', () => loadData(false));

  // Initial load
  loadData(true);
});
