/* ROLLON AR — Type-Aware Filter System
   Matches Airtable operator sets per field type */

const FILTER_OPS = {
  text: [
    {value:'contains',label:'contains'},
    {value:'does_not_contain',label:'does not contain'},
    {value:'is',label:'is'},
    {value:'is_not',label:'is not'},
    {value:'starts_with',label:'starts with'},
    {value:'ends_with',label:'ends with'},
    {value:'is_empty',label:'is empty'},
    {value:'is_not_empty',label:'is not empty'}
  ],
  tag: [
    {value:'contains_any',label:'has any of'},
    {value:'contains_all',label:'has all of'},
    {value:'is',label:'is exactly'},
    {value:'does_not_contain',label:'has none of'},
    {value:'contains',label:'contains'},
    {value:'is_empty',label:'is empty'},
    {value:'is_not_empty',label:'is not empty'}
  ],
  link: [
    {value:'contains_any',label:'has any of'},
    {value:'contains_all',label:'has all of'},
    {value:'is',label:'is exactly'},
    {value:'does_not_contain',label:'has none of'},
    {value:'contains',label:'contains'},
    {value:'does_not_contain',label:'does not contain'},
    {value:'is_empty',label:'is empty'},
    {value:'is_not_empty',label:'is not empty'}
  ],
  autocomplete: [
    {value:'contains_any',label:'has any of'},
    {value:'is',label:'is exactly'},
    {value:'does_not_contain',label:'has none of'},
    {value:'contains',label:'contains'},
    {value:'does_not_contain',label:'does not contain'},
    {value:'is_empty',label:'is empty'},
    {value:'is_not_empty',label:'is not empty'}
  ],
  date: [
    {value:'is',label:'is'},
    {value:'is_before',label:'is before'},
    {value:'is_after',label:'is after'},
    {value:'is_on_or_before',label:'is on or before'},
    {value:'is_on_or_after',label:'is on or after'},
    {value:'is_empty',label:'is empty'},
    {value:'is_not_empty',label:'is not empty'}
  ],
  number: [
    {value:'is',label:'='},
    {value:'is_not',label:'≠'},
    {value:'is_before',label:'<'},
    {value:'is_after',label:'>'},
    {value:'is_empty',label:'is empty'},
    {value:'is_not_empty',label:'is not empty'}
  ]
};

function getOpsForField(header){
  const type=fieldType(header);
  if(type==='date')return FILTER_OPS.date;
  if(type==='tag'||type==='field_type')return FILTER_OPS.tag;
  if(type==='link')return FILTER_OPS.link;
  if(type==='autocomplete')return FILTER_OPS.autocomplete;
  return FILTER_OPS.text;
}

function getSortLabels(header){
  const type=fieldType(header);
  if(type==='date')return ['Earliest → Latest','Latest → Earliest'];
  if(type==='tag'||type==='link')return ['A → Z','Z → A'];
  return ['First → Last','Last → First'];
}

// Filter panel - does NOT rebuild on value typing (fixes one-character-at-a-time bug)
function buildFilterPanelV2(containerId,columns,headers,filters,onChange){
  const el=document.getElementById(containerId);if(!el)return;
  const mode=window._filterMode||'and';
  const andCls=mode==='and'?'btn-accent':'';
  const orCls=mode==='or'?'btn-accent':'';
  let html=`<div class="filter-header" style="display:flex;justify-content:space-between;align-items:center"><span style="font-size:11px;color:var(--text-secondary);font-weight:600">In this view, show records</span><div style="display:flex;gap:4px;align-items:center"><button class="btn btn-sm ${andCls}" onclick="window._filterMode='and';window._fmChange()" style="font-size:10px;padding:2px 8px">AND</button><button class="btn btn-sm ${orCls}" onclick="window._filterMode='or';window._fmChange()" style="font-size:10px;padding:2px 8px">OR</button></div><span class="filter-remove" onclick="document.getElementById('filter-panel').classList.remove('open')" style="cursor:pointer;font-size:16px">✕</span></div>`;
  filters.forEach((f,i)=>{
    html+='<div class="filter-row">';
    html+=`<span class="filter-conjunction">${i===0?'WHERE':(mode==='or'?'OR':'AND')}</span>`;
    // Searchable field selector
    html+=`<div class="filter-field-wrap" style="position:relative;flex:1;max-width:180px">`;
    html+=`<input class="filter-field-search" data-fidx="${i}" value="${esc(f.col||'')}" placeholder="Search field..." onclick="showFilterFieldDD(this,${i})" oninput="filterFilterFieldDD(this,${i})">`;
    html+=`<div class="filter-field-dd" id="ffd-${i}" style="display:none;position:absolute;top:100%;left:0;right:0;max-height:250px;overflow-y:auto;background:var(--bg-raised);border:1px solid var(--border-strong);border-radius:var(--r-md);z-index:50">`;
    columns.forEach(c=>{html+=`<div class="typeahead-item" data-col="${escA(c)}" onclick="pickFilterField(${i},'${escA(c)}')">${esc(c)}</div>`});
    html+=`</div></div>`;
    const rawH=headers.find(h=>cleanH(h)===f.col)||f.col;
    const ops=f.col?getOpsForField(rawH):FILTER_OPS.text;
    html+=`<select class="filter-op" onchange="window._fu2(${i},'op',this.value)">`;
    ops.forEach(o=>{html+=`<option value="${o.value}" ${f.op===o.value?'selected':''}>${o.label}</option>`});
    html+=`</select>`;
    const needsVal=!['is_empty','is_not_empty'].includes(f.op);
    const type=f.col?fieldType(rawH):'text';
    if(needsVal){
      if(type==='date'){
        html+=`<input type="date" class="filter-val" value="${f.val||''}" onchange="window._fv(${i},this.value)">`;
      } else if(type==='link'){
        // Linked field: show selected values as pills + searchable typeahead
        const selectedVals=(f.val||'').split(',').map(v=>v.trim()).filter(Boolean);
        html+=`<div class="filter-link-wrap" style="position:relative;flex:1">`;
        html+=`<div class="filter-link-pills" id="flp-${i}" style="display:flex;flex-wrap:wrap;gap:3px;align-items:center;min-height:28px;padding:2px 4px;background:var(--bg);border:1px solid var(--border);border-radius:var(--r-md)">`;
        selectedVals.forEach(v=>{
          html+=`<span class="pill pill-link" style="font-size:10px;padding:1px 6px;cursor:pointer" onclick="navToRecord('${escA(v)}')">${esc(v)} <span class="pill-x" onclick="event.stopPropagation();removeFilterVal(${i},'${escA(v)}')">&times;</span></span>`;
        });
        html+=`<input class="filter-link-input" data-fidx="${i}" placeholder="Search..." style="border:none;background:none;color:var(--text);font-size:11px;min-width:60px;flex:1;outline:none" oninput="searchFilterLink(this,${i},'${escA(f.col)}')">`;
        html+=`</div>`;
        html+=`<div class="filter-link-dd" id="fld-${i}" style="display:none;position:absolute;top:100%;left:0;right:0;max-height:200px;overflow-y:auto;background:var(--bg-raised);border:1px solid var(--border-strong);border-radius:var(--r-md);z-index:50"></div>`;
        html+=`</div>`;
      } else if(type==='tag'||type==='field_type'||type==='autocomplete'){
        const selectedVals=(f.val||'').split(',').map(v=>v.trim()).filter(Boolean);
        html+=`<div class="filter-pill-select" id="fps-${i}">`;
        html+=`<button class="btn btn-sm filter-pill-btn" onclick="toggleFilterPillDropdown(${i},'${escA(f.col)}',window._currentTable||'directory')">${selectedVals.length?selectedVals.map(v=>'<span class="pill" style="font-size:10px;padding:1px 6px">'+esc(v)+'</span>').join(' '):'Select ▾'}</button>`;
        html+=`<div class="filter-pill-dropdown" id="fpd-${i}" style="display:none"></div>`;
        html+=`</div>`;
      } else {
        html+=`<input class="filter-val" data-fidx="${i}" value="${esc(f.val||'').replace(/"/g,'&quot;')}" placeholder="Enter a value...">`;
      }
    }
    html+=`<span class="filter-remove" onclick="window._fr2(${i})">🗑</span>`;
    html+=`</div>`;
  });
  html+=`<div class="filter-actions"><button class="btn btn-sm" onclick="window._fa2()">+ Add condition</button></div>`;
  el.innerHTML=html;

  // Store references for helper functions
  window._currentFilters=filters;
  window._filterOnChange=onChange;
  window._filterRebuild=()=>buildFilterPanelV2(containerId,columns,headers,filters,onChange);

  // Attach debounced input handlers to text filter inputs (NO panel rebuild)
  let _fvDeb;
  el.querySelectorAll('input.filter-val[data-fidx]').forEach(inp=>{
    const idx=parseInt(inp.dataset.fidx);
    inp.addEventListener('input',()=>{
      filters[idx].val=inp.value;
      clearTimeout(_fvDeb);
      _fvDeb=setTimeout(()=>onChange(filters),400);
    });
    inp.addEventListener('keydown',e=>{
      if(e.key==='Enter'){clearTimeout(_fvDeb);onChange(filters)}
    });
  });

  // Value change for date/pill (these DO rebuild)
  window._fv=(idx,val)=>{filters[idx].val=val;onChange(filters)};

  // Field/operator change (rebuilds panel to update operators)
  window._fu2=(idx,key,val)=>{
    filters[idx][key]=val;
    if(key==='col'){
      const rawH2=headers.find(h=>cleanH(h)===val)||val;
      const ops2=getOpsForField(rawH2);
      filters[idx].op=ops2[0].value;
      filters[idx].val='';
    }
    onChange(filters);
    buildFilterPanelV2(containerId,columns,headers,filters,onChange);
  };
  window._fr2=idx=>{filters.splice(idx,1);onChange(filters);buildFilterPanelV2(containerId,columns,headers,filters,onChange)};
  window._fa2=()=>{filters.push({col:'',op:'contains',val:''});buildFilterPanelV2(containerId,columns,headers,filters,onChange)};
  window._fmChange=()=>{onChange(filters);buildFilterPanelV2(containerId,columns,headers,filters,onChange)};
}

// Enhanced sort panel matching Airtable
function buildSortPanelV2(containerId,columns,headers,sorts,onChange){
  const el=document.getElementById(containerId);if(!el)return;
  let html='<div class="sort-header" style="display:flex;justify-content:space-between;align-items:center"><span style="font-size:11px;color:var(--text-secondary);font-weight:600">Sort by</span><span class="filter-remove" onclick="document.getElementById(\'sort-panel\').classList.remove(\'open\')" style="cursor:pointer;font-size:16px">✕</span></div>';
  sorts.forEach((s,i)=>{
    const rawH=headers.find(h=>cleanH(h)===s.col)||s.col;
    const labels=s.col?getSortLabels(rawH):['First → Last','Last → First'];
    html+=`<div class="filter-row">`;
    html+=`<div class="searchable-select" style="position:relative;flex:1">`;
    html+=`<input class="prompt-input" style="font-size:12px;padding:6px 8px" value="${esc(s.col||'').replace(/"/g,'&quot;')}" placeholder="Search field..." onfocus="showSortFieldDD(this,${i})" oninput="filterSortFieldDD(this,${i})">`;
    html+=`<div class="sort-field-dd" id="sdd-${i}" style="display:none;position:absolute;top:100%;left:0;right:0;max-height:200px;overflow-y:auto;background:var(--bg-raised);border:1px solid var(--border-strong);border-radius:var(--r-md);z-index:50">`;
    columns.forEach(c=>{html+=`<div class="typeahead-item" data-col="${esc(c).replace(/"/g,'&quot;')}" onclick="pickSortField(${i},'${escA(c)}')">${esc(c)}</div>`});
    html+=`</div></div>`;
    html+=`<select onchange="window._su(${i},'dir',this.value)" style="flex:0 0 auto;width:140px">`;
    html+=`<option value="asc" ${s.dir==='asc'?'selected':''}>${labels[0]}</option>`;
    html+=`<option value="desc" ${s.dir==='desc'?'selected':''}>${labels[1]}</option>`;
    html+=`</select>`;
    html+=`<span class="filter-remove" onclick="window._sr(${i})">✕</span>`;
    html+=`</div>`;
  });
  html+=`<div class="filter-actions"><button class="btn btn-sm" onclick="window._sa()">+ Add another sort</button></div>`;
  el.innerHTML=html;
  window._su=(idx,key,val)=>{sorts[idx][key]=val;onChange(sorts);buildSortPanelV2(containerId,columns,headers,sorts,onChange)};
  window._sr=idx=>{sorts.splice(idx,1);onChange(sorts);buildSortPanelV2(containerId,columns,headers,sorts,onChange)};
  window._sa=()=>{sorts.push({col:'',dir:'asc'});buildSortPanelV2(containerId,columns,headers,sorts,onChange)};
}
function showSortFieldDD(inp,idx){const dd=document.getElementById('sdd-'+idx);if(dd){dd.style.display='block';inp.select();
  setTimeout(()=>{const h=e=>{if(!dd.contains(e.target)&&e.target!==inp){dd.style.display='none';document.removeEventListener('click',h)}};document.addEventListener('click',h)},50)}}
function filterSortFieldDD(inp,idx){const dd=document.getElementById('sdd-'+idx);if(!dd)return;const q=inp.value.toLowerCase();
  dd.querySelectorAll('.typeahead-item').forEach(el=>{el.style.display=el.dataset.col.toLowerCase().includes(q)?'':'none'})}
function pickSortField(idx,col){document.getElementById('sdd-'+idx).style.display='none';window._su(idx,'col',col)}

// ==================== PILL SELECTOR DROPDOWN FOR FILTERS ====================
function toggleFilterPillDropdown(filterIdx,colName,table){
  const dd=document.getElementById('fpd-'+filterIdx);
  if(!dd)return;
  if(dd.style.display==='block'){dd.style.display='none';return}
  // Fetch available values for this column
  const ep=table==='songs'?'/api/songs/tags':'/api/directory/tags';
  fetch(ep).then(r=>r.json()).then(data=>{
    // Get values based on column name
    let options=[];
    const cn=colName.toLowerCase();
    if(cn==='tags'||cn==='tag')options=data.tags||[];
    else if(cn==='field')options=['Creative','MGMT','Record A&R','Publishing A&R','Agent','Artist','Music Supervisor','Publicist','Sync'];
    else if(cn==='audio status')options=data.statuses||[];
    else if(cn==='project')options=data.projects||[];
    else {
      // Fallback: fetch unique values from autocomplete
      fetch(`/api/autocomplete/${table}/${encodeURIComponent(colName)}?limit=50`).then(r=>r.json()).then(d2=>{
        renderPillDropdown(dd,filterIdx,d2.values||[]);
      });
      return;
    }
    renderPillDropdown(dd,filterIdx,options);
  });
}

function renderPillDropdown(dd,filterIdx,options){
  const page=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);
  const currentFilter=page?.filters?.[filterIdx];
  const selectedVals=(currentFilter?.val||'').split(',').map(v=>v.trim()).filter(Boolean);
  const ac='#d4a853';

  // Sort: selected first, then alphabetical
  const sorted=[...options].sort((a,b)=>{
    const aOn=selectedVals.includes(a)?0:1;
    const bOn=selectedVals.includes(b)?0:1;
    if(aOn!==bOn)return aOn-bOn;
    return a.localeCompare(b);
  });

  let html='<div class="fpd-search"><input class="fpd-input" placeholder="Find an option" oninput="filterPillOptions(this,'+filterIdx+')"></div>';
  html+='<div class="fpd-options">';
  sorted.forEach(opt=>{
    const isOn=selectedVals.includes(opt);
    const color=TAG_COLORS[opt]||ac;
    html+=`<div class="fpd-option ${isOn?'fpd-on':''}" data-val="${esc(opt).replace(/"/g,'&quot;')}" onclick="toggleFilterPill(${filterIdx},this)">`;
    html+=`<span class="fpd-toggle ${isOn?'active':''}"></span>`;
    html+=`<span class="pill pill-tag" style="background:${color}20;color:${color};border:1px solid ${color}40">${esc(opt)}</span>`;
    html+=`</div>`;
  });
  html+='</div>';
  html+=`<div class="fpd-actions"><button class="btn btn-sm" onclick="document.getElementById('fpd-${filterIdx}').style.display='none'">Cancel</button><button class="btn btn-sm btn-accent" onclick="applyFilterPills(${filterIdx})">Apply</button></div>`;
  dd.innerHTML=html;
  dd.style.display='block';
  dd.querySelector('.fpd-input')?.focus();
}

function filterPillOptions(input,filterIdx){
  const q=input.value.toLowerCase();
  const dd=document.getElementById('fpd-'+filterIdx);
  dd.querySelectorAll('.fpd-option').forEach(opt=>{
    const val=opt.dataset.val.toLowerCase();
    opt.style.display=val.includes(q)?'':'none';
  });
}

function toggleFilterPill(filterIdx,optEl){
  optEl.classList.toggle('fpd-on');
  optEl.querySelector('.fpd-toggle')?.classList.toggle('active');
}

function applyFilterPills(filterIdx){
  const dd=document.getElementById('fpd-'+filterIdx);if(!dd)return;
  const selected=[];
  dd.querySelectorAll('.fpd-on').forEach(opt=>{selected.push(opt.dataset.val)});
  window._fu2(filterIdx,'val',selected.join(','));
  dd.style.display='none';
}

// ==================== SEARCHABLE FILTER FIELD SELECTOR ====================
function showFilterFieldDD(inp,idx){
  const dd=document.getElementById('ffd-'+idx);if(!dd)return;
  dd.style.display='block';inp.select();
  setTimeout(()=>{const h=e=>{if(!dd.contains(e.target)&&e.target!==inp){dd.style.display='none';document.removeEventListener('click',h)}};document.addEventListener('click',h)},50);
}
function filterFilterFieldDD(inp,idx){
  const dd=document.getElementById('ffd-'+idx);if(!dd)return;
  const q=inp.value.toLowerCase();
  dd.querySelectorAll('.typeahead-item').forEach(el=>{
    el.style.display=el.dataset.col.toLowerCase().includes(q)?'':'none';
    el.classList.remove('ta-highlight');
  });
  dd.style.display='block';
  const vis=Array.from(dd.querySelectorAll('.typeahead-item')).filter(el=>el.style.display!=='none');
  if(vis.length)vis[0].classList.add('ta-highlight');
}
function pickFilterField(idx,col){
  document.getElementById('ffd-'+idx).style.display='none';
  window._fu2(idx,'col',col);
}

// ==================== LINKED FIELD FILTER TYPEAHEAD ====================
function searchFilterLink(inp,idx,fieldName){
  const q=inp.value.trim();
  const dd=document.getElementById('fld-'+idx);if(!dd)return;
  if(q.length<1){dd.style.display='none';return}
  const table=getLinkTable(fieldName);
  fetch(`/api/search-record?q=${encodeURIComponent(q)}&table=${encodeURIComponent(table)}`).then(r=>r.json()).then(d=>{
    const results=d.results||[];
    let html=results.map(r=>`<div class="typeahead-item" onclick="addFilterVal(${idx},'${escA(r.name)}')">${esc(r.name)}<span style="font-size:9px;color:var(--text-ghost);margin-left:6px">${r.table}</span></div>`).join('');
    if(!results.length)html='<div style="padding:8px;color:var(--text-ghost);font-size:11px">No results</div>';
    dd.innerHTML=html;dd.style.display='block';
  });
}
function addFilterVal(idx,val){
  const filters=window._currentFilters;if(!filters)return;
  const current=(filters[idx].val||'').split(',').map(v=>v.trim()).filter(Boolean);
  if(!current.includes(val))current.push(val);
  filters[idx].val=current.join(',');
  document.getElementById('fld-'+idx).style.display='none';
  const inp=document.querySelector(`.filter-link-input[data-fidx="${idx}"]`);
  if(inp)inp.value='';
  if(window._filterOnChange)window._filterOnChange(filters);
  if(window._filterRebuild)window._filterRebuild();
}
function removeFilterVal(idx,val){
  const filters=window._currentFilters;if(!filters)return;
  const current=(filters[idx].val||'').split(',').map(v=>v.trim()).filter(Boolean);
  filters[idx].val=current.filter(v=>v!==val).join(',');
  if(window._filterOnChange)window._filterOnChange(filters);
  if(window._filterRebuild)window._filterRebuild();
}
