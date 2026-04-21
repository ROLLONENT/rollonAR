/* ==========================================================================
   ROLLON AR cell_mechanics.js  (v37.7 spreadsheet grid interactions)
   ==========================================================================
   F1 single cell selection + arrow/tab/enter/escape nav
   F2 Cmd+C / Cmd+Shift+C type aware serialization
   F3 Cmd+V type aware parsing, computed cell guard
   --------------------------------------------------------------------------
   Replaces the V36.1 cellSelect/_selectedCell block previously in core.js.
   The selection model is global: any <td data-field> in any rendered grid
   gets cell selection through document-level event delegation, so every
   grid page (Directory, Songs, Pitches, Invoices, Calendar) inherits this.
   ========================================================================== */
(function(){
  'use strict';

  // ---- State ----
  let activeCell = null;      // primary cell (TD) — the currently selected cell

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
    document.querySelectorAll('td.cell-selected').forEach(c => c.classList.remove('cell-selected'));
  }
  function selectSingle(td){
    clearClasses();
    if(!td){ activeCell = null; window._selectedCell = null; return; }
    td.classList.add('cell-selected');
    activeCell = td;
    // Keep compat with core.js inline-edit blur path that calls cellSelect(td)
    window._selectedCell = td;
  }
  function deselect(){
    clearClasses();
    activeCell = null;
    window._selectedCell = null;
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
    const cells = activeCell ? [activeCell] : [];
    if(!cells.length) return;
    const fmt = format || 'plain';
    const payload = copyCells(cells, fmt);
    if(!payload){ toastMsg('Nothing to copy','error'); return; }
    navigator.clipboard.writeText(payload).then(()=>{
      cells.forEach(td => {
        td.classList.add('cell-copied');
        setTimeout(()=> td.classList.remove('cell-copied'), 600);
      });
      toastMsg('Copied');
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
    if(!activeCell) return;
    let text = '';
    try{ text = await navigator.clipboard.readText(); }
    catch(e){ toastMsg('Clipboard blocked','error'); return; }
    if(text==null) return;
    const grid = parseClipboardGrid(text);
    const rowsN = grid.length, colsN = grid[0] ? grid[0].length : 0;

    // Single-cell clipboard into single-cell selection: type-aware paste.
    if(rowsN===1 && colsN===1){
      if(isReadOnlyCell(activeCell)){
        toastMsg('This cell is computed');
        return;
      }
      const res = await writeCell(activeCell, grid[0][0]);
      if(res.ok) toastMsg('Saved');
      return;
    }
    // Multi-cell TSV: paste starting at the active cell as the top-left anchor.
    const ac = (function(){
      const tr = activeCell.closest('tr');
      const tbody = tr && tr.parentElement;
      if(!tbody) return null;
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const r = rows.indexOf(tr);
      const cells = Array.from(tr.querySelectorAll('td[data-field]'));
      const c = cells.indexOf(activeCell);
      return { r, c, rows };
    })();
    if(!ac){ return; }
    let written = 0, skipped = 0;
    for(let r=0; r<rowsN; r++){
      const tr = ac.rows[ac.r + r];
      if(!tr) break;
      const targetCells = Array.from(tr.querySelectorAll('td[data-field]'));
      for(let c=0; c<colsN; c++){
        const td = targetCells[ac.c + c];
        if(!td) continue;
        const res = await writeCell(td, grid[r][c]);
        if(res.ok) written++; else skipped++;
      }
    }
    toastMsg('Pasted '+written+' cell'+(written===1?'':'s')+(skipped ? ' (skipped '+skipped+')' : ''));
  }
  function openEditor(td){
    if(!td || isReadOnlyCell(td)) return;
    const field = td.dataset.field;
    const ri = parseInt(td.dataset.ri, 10);
    const table = currentTable();
    if(typeof gridEdit === 'function') gridEdit(td, field, ri, table);
  }

  // ---- Mouse: cell click ----
  function onMouseDown(e){
    if(e.button !== 0) return;
    const td = e.target.closest('td[data-field]');
    if(!td) return;
    if(isInsideEditor(e.target)) return;
    if(e.target.closest('.pill-x')) return;
    if(e.target.closest('.row-check, .expand-col, .expand-icon, a[href]')) return;
    if(e.shiftKey && activeCell && sameGrid(activeCell, td)){
      e.preventDefault();
      selectSingle(td);
      return;
    }
    selectSingle(td);
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

  // ---- Global handlers ----
  document.addEventListener('mousedown', onMouseDown);
  document.addEventListener('click', onClick);
  document.addEventListener('keydown', onKeyDown);
  // Deselect when clicking outside any grid (but not inside modals/menus).
  document.addEventListener('mousedown', e => {
    if(!activeCell) return;
    if(e.target.closest('.data-grid')) return;
    if(e.target.closest('.col-menu, .prompt-overlay, .modal, .tag-editor, .typeahead-wrap, .toast')) return;
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
    copy: doCopy,
    copyRow: copyRowAsTSV,
    paste: doPaste,
    parse: parseValueForType
  };
})();
