/* ROLLON AR — Performance Monitor + Error Wrapper + Self-Healing
   Inject at end of core.js. Zero user-visible impact. Silent operation.
   Logs latency > 500ms, auto-retries failures, heals data inconsistencies. */

(function(){
  'use strict';

  // ==================== PERFORMANCE MONITOR ====================
  const PERF_LOG = [];
  const SLOW_THRESHOLD = 500; // ms
  const MAX_LOG = 200;

  // Wrap native fetch to measure every API call
  const _origFetch = window.fetch;
  window.fetch = function(url, opts) {
    const start = performance.now();
    const method = (opts && opts.method) || 'GET';
    const endpoint = typeof url === 'string' ? url.split('?')[0] : 'unknown';

    return _origFetch.apply(this, arguments)
      .then(response => {
        const elapsed = Math.round(performance.now() - start);
        const entry = { endpoint, method, elapsed, status: response.status, ts: Date.now() };

        if (elapsed > SLOW_THRESHOLD) {
          console.warn(`[PERF] SLOW ${method} ${endpoint}: ${elapsed}ms`, entry);
          entry.slow = true;
        }

        PERF_LOG.push(entry);
        if (PERF_LOG.length > MAX_LOG) PERF_LOG.shift();

        // Clone response so we can inspect without consuming the body
        return response;
      })
      .catch(err => {
        const elapsed = Math.round(performance.now() - start);
        console.error(`[PERF] FAIL ${method} ${endpoint}: ${elapsed}ms`, err.message);
        PERF_LOG.push({ endpoint, method, elapsed, status: 0, error: err.message, ts: Date.now() });

        // Auto-retry GET requests once on network failure
        if (method === 'GET' && !url._retried) {
          console.warn(`[HEAL] Auto-retrying ${endpoint}...`);
          const retryUrl = typeof url === 'string' ? url : url;
          retryUrl._retried = true;
          return new Promise(r => setTimeout(r, 800)).then(() => _origFetch(retryUrl, opts));
        }
        throw err;
      });
  };

  // ==================== GLOBAL ERROR WRAPPER ====================
  // Catch all unhandled promise rejections (failed API calls that slip through)
  window.addEventListener('unhandledrejection', e => {
    const msg = e.reason?.message || String(e.reason || 'Unknown error');
    // Don't toast for AbortError (user navigated away) or minor issues
    if (msg.includes('AbortError') || msg.includes('signal')) return;
    console.error('[ERROR] Unhandled:', msg);
    // Only show toast for genuine failures, not race conditions
    if (msg.includes('NetworkError') || msg.includes('Failed to fetch')) {
      if (typeof toast === 'function') toast('Connection issue. Retrying...', 'error');
    }
    e.preventDefault(); // Prevent console noise
  });

  // Catch synchronous errors in event handlers
  window.addEventListener('error', e => {
    const msg = e.message || '';
    // Suppress known non-issues
    if (msg.includes('ResizeObserver') || msg.includes('Script error')) return;
    console.error('[ERROR] Runtime:', msg, 'at', e.filename, ':', e.lineno);
  });

  // ==================== DATA CONSISTENCY HEALER ====================
  // Runs silently after each detail modal render to check for common issues

  const _origRenderDetail = window.renderDetailModal;
  if (typeof _origRenderDetail === 'function') {
    window.renderDetailModal = function(record, headers, table) {
      // Call original
      _origRenderDetail.apply(this, arguments);

      // Silent consistency checks (non-blocking)
      setTimeout(() => healRecord(record, headers, table), 100);
    };
  }

  function healRecord(record, headers, table) {
    const fixes = [];

    if (table === 'directory') {
      // Check: Has email but still tagged "Need Email"
      const emailH = headers.find(h => cleanH(h).toLowerCase() === 'email');
      const tagsH = headers.find(h => cleanH(h).toLowerCase() === 'tags');
      if (emailH && tagsH) {
        const email = (record[emailH] || '').trim();
        const tags = (record[tagsH] || '');
        if (email && tags.includes('Need Email')) {
          fixes.push({ field: tagsH, action: 'remove_tag', tag: 'Need Email', reason: 'Has email but tagged Need Email' });
        }
        if (!email && !tags.includes('Need Email')) {
          fixes.push({ field: tagsH, action: 'add_tag', tag: 'Need Email', reason: 'No email but missing Need Email tag' });
        }
      }

      // Check: Has city but no country
      const cityH = headers.find(h => cleanH(h).toLowerCase() === 'city');
      const countryH = headers.find(h => cleanH(h).toLowerCase() === 'countries' || cleanH(h).toLowerCase() === 'country');
      if (cityH && countryH) {
        const city = (record[cityH] || '').trim();
        const country = (record[countryH] || '').trim();
        if (city && !country) {
          fixes.push({ field: 'city_country', action: 'flag', reason: `City "${city}" has no country` });
        }
      }
    }

    if (table === 'songs') {
      // Check: Has Ben Wylen in credits but no BW Collab tag
      const swH = headers.find(h => cleanH(h).toLowerCase().includes('songwriter credit'));
      const prodH = headers.find(h => cleanH(h).toLowerCase() === 'producer');
      const tagsH = headers.find(h => cleanH(h).toLowerCase() === 'tag' || cleanH(h).toLowerCase() === 'tags');
      if (tagsH) {
        const tags = record[tagsH] || '';
        const hasBW = [swH, prodH].some(h => h && (record[h] || '').toLowerCase().includes('ben wylen'));
        if (hasBW && !tags.includes('BW Collab')) {
          fixes.push({ field: tagsH, action: 'add_tag', tag: 'BW Collab', reason: 'Ben Wylen in credits but no BW Collab tag' });
        }
      }
    }

    // Apply silent fixes
    fixes.forEach(fix => {
      if (fix.action === 'flag') {
        console.info(`[HEAL] Flag: ${fix.reason}`);
        return;
      }

      const ri = record._row_index;
      const ep = table === 'songs' ? `/api/songs/${ri}` : `/api/directory/${ri}`;

      // Fetch fresh to avoid stale data
      _origFetch(ep).then(r => r.json()).then(fresh => {
        const currentTags = (fresh[fix.field] || '').split(' | ').map(t => t.trim()).filter(Boolean);

        if (fix.action === 'remove_tag' && currentTags.includes(fix.tag)) {
          const newTags = currentTags.filter(t => t !== fix.tag).join(' | ');
          const updateEp = table === 'songs' ? '/api/songs/update' : '/api/directory/update';
          _origFetch(updateEp, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ field: fix.field, row_index: ri, value: newTags })
          });
          console.info(`[HEAL] Auto-fixed: ${fix.reason} — removed "${fix.tag}"`);
        }

        if (fix.action === 'add_tag' && !currentTags.includes(fix.tag)) {
          currentTags.push(fix.tag);
          const newTags = currentTags.join(' | ');
          const updateEp = table === 'songs' ? '/api/songs/update' : '/api/directory/update';
          _origFetch(updateEp, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ field: fix.field, row_index: ri, value: newTags })
          });
          console.info(`[HEAL] Auto-fixed: ${fix.reason} — added "${fix.tag}"`);
        }
      }).catch(() => {}); // Silent fail
    });
  }

  // ==================== PREFETCH ENGINE ====================
  // Prefetch adjacent pages and common typeahead data on idle

  let _prefetchDone = {};

  function prefetchOnIdle() {
    if (typeof requestIdleCallback !== 'function') return;

    requestIdleCallback(() => {
      const table = window._currentTable;
      if (!table) return;

      // Prefetch page 2 if on page 1
      const page = (typeof S !== 'undefined' && S.page) || (typeof D !== 'undefined' && D.page) || 1;
      if (page === 1) {
        const ep = table === 'songs' ? '/api/songs?page=2&per_page=50' : '/api/directory?page=2&per_page=50';
        if (!_prefetchDone[ep]) {
          _origFetch(ep).then(() => { _prefetchDone[ep] = true; });
        }
      }

      // Prefetch tag/column data for typeahead
      const tagsEp = table === 'songs' ? '/api/songs/tags' : '/api/directory/tags';
      if (!_prefetchDone[tagsEp]) {
        _origFetch(tagsEp).then(() => { _prefetchDone[tagsEp] = true; });
      }
    });
  }

  // Run prefetch after initial page load
  if (document.readyState === 'complete') prefetchOnIdle();
  else window.addEventListener('load', () => setTimeout(prefetchOnIdle, 1000));

  // ==================== PERF DASHBOARD (dev only) ====================
  // Access via: ROLLON.perf() in browser console

  window.ROLLON = {
    perf() {
      const total = PERF_LOG.length;
      const slow = PERF_LOG.filter(e => e.slow).length;
      const failed = PERF_LOG.filter(e => e.status === 0).length;
      const avgMs = total ? Math.round(PERF_LOG.reduce((s, e) => s + e.elapsed, 0) / total) : 0;
      const slowest = PERF_LOG.reduce((max, e) => e.elapsed > (max?.elapsed || 0) ? e : max, null);

      console.table({
        'Total API calls': total,
        'Slow (>500ms)': slow,
        'Failed': failed,
        'Avg latency': avgMs + 'ms',
        'Slowest': slowest ? `${slowest.endpoint} (${slowest.elapsed}ms)` : 'N/A'
      });

      // Top 5 slowest endpoints
      const byEndpoint = {};
      PERF_LOG.forEach(e => {
        if (!byEndpoint[e.endpoint]) byEndpoint[e.endpoint] = [];
        byEndpoint[e.endpoint].push(e.elapsed);
      });
      const ranked = Object.entries(byEndpoint)
        .map(([ep, times]) => ({ endpoint: ep, avg: Math.round(times.reduce((a, b) => a + b, 0) / times.length), count: times.length, max: Math.max(...times) }))
        .sort((a, b) => b.avg - a.avg);
      console.log('\nTop 5 slowest endpoints:');
      console.table(ranked.slice(0, 5));

      return { total, slow, failed, avgMs, log: PERF_LOG };
    },

    health() {
      console.log('Running health check...');
      return Promise.all([
        _origFetch('/api/config').then(r => r.ok ? '✓ Config' : '✗ Config'),
        _origFetch('/api/songs?per_page=1').then(r => r.ok ? '✓ Songs API' : '✗ Songs API'),
        _origFetch('/api/directory?per_page=1').then(r => r.ok ? '✓ Directory API' : '✗ Directory API'),
        _origFetch('/api/songs/tags').then(r => r.ok ? '✓ Songs Tags' : '✗ Songs Tags'),
        _origFetch('/api/directory/tags').then(r => r.ok ? '✓ Directory Tags' : '✗ Directory Tags'),
      ]).then(results => {
        results.forEach(r => console.log('  ' + r));
        return results;
      });
    }
  };

})();
