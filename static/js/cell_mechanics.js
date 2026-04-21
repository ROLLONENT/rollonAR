/* ==========================================================================
   ROLLON AR cell_mechanics.js  (v37.7 spreadsheet grid interactions)
   ==========================================================================
   F1 single cell selection + arrow/tab/enter/escape nav
   F2 Cmd+C / Cmd+Shift+C type aware serialization
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

  // ---- Editor open ----
  function isReadOnlyCell(td){
    if(!td) return true;
    if(!td.classList.contains('cell-editable')) return true;
    return false;
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
    copyRow: copyRowAsTSV
  };
})();
