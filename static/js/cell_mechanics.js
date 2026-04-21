/* ==========================================================================
   ROLLON AR cell_mechanics.js  (v37.7 spreadsheet grid interactions)
   ==========================================================================
   F1 single cell selection + arrow/tab/enter/escape nav
   F2 Cmd+C / Cmd+Shift+C type aware serialization
   F3 Cmd+V type aware parsing, computed cell guard
   F4 drag fill handle (literal copy, single cell across range)
   F5 multi cell range (click drag, shift click, Cmd+A) + range copy / paste /
      delete + right click context menu
   F6 universal: cell_mechanics.js is loaded by templates/base.html on every
      authenticated page, so any grid built through buildGridV2 or
      buildGroupedGrid in core.js (Directory, Songs, Pitches, Invoices,
      Calendar) automatically inherits F1-F5 because every data cell carries
      data-field + data-ri and the listeners are attached at document level.
      Card-based pages (Scout, Playlists, Pitch Intelligence, Settings,
      Dashboard) intentionally fall outside scope until they migrate to the
      .data-grid renderer.
   --------------------------------------------------------------------------
   Replaces the V36.1 cellSelect/_selectedCell block previously in core.js.
   ========================================================================== */
(function(){
  'use strict';

  // ---- State ----
  let activeCell = null;      // primary cell (TD) — the currently selected cell
  let rangeAnchor = null;     // mouse-down corner of a range
  let rangeFoot = null;       // mouse-up corner of a range (== activeCell)
  let dragging = false;       // mouse-drag range selection in progress
  let dragFilling = false;    // fill-handle drag in progress
  let fillSource = null;      // the source cell whose value will be filled
  let fillSourceCells = [];   // F5: multi-cell drag-fill source pattern
  let lastUndo = null;        // { cells:[{ri,field,prev,td,table}] } for Cmd+Z

  // ---- Small helpers (depend on globals from core.js) ----
  function currentTable(){ return window._currentTable || 'directory'; }
  function isInsideEditor(el){
    return !!(el && (el.closest('.inline-edit') || el.closest('.tag-editor') || el.closest('.typeahead-wrap')));
  }
  function getCache(ri){ return (typeof cacheGet==='function') ? cacheGet(ri) : null; }
  function getFieldType(h){ return (typeof fieldType==='function') ? fieldType(h) : 'text'; }
  function toastMsg(msg, kind){
    if(typeof toast==='function') toast(msg, kind||'success');
    else console.log('[toast]', msg);
  }
  function normHeader(h){
    return (h||'')
      .replace(/\[\s*[✓✗∅?]+\s*\]/g,'')
      .replace(/\[USE\]|\[LU\]|\[Sync\]/gi,'')
      .trim()
      .toLowerCase();
  }

  // ---- Selection primitives ----
  function clearClasses(){
    document.querySelectorAll('td.cell-selected, td.cell-range').forEach(c => {
      c.classList.remove('cell-selected','cell-range');
    });
  }
  function removeFillHandle(){
    document.querySelectorAll('.cell-fill-handle').forEach(h => h.remove());
  }
  function paintRange(a,b){
    clearClasses();
    if(!a || !b) return;
    const cells = getCellsInRange(a,b);
    cells.forEach(td => td.classList.add('cell-range'));
    (b || a).classList.add('cell-selected');
  }
  function selectSingle(td){
    if(!td){
      removeFillHandle(); clearClasses();
      activeCell = null; rangeAnchor = null; rangeFoot = null; window._selectedCell = null;
      return;
    }
    // F6: short-circuit if the same single cell is already the live selection.
    // Avoids re-painting and recreating the fill handle on every inline-edit
    // blur that calls cellSelect(td) to restore highlight after save.
    if(activeCell === td && rangeAnchor === td && rangeFoot === td &&
       td.classList.contains('cell-selected') && td.querySelector('.cell-fill-handle')){
      return;
    }
    removeFillHandle();
    clearClasses();
    td.classList.add('cell-selected');
    activeCell = td; rangeAnchor = td; rangeFoot = td;
    attachFillHandle(td);
    // Keep compat with core.js inline-edit blur path that calls cellSelect(td)
    window._selectedCell = td;
  }
  function selectRange(a,b){
    removeFillHandle();
    paintRange(a,b);
    activeCell = b; rangeAnchor = a; rangeFoot = b;
    attachFillHandle(b);
    window._selectedCell = b;
  }
  function deselect(){
    removeFillHandle();
    clearClasses();
    activeCell = null; rangeAnchor = null; rangeFoot = null;
    window._selectedCell = null;
  }
  function attachFillHandle(td){
    if(!td || isReadOnlyCell(td)) return;
    if(td.querySelector('.cell-fill-handle')) return;
    const h = document.createElement('div');
    h.className = 'cell-fill-handle';
    h.title = 'Drag to fill';
    h.addEventListener('mousedown', onFillMouseDown);
    td.appendChild(h);
  }

  // ---- Grid geometry ----
  function sameGrid(a,b){
    return a && b && a.closest('tbody') && a.closest('tbody') === b.closest('tbody');
  }
  function cellCoord(td){
    const tr = td.closest('tr');
    const tbody = tr && tr.parentElement;
    if(!tbody) return null;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const r = rows.indexOf(tr);
    const cells = Array.from(tr.querySelectorAll('td[data-field]'));
    const c = cells.indexOf(td);
    return { r, c, rows, tr, tbody };
  }
  function getCellsInRange(a,b){
    if(!sameGrid(a,b)) return [a].filter(Boolean);
    const ca = cellCoord(a), cb = cellCoord(b);
    if(!ca || !cb) return [a];
    const r1 = Math.min(ca.r, cb.r), r2 = Math.max(ca.r, cb.r);
    const c1 = Math.min(ca.c, cb.c), c2 = Math.max(ca.c, cb.c);
    const out = [];
    for(let r=r1; r<=r2; r++){
      const cells = Array.from(ca.rows[r].querySelectorAll('td[data-field]'));
      for(let c=c1; c<=c2; c++){
        if(cells[c]) out.push(cells[c]);
      }
    }
    return out;
  }
  function currentRangeCells(){
    if(!rangeAnchor || !rangeFoot) return activeCell ? [activeCell] : [];
    return getCellsInRange(rangeAnchor, rangeFoot);
  }

  // ---- Navigation ----
  function move(dir){
    if(!activeCell) return;
    const co = cellCoord(activeCell);
    if(!co) return;
    const { rows, r, c } = co;
    let nr = r, nc = c;
    if(dir==='up') nr = Math.max(0, r-1);
    else if(dir==='down') nr = Math.min(rows.length-1, r+1);
    else if(dir==='left') nc = Math.max(0, c-1);
    else if(dir==='right'){
      const cells = Array.from(rows[r].querySelectorAll('td[data-field]'));
      nc = Math.min(cells.length-1, c+1);
    }
    const targetRow = rows[nr];
    if(!targetRow) return;
    const targetCells = Array.from(targetRow.querySelectorAll('td[data-field]'));
    const target = targetCells[nc] || targetCells[targetCells.length-1];
    if(target){
      selectSingle(target);
      target.scrollIntoView({ block:'nearest', inline:'nearest' });
    }
  }

  // ---- Serialization (F2) ----
  function serializeCell(td){
    if(!td || !td.dataset.field) return '';
    const field = td.dataset.field;
    const ri = parseInt(td.dataset.ri, 10);
    const cached = getCache(ri);
    let raw = cached ? (cached[field] || '') : (td.innerText || '').trim();
    if(!raw) return '';
    const t = getFieldType(field);
    if(t==='tag' || t==='link' || t==='autocomplete' || t==='field_type'){
      // Multi-value fields stored pipe-separated; serialize as comma list
      // ("Warm | Hot Lead" -> "Warm, Hot Lead") for clean clipboard pastes.
      return String(raw).split(/\s*\|\s*/).filter(Boolean).join(', ');
    }
    return String(raw);
  }
  function csvEscape(v){
    v = (v==null ? '' : String(v));
    return /[",\n\r]/.test(v) ? '"'+v.replace(/"/g,'""')+'"' : v;
  }
  function tsvEscape(v){
    return (v==null ? '' : String(v)).replace(/\t/g,' ').replace(/\r?\n/g,' ');
  }
  function copyCells(cells, format){
    if(!cells || !cells.length) return '';
    const byRow = new Map();
    cells.forEach(td => {
      const tr = td.closest('tr');
      if(!byRow.has(tr)) byRow.set(tr, []);
      byRow.get(tr).push(td);
    });
    const rows = Array.from(byRow.values());
    if(format==='tsv'){
      return rows.map(r => r.map(td => tsvEscape(serializeCell(td))).join('\t')).join('\n');
    }
    if(format==='csv'){
      return rows.map(r => r.map(td => csvEscape(serializeCell(td))).join(',')).join('\n');
    }
    if(format==='json'){
      const list = rows.map(r => {
        const o = {};
        r.forEach(td => { o[normHeader(td.dataset.field) || td.dataset.field] = serializeCell(td); });
        return o;
      });
      return JSON.stringify(list.length===1 ? list[0] : list, null, 2);
    }
    if(cells.length===1) return serializeCell(cells[0]);
    return rows.map(r => r.map(td => tsvEscape(serializeCell(td))).join('\t')).join('\n');
  }
  function doCopy(format){
    const cells = currentRangeCells();
    if(!cells.length) return;
    // Single-cell defaults to plain text; range defaults to TSV.
    const fmt = format || (cells.length>1 ? 'tsv' : 'plain');
    const payload = copyCells(cells, fmt);
    if(!payload){ toastMsg('Nothing to copy','error'); return; }
    navigator.clipboard.writeText(payload).then(()=>{
      cells.forEach(td => {
        td.classList.add('cell-copied');
        setTimeout(()=> td.classList.remove('cell-copied'), 600);
      });
      toastMsg(cells.length>1 ? ('Copied '+cells.length+' cells') : 'Copied');
    }).catch(()=> toastMsg('Clipboard blocked','error'));
  }

  // ---- Row copy (Cmd+Shift+C) ----
  function copyRowAsTSV(tr){
    if(!tr) return;
    const cells = Array.from(tr.querySelectorAll('td[data-field]'));
    const headers = cells.map(td => normHeader(td.dataset.field) || td.dataset.field);
    const vals = cells.map(td => tsvEscape(serializeCell(td)));
    navigator.clipboard.writeText(headers.join('\t')+'\n'+vals.join('\t'))
      .then(()=> toastMsg('Row copied as TSV'));
  }

  // ---- Read only / computed header list (F3) ----
  // Headers whose value is computed by the backend and must silently no-op
  // on paste / delete / drag-fill with a "This cell is computed" toast.
  const READONLY_HEADERS = [
    'combined first names',
    'emails combined',
    'date/time in la to send email',
    'date/time in london to send email',
    'backlinks cache',
    'group leader',
    'grouping override'
  ];
  function isReadOnlyHeader(h){
    const n = normHeader(h);
    if(!n) return true;
    return READONLY_HEADERS.some(ro => n === ro || n === ro+' [use]' || n.startsWith(ro));
  }
  function isReadOnlyCell(td){
    if(!td) return true;
    if(isReadOnlyHeader(td.dataset.field)) return true;
    if(!td.classList.contains('cell-editable')) return true;
    return false;
  }

  // ---- Parsing (F3) ----
  function parseDateLike(raw){
    if(!raw) return null;
    const s = String(raw).trim();
    // ISO yyyy-mm-dd[ T]HH:MM[:SS]
    let m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2})(?::(\d{2}))?)?/);
    if(m){
      return {
        date: m[1]+'-'+m[2]+'-'+m[3],
        time: m[4] ? (m[4]+':'+m[5]+':'+(m[6]||'00')) : null
      };
    }
    // DD/MM/YYYY HH:MM or MM/DD/YYYY HH:MM — DD/MM preferred for UK workflow
    m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
    if(m){
      const day = m[1].padStart(2,'0'), mon = m[2].padStart(2,'0');
      return {
        date: m[3]+'-'+mon+'-'+day,
        time: m[4] ? (m[4].padStart(2,'0')+':'+m[5]+':'+(m[6]||'00')) : null
      };
    }
    return null;
  }
  function parseValueForType(raw, type){
    if(raw==null) return '';
    const s = String(raw).trim();
    if(!s) return '';
    if(type==='number' || type==='currency' || type==='percent' || type==='rating'){
      const cleaned = s.replace(/[^\d\.\-]/g,'');
      const n = parseFloat(cleaned);
      if(isNaN(n)) return { error: 'Not a number: '+s };
      return String(n);
    }
    if(type==='date'){
      const p = parseDateLike(s);
      if(!p) return { error: 'Bad date: '+s };
      return p.date;
    }
    if(type==='datetime'){
      const p = parseDateLike(s);
      if(!p) return { error: 'Bad datetime: '+s };
      return p.date + (p.time ? ' '+p.time : ' 00:00:00');
    }
    if(type==='tag' || type==='link' || type==='autocomplete' || type==='field_type'){
      return s.split(/\s*[,;|]\s*/).filter(Boolean).join(' | ');
    }
    return s;
  }

  function writeCell(td, rawValue){
    return new Promise(resolve => {
      if(!td || !td.dataset.field){ resolve({ ok:false, skipped:true, reason:'no-field' }); return; }
      if(isReadOnlyCell(td)){ resolve({ ok:false, skipped:true, reason:'readonly' }); return; }
      const field = td.dataset.field;
      const ri = parseInt(td.dataset.ri, 10);
      const table = currentTable();
      const type = getFieldType(field);
      const parsed = parseValueForType(rawValue, type);
      if(parsed && typeof parsed === 'object' && parsed.error){
        toastMsg(parsed.error, 'error');
        resolve({ ok:false, skipped:true, reason:'parse', error:parsed.error });
        return;
      }
      if(typeof _gridSave === 'function'){
        _gridSave(td, field, ri, table, parsed);
        resolve({ ok:true, skipped:false });
      } else {
        resolve({ ok:false, skipped:true, reason:'no-save' });
      }
    });
  }

  // ---- Paste (F3) ----
  function parseClipboardGrid(text){
    if(text==null) return [['']];
    const s = String(text);
    if(/[\t\n]/.test(s)){
      const lines = s.replace(/\r\n?/g,'\n').replace(/\n$/,'').split('\n');
      return lines.map(l => l.split('\t'));
    }
    return [[s]];
  }
  async function doPaste(){
    const cells = currentRangeCells();
    if(!cells.length) return;
    let text = '';
    try{ text = await navigator.clipboard.readText(); }
    catch(e){ toastMsg('Clipboard blocked','error'); return; }
    if(text==null) return;
    const grid = parseClipboardGrid(text);
    const rowsN = grid.length, colsN = grid[0] ? grid[0].length : 0;

    // Single-cell clipboard into a range: drag-fill semantics (literal copy).
    if(rowsN===1 && colsN===1){
      if(cells.length===1){
        if(isReadOnlyCell(cells[0])){ toastMsg('This cell is computed'); return; }
        const res = await writeCell(cells[0], grid[0][0]);
        if(res.ok) toastMsg('Saved');
        return;
      }
      await fillRangeWithValue(cells, grid[0][0]);
      return;
    }
    // Multi-cell TSV: paste starting at the rangeAnchor (top-left of selection).
    const anchor = rangeAnchor || activeCell;
    if(!anchor) return;
    const ac = cellCoord(anchor);
    if(!ac) return;
    const undoBucket = [];
    let written = 0, skipped = 0;
    for(let r=0; r<rowsN; r++){
      const tr = ac.rows[ac.r + r];
      if(!tr) break;
      const targetCells = Array.from(tr.querySelectorAll('td[data-field]'));
      for(let c=0; c<colsN; c++){
        const td = targetCells[ac.c + c];
        if(!td) continue;
        const field = td.dataset.field, ri = parseInt(td.dataset.ri,10);
        const cached = getCache(ri);
        const prev = cached ? (cached[field]||'') : '';
        const res = await writeCell(td, grid[r][c]);
        if(res.ok){ undoBucket.push({ td, field, ri, prev, next:grid[r][c], table:currentTable() }); written++; }
        else skipped++;
      }
    }
    if(undoBucket.length){ lastUndo = { cells: undoBucket }; }
    toastMsg('Pasted '+written+' cell'+(written===1?'':'s')+(skipped ? ' (skipped '+skipped+')' : ''));
  }

  // ---- Drag fill (F4) ----
  function serializeSourceValue(td){
    // Use the cache RAW value (pipe-separated) so the fill writes back
    // bytes the storage layer already understands. Skips the comma reformat
    // that serializeCell uses for clipboard pastes.
    if(!td) return '';
    const ri = parseInt(td.dataset.ri, 10);
    const cached = getCache(ri);
    return cached ? (cached[td.dataset.field] || '') : (td.innerText || '').trim();
  }
  function onFillMouseDown(e){
    e.preventDefault();
    e.stopPropagation();
    if(!activeCell) return;
    // Source = current selection (single cell or multi-cell range pattern).
    fillSourceCells = currentRangeCells();
    fillSource = activeCell;
    dragFilling = true;
    document.body.classList.add('cell-fill-dragging');
    document.addEventListener('mousemove', onFillMouseMove);
    document.addEventListener('mouseup', onFillMouseUp, { once:true });
  }
  function onFillMouseMove(e){
    if(!dragFilling || !activeCell) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const target = el && el.closest && el.closest('td[data-field]');
    if(!target || !sameGrid(target, activeCell)) return;
    const src = (fillSourceCells && fillSourceCells.length) ? fillSourceCells : [activeCell];
    const srcFirst = src[0], srcLast = src[src.length-1];
    const p1 = cellCoord(srcFirst), p2 = cellCoord(srcLast), pt = cellCoord(target);
    if(!p1 || !p2 || !pt) return;
    const r1 = Math.min(p1.r, p2.r, pt.r), r2 = Math.max(p1.r, p2.r, pt.r);
    const c1 = Math.min(p1.c, p2.c, pt.c), c2 = Math.max(p1.c, p2.c, pt.c);
    const rows = p1.rows;
    document.querySelectorAll('td.cell-fill-ghost').forEach(c => c.classList.remove('cell-fill-ghost'));
    for(let r=r1; r<=r2; r++){
      const cells = Array.from(rows[r].querySelectorAll('td[data-field]'));
      for(let c=c1; c<=c2; c++){
        if(cells[c]) cells[c].classList.add('cell-fill-ghost');
      }
    }
  }
  async function onFillMouseUp(){
    document.removeEventListener('mousemove', onFillMouseMove);
    document.body.classList.remove('cell-fill-dragging');
    if(!dragFilling) return;
    dragFilling = false;
    const ghostCells = Array.from(document.querySelectorAll('td.cell-fill-ghost'));
    ghostCells.forEach(c => c.classList.remove('cell-fill-ghost'));
    if(!ghostCells.length) return;
    const source = (fillSourceCells && fillSourceCells.length) ? fillSourceCells : [activeCell];
    if(source.length === 1){
      await fillRangeWithValue(ghostCells, serializeSourceValue(source[0]));
    } else {
      // Tile the multi-cell source pattern across the ghost range (F5).
      await fillRangeWithPattern(ghostCells, source);
    }
  }
  async function fillRangeWithValue(cells, value){
    const undoBucket = [];
    let written = 0, skipped = 0;
    for(const td of cells){
      if(isReadOnlyCell(td)){ skipped++; continue; }
      const field = td.dataset.field;
      const ri = parseInt(td.dataset.ri, 10);
      const table = currentTable();
      const cached = getCache(ri);
      const prev = cached ? (cached[field] || '') : '';
      // Literal copy: source value is already canonical, no parse step.
      if(typeof _gridSave === 'function'){
        _gridSave(td, field, ri, table, value);
        undoBucket.push({ td, field, ri, prev, next:value, table });
        written++;
      }
    }
    if(undoBucket.length){ lastUndo = { cells: undoBucket }; showUndoToast(undoBucket.length); }
    toastMsg('Filled '+written+' cell'+(written===1?'':'s')+(skipped ? ' (skipped '+skipped+' read only)' : ''));
  }

  // ---- Undo toast (F4) ----
  function showUndoToast(n){
    const el = document.createElement('div');
    el.className = 'toast success cell-undo-toast';
    el.innerHTML = 'Filled '+n+' cell'+(n===1?'':'s')+'. <button class="cell-undo-btn">Undo</button>';
    const container = document.getElementById('toast-container');
    if(!container) return;
    container.appendChild(el);
    const btn = el.querySelector('.cell-undo-btn');
    btn.addEventListener('click', () => { doUndo(); el.remove(); });
    setTimeout(() => el.remove(), 10000);
  }
  function doUndo(){
    if(!lastUndo || !lastUndo.cells || !lastUndo.cells.length){
      toastMsg('Nothing to undo');
      return;
    }
    const batch = lastUndo.cells;
    lastUndo = null;
    batch.forEach(entry => {
      if(typeof _gridSave === 'function'){
        _gridSave(entry.td, entry.field, entry.ri, entry.table, entry.prev);
      }
    });
    toastMsg('Undid '+batch.length+' cell'+(batch.length===1?'':'s'));
  }

  // ---- Multi-cell range fill (F5): drag-fill from a multi-cell source pattern ----
  async function fillRangeWithPattern(cells, source){
    if(!cells.length || !source.length) return;
    const ac = cellCoord(cells[0]);
    const sc0 = cellCoord(source[0]);
    if(!ac || !sc0) return;
    const srcRows = Math.max.apply(null, source.map(s => cellCoord(s).r)) - sc0.r + 1;
    const srcCols = Math.max.apply(null, source.map(s => cellCoord(s).c)) - sc0.c + 1;
    const srcMap = new Map();
    source.forEach(s => {
      const p = cellCoord(s);
      srcMap.set((p.r - sc0.r)+':'+(p.c - sc0.c), serializeSourceValue(s));
    });
    const undoBucket = [];
    let written = 0, skipped = 0;
    for(const td of cells){
      const p = cellCoord(td);
      const dr = (p.r - ac.r) % srcRows;
      const dc = (p.c - ac.c) % srcCols;
      const value = srcMap.get(dr+':'+dc);
      if(value==null) continue;
      if(isReadOnlyCell(td)){ skipped++; continue; }
      const field = td.dataset.field;
      const ri = parseInt(td.dataset.ri, 10);
      const table = currentTable();
      const cached = getCache(ri);
      const prev = cached ? (cached[field]||'') : '';
      _gridSave(td, field, ri, table, value);
      undoBucket.push({ td, field, ri, prev, next:value, table });
      written++;
    }
    if(undoBucket.length){ lastUndo = { cells: undoBucket }; showUndoToast(undoBucket.length); }
    toastMsg('Filled '+written+' cells'+(skipped ? ' (skipped '+skipped+' read only)' : ''));
  }

  // ---- Delete / clear (F5) ----
  async function clearRange(cells){
    if(!cells || !cells.length) return;
    const undoBucket = [];
    let written = 0, skipped = 0;
    for(const td of cells){
      if(isReadOnlyCell(td)){ skipped++; continue; }
      const field = td.dataset.field, ri = parseInt(td.dataset.ri,10);
      const cached = getCache(ri);
      const prev = cached ? (cached[field]||'') : '';
      const res = await writeCell(td, '');
      if(res.ok){ undoBucket.push({ td, field, ri, prev, next:'', table:currentTable() }); written++; }
      else skipped++;
    }
    if(undoBucket.length){ lastUndo = { cells: undoBucket }; }
    toastMsg('Cleared '+written+' cell'+(written===1?'':'s')+(skipped ? ' (skipped '+skipped+')' : ''));
  }

  function selectAllInGrid(anchor){
    const tbody = anchor.closest('tbody');
    if(!tbody) return;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    if(!rows.length) return;
    const first = rows[0].querySelector('td[data-field]');
    const lastRow = rows[rows.length-1];
    const lastCells = Array.from(lastRow.querySelectorAll('td[data-field]'));
    const last = lastCells[lastCells.length-1];
    if(first && last) selectRange(first, last);
  }

  function openEditor(td){
    if(!td || isReadOnlyCell(td)) return;
    const field = td.dataset.field;
    const ri = parseInt(td.dataset.ri, 10);
    const table = currentTable();
    if(typeof gridEdit === 'function') gridEdit(td, field, ri, table);
  }

  // ---- Mouse: cell click + range drag (F5) ----
  function onMouseDown(e){
    if(e.button !== 0) return;
    const td = e.target.closest('td[data-field]');
    if(!td) return;
    if(isInsideEditor(e.target)) return;
    if(e.target.closest('.pill-x')) return;
    if(e.target.closest('.row-check, .expand-col, .expand-icon, a[href]')) return;
    // Don't initiate range drag when clicking on the fill handle  that handler runs first
    if(e.target.closest('.cell-fill-handle')) return;

    const clickedOnPillLink = !!e.target.closest('.pill-link');

    // Shift+click extends the range from the existing anchor.
    if(e.shiftKey && activeCell && sameGrid(activeCell, td)){
      e.preventDefault();
      selectRange(rangeAnchor || activeCell, td);
      return;
    }
    selectSingle(td);
    // Clicking on a pill-link should still navigate; don't start a drag.
    if(clickedOnPillLink) return;
    // Begin a potential rectangular range drag. mousemove paints the range
    // until mouseup ends it.
    dragging = true;
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp, { once:true });
  }
  function onMouseMove(e){
    if(!dragging || !activeCell) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const td = el && el.closest && el.closest('td[data-field]');
    if(!td || !sameGrid(td, activeCell)) return;
    if(td !== rangeFoot){
      selectRange(rangeAnchor || activeCell, td);
    }
  }
  function onMouseUp(){
    dragging = false;
    document.removeEventListener('mousemove', onMouseMove);
  }

  // Single click handler: same-cell second click on an editable cell opens the editor.
  let lastClickCell = null, lastClickTs = 0;
  function onClick(e){
    const td = e.target.closest('td[data-field]');
    if(!td) return;
    if(isInsideEditor(e.target)) return;
    if(e.target.closest('.pill-x, .pill-link, a[href], .row-check, .expand-col, .expand-icon')) return;
    const now = Date.now();
    if(lastClickCell === td && now - lastClickTs < 600 && td.classList.contains('cell-editable')){
      openEditor(td);
    }
    lastClickCell = td; lastClickTs = now;
  }

  // ---- Keyboard ----
  function onKeyDown(e){
    const tag = document.activeElement && document.activeElement.tagName;
    if(tag==='INPUT' || tag==='TEXTAREA' || tag==='SELECT') return;
    if(document.getElementById('prompt-modal') || document.getElementById('field-type-picker')) return;

    // Cmd+A = select every cell in the active grid (F5).
    if((e.metaKey || e.ctrlKey) && e.key==='a' && activeCell){
      e.preventDefault();
      selectAllInGrid(activeCell);
      return;
    }
    // Cmd+Z = undo last drag-fill / paste / clear batch (works without an active cell).
    if((e.metaKey || e.ctrlKey) && e.key==='z' && !e.shiftKey){
      if(lastUndo){ e.preventDefault(); doUndo(); return; }
    }

    if(!activeCell) return;

    if(e.key==='ArrowRight'){ e.preventDefault(); move('right'); }
    else if(e.key==='ArrowLeft'){ e.preventDefault(); move('left'); }
    else if(e.key==='ArrowDown'){ e.preventDefault(); move('down'); }
    else if(e.key==='ArrowUp'){ e.preventDefault(); move('up'); }
    else if(e.key==='Tab'){ e.preventDefault(); move(e.shiftKey ? 'left' : 'right'); }
    else if(e.key==='Enter'){
      e.preventDefault();
      if(e.shiftKey){ move('up'); }
      else if(activeCell.classList.contains('cell-editable')){
        openEditor(activeCell);
      } else {
        move('down');
      }
    }
    else if(e.key==='Escape'){ e.preventDefault(); deselect(); }
    else if((e.metaKey || e.ctrlKey) && (e.key==='c' || e.key==='C')){
      e.preventDefault();
      if(e.shiftKey){
        // Cmd+Shift+C — copy entire row as TSV (headers + values)
        copyRowAsTSV(activeCell.closest('tr'));
      } else {
        doCopy();
      }
    }
    else if((e.metaKey || e.ctrlKey) && (e.key==='v' || e.key==='V')){
      e.preventDefault();
      doPaste();
    }
    else if(e.key==='Delete' || e.key==='Backspace'){
      // F5: clear every cell in the current selection (skips read-only).
      e.preventDefault();
      clearRange(currentRangeCells());
    }
    else if(e.key.length===1 && !e.metaKey && !e.ctrlKey && !e.altKey){
      // Type-to-edit: any printable character starts editing the current cell.
      if(activeCell.classList.contains('cell-editable')){
        openEditor(activeCell);
        setTimeout(()=>{
          const inp = activeCell && activeCell.querySelector('.inline-edit');
          if(inp){ inp.value = e.key; try{ inp.setSelectionRange(1,1); }catch(_){} }
        }, 60);
      }
    }
  }

  // ---- Right-click context menu (F5) ----
  function onContextMenu(e){
    const td = e.target.closest('td[data-field]');
    if(!td) return;
    if(e.target.closest('.pill-x, a[href]')) return;
    if(!currentRangeCells().includes(td)) selectSingle(td);
    e.preventDefault();
    showContextMenu(e.clientX, e.clientY, td);
  }
  function showContextMenu(x, y, td){
    const old = document.getElementById('cell-ctx-menu');
    if(old) old.remove();
    const tr = td.closest('tr');
    const rangeMulti = currentRangeCells().length > 1;
    const m = document.createElement('div');
    m.id = 'cell-ctx-menu';
    m.className = 'cell-ctx-menu';
    m.style.cssText = 'position:fixed;left:'+x+'px;top:'+y+'px;z-index:4000;';
    const items = [
      { act:'copy',        label: rangeMulti ? 'Copy (TSV)' : 'Copy' },
      { act:'copy-tsv',    label:'Copy as TSV' },
      { act:'copy-csv',    label:'Copy as CSV' },
      { act:'copy-json',   label:'Copy as JSON' },
      { act:'sep' },
      { act:'paste',       label:'Paste' },
      { act:'fill-down',   label:'Fill down from here' },
      { act:'clear',       label:'Clear cell' },
      { act:'sep' },
      { act:'row-tsv',     label:'Copy row as TSV' },
      { act:'row-csv',     label:'Copy row as CSV' },
      { act:'row-json',    label:'Copy row as JSON' }
    ];
    m.innerHTML = items.map(it => it.act==='sep'
      ? '<div class="cell-ctx-sep"></div>'
      : '<div class="cell-ctx-item" data-act="'+it.act+'">'+it.label+'</div>'
    ).join('');
    document.body.appendChild(m);
    m.querySelectorAll('.cell-ctx-item').forEach(it => {
      it.addEventListener('click', () => { runCtxAction(it.dataset.act, td, tr); m.remove(); });
    });
  }
  function runCtxAction(act, td, tr){
    switch(act){
      case 'copy':       doCopy(); break;
      case 'copy-tsv':   doCopy('tsv'); break;
      case 'copy-csv':   doCopy('csv'); break;
      case 'copy-json':  doCopy('json'); break;
      case 'paste':      doPaste(); break;
      case 'fill-down':  fillDownFrom(td); break;
      case 'clear':      clearRange([td]); break;
      case 'row-tsv':    copyRowAsTSV(tr); break;
      case 'row-csv':    copyRowAsCSV(tr); break;
      case 'row-json':   copyRowAsJSON(tr); break;
    }
  }
  function fillDownFrom(td){
    const co = cellCoord(td);
    if(!co) return;
    const srcVal = serializeSourceValue(td);
    const targets = [];
    for(let r=co.r+1; r<co.rows.length; r++){
      const cells = Array.from(co.rows[r].querySelectorAll('td[data-field]'));
      if(cells[co.c]) targets.push(cells[co.c]);
    }
    if(!targets.length){ toastMsg('Nothing below to fill'); return; }
    fillRangeWithValue(targets, srcVal);
  }
  function copyRowAsCSV(tr){
    if(!tr) return;
    const cells = Array.from(tr.querySelectorAll('td[data-field]'));
    const headers = cells.map(td => normHeader(td.dataset.field) || td.dataset.field);
    const vals = cells.map(td => csvEscape(serializeCell(td)));
    navigator.clipboard.writeText(headers.map(csvEscape).join(',')+'\n'+vals.join(','))
      .then(() => toastMsg('Row copied as CSV'));
  }
  function copyRowAsJSON(tr){
    if(!tr) return;
    const cells = Array.from(tr.querySelectorAll('td[data-field]'));
    const obj = {};
    cells.forEach(td => { obj[normHeader(td.dataset.field) || td.dataset.field] = serializeCell(td); });
    navigator.clipboard.writeText(JSON.stringify(obj, null, 2))
      .then(() => toastMsg('Row copied as JSON'));
  }

  // ---- Global handlers ----
  document.addEventListener('mousedown', onMouseDown);
  document.addEventListener('click', onClick);
  document.addEventListener('keydown', onKeyDown);
  document.addEventListener('contextmenu', onContextMenu);
  document.addEventListener('scroll', () => {
    const m = document.getElementById('cell-ctx-menu');
    if(m) m.remove();
  }, true);
  document.addEventListener('click', e => {
    const m = document.getElementById('cell-ctx-menu');
    if(m && !m.contains(e.target)) m.remove();
  });
  // Deselect when clicking outside any grid (but not inside modals/menus).
  document.addEventListener('mousedown', e => {
    if(!activeCell) return;
    if(e.target.closest('.data-grid')) return;
    if(e.target.closest('.col-menu, .prompt-overlay, #cell-ctx-menu, .cell-undo-toast, .modal, .tag-editor, .typeahead-wrap, .toast')) return;
    deselect();
  });

  // ---- Compat shims used by existing core.js inline edit flow ----
  // gridEdit's blur handler at core.js:1859 calls cellSelect(td) to re-highlight after save.
  window.cellSelect = function(td){ if(td) selectSingle(td); };
  window.cellDeselect = function(){ deselect(); };
  window.cellMove = function(dir){ move(dir); };

  // ---- Public debug hook ----
  window._cellMechanics = {
    state: () => ({ activeCell }),
    selectSingle, deselect, move,
    range: () => currentRangeCells(),
    copy: doCopy,
    copyRow: copyRowAsTSV,
    paste: doPaste,
    parse: parseValueForType,
    fill: fillRangeWithValue,
    fillPattern: fillRangeWithPattern,
    clear: clearRange,
    selectAll: selectAllInGrid,
    selectRange,
    undo: doUndo
  };
})();
