/* ROLLON AR v35 — Core JS — Google Sheets master, no Airtable */

let TAG_COLORS={},PILL_COLORED=false;
fetch('/api/config').then(r=>r.json()).then(d=>{TAG_COLORS=d.tag_colors||{}}).catch(()=>{});
try{const stored=localStorage.getItem('pill_colored');if(stored!==null)PILL_COLORED=stored==='true'}catch(e){}

// ---- MULTI-SORT HELPERS (used by invoices and other pages with sortFields array) ----
function sortFieldsToURL(fields){
  if(!fields||!fields.length)return '';
  return fields.map((s,i)=>`&sort${i}_field=${encodeURIComponent(s.col||'')}&sort${i}_dir=${s.dir||'asc'}`).join('');
}
function sortFieldsForGrid(fields){
  if(!fields||!fields.length)return {field:'',dir:'asc'};
  return {field:fields[0].col||'',dir:fields[0].dir||'asc'};
}
function sortFieldsSummary(fields){
  if(!fields||!fields.length)return '';
  return fields.filter(s=>s.col).map(s=>s.col+(s.dir==='desc'?' ↓':' ↑')).join(', ');
}

// ---- SESSION MEMORY (restore last page state) ----
function saveSessionState(page,data){try{sessionStorage.setItem('rollon_session_'+page,JSON.stringify(data))}catch(e){}}
function loadSessionState(page){try{return JSON.parse(sessionStorage.getItem('rollon_session_'+page)||'{}')}catch(e){return {}}}

// ---- NAV HISTORY (back button) ----
const NAV_STACK=[];
function pushNav(ri,table){NAV_STACK.push({ri,table})}

// ---- VIEWSYNC (localStorage + Sheets API persistence) ----
const ViewSync={
  _timers:{},
  load(page,lsKey){
    // 1. Return localStorage immediately (fast)
    let local={};
    try{local=JSON.parse(localStorage.getItem(lsKey)||'{}')}catch(e){}
    // 2. Fetch from server in background and merge (server wins if newer)
    fetch('/api/views/'+page).then(r=>r.json()).then(server=>{
      if(server&&Object.keys(server).length>0){
        // Merge: server views override local views by name
        const merged={...local,...server};
        localStorage.setItem(lsKey,JSON.stringify(merged));
      }
    }).catch(()=>{});
    return local;
  },
  save(page,lsKey,views){
    localStorage.setItem(lsKey,JSON.stringify(views));
    clearTimeout(this._timers[page]);
    this._timers[page]=setTimeout(()=>{
      fetch('/api/views/'+page,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(views)}).catch(()=>{});
    },2000);
  }
};

// ---- TOAST ----
function toast(msg,type='success'){const el=document.createElement('div');el.className='toast '+type;el.textContent=msg;document.getElementById('toast-container').appendChild(el);setTimeout(()=>el.remove(),3500)}

// ---- LONG TEXT POPUP (system-wide for all long fields) ----
function openLongTextPopup(fieldName,currentVal,onSave){
  // Remove any existing popup
  document.querySelector('.longtext-overlay')?.remove();
  const label=cleanH(fieldName);
  const overlay=document.createElement('div');
  overlay.className='longtext-overlay';
  overlay.innerHTML=`<div class="longtext-box">
    <div class="longtext-header"><h3>${esc(label)}</h3><span class="lt-close" onclick="closeLongTextPopup()">&times;</span></div>
    <div class="longtext-body"><textarea id="lt-textarea" placeholder="Enter ${esc(label).toLowerCase()}...">${esc(currentVal||'')}</textarea></div>
    <div class="longtext-footer"><button class="lt-cancel" onclick="closeLongTextPopup()">Cancel</button><button class="lt-save" id="lt-save-btn">Save</button></div>
  </div>`;
  document.body.appendChild(overlay);
  const ta=document.getElementById('lt-textarea');
  setTimeout(()=>{ta.focus();ta.setSelectionRange(ta.value.length,ta.value.length)},50);
  // Close on overlay click
  overlay.addEventListener('click',e=>{if(e.target===overlay)closeLongTextPopup()});
  // Escape to close
  const escHandler=e=>{if(e.key==='Escape'){e.stopPropagation();closeLongTextPopup();document.removeEventListener('keydown',escHandler,true)}};
  document.addEventListener('keydown',escHandler,true);
  // Save handler
  document.getElementById('lt-save-btn').addEventListener('click',()=>{
    const val=ta.value;
    closeLongTextPopup();
    document.removeEventListener('keydown',escHandler,true);
    if(onSave)onSave(val);
  });
}
function closeLongTextPopup(){document.querySelector('.longtext-overlay')?.remove()}

// ---- KEYBOARD ----
document.addEventListener('keydown',e=>{
  const tag=document.activeElement?.tagName;
  const isInput=tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT';
  if((e.metaKey||e.ctrlKey)&&e.key==='z'){
    if(isInput)return;
    e.preventDefault();
    fetch('/api/undo',{method:'POST'}).then(r=>r.json()).then(d=>{
      if(d.success){toast('Undo: '+d.field+' restored');if(typeof reload==='function')reload()}
      else toast(d.error||'Nothing to undo','error')
    })}
  // Cmd+Enter: save and close modal
  if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){
    const saveBtn=document.querySelector('.lt-save');
    if(saveBtn){e.preventDefault();saveBtn.click();return}
    const promptOk=document.getElementById('prompt-ok');
    if(promptOk){e.preventDefault();promptOk.click();return}
  }
  if(e.key==='Escape'){
    const ie=document.querySelector('.inline-edit');
    if(ie){const dv=ie.closest('.detail-value');if(dv){const ri=parseInt(dv.dataset.row),t=dv.dataset.table;refreshDetail(ri,t);return}}
    const ta=document.querySelector('.typeahead-wrap');if(ta){ta.remove();return}
    const fp=document.querySelector('.fields-panel.open');if(fp){fp.classList.remove('open');return}
    const cm=document.querySelector('.col-menu');if(cm){cm.remove();return}
    const pm=document.getElementById('prompt-modal');if(pm){pm.remove();return}
    closeModal();
  }
  // Shortcuts (only when not in input)
  if(isInput)return;
  // / focuses search
  if(e.key==='/'){e.preventDefault();const si=document.querySelector('.search-input')||document.getElementById('global-search');if(si)si.focus()}
  // N for new record
  if(e.key==='n'||e.key==='N'){
    if(typeof S!=='undefined'&&S.newRecord&&document.querySelector('[href="/songs"].active'))S.newRecord();
    else if(typeof D!=='undefined'&&D.newRecord&&document.querySelector('[href="/directory"].active'))D.newRecord();
  }
  // ? for shortcuts overlay
  if(e.key==='?')showShortcutsOverlay();
});

function showShortcutsOverlay(){
  document.querySelector('.shortcuts-overlay')?.remove();
  const ov=document.createElement('div');ov.className='shortcuts-overlay';
  ov.innerHTML=`<div class="shortcuts-box"><h3 style="color:var(--accent);margin-bottom:12px;font-family:var(--font-d)">Keyboard Shortcuts</h3>
    <div class="sc-row"><kbd>/</kbd><span>Focus search</span></div>
    <div class="sc-row"><kbd>N</kbd><span>New record</span></div>
    <div class="sc-row"><kbd>Esc</kbd><span>Close modal / cancel edit</span></div>
    <div class="sc-row"><kbd>Cmd+Z</kbd><span>Undo last change</span></div>
    <div class="sc-row"><kbd>Cmd+Enter</kbd><span>Save and close</span></div>
    <div class="sc-row"><kbd>?</kbd><span>Show this help</span></div>
    <button class="btn btn-sm" onclick="this.closest('.shortcuts-overlay').remove()" style="margin-top:12px">Close</button>
  </div>`;
  ov.addEventListener('click',e=>{if(e.target===ov)ov.remove()});
  document.body.appendChild(ov);
}

// ---- OUTSIDE CLICK ----
document.addEventListener('click',e=>{
  if(!e.target.closest('.fields-panel')&&!e.target.closest('.btn'))
    document.querySelectorAll('.fields-panel.open').forEach(p=>p.classList.remove('open'));
  if(!e.target.closest('.col-menu')&&!e.target.closest('th'))
    document.querySelectorAll('.col-menu').forEach(m=>m.remove());
  if(!e.target.closest('.search-dropdown')&&!e.target.closest('.toolbar-search'))
    document.querySelectorAll('.search-dropdown').forEach(d=>d.style.display='none');
});

// ---- MODAL ----
function openModal(title,bodyHtml){document.getElementById('modal-title').textContent=title;document.getElementById('modal-body').innerHTML=bodyHtml;document.getElementById('detail-modal').style.display='flex'}
function closeModal(){document.getElementById('detail-modal').style.display='none'}
document.getElementById('detail-modal')?.addEventListener('click',e=>{if(e.target.id==='detail-modal')closeModal()});

// ---- PROMPT MODAL (with searchable selects) ----
function showPromptModal(title,fields,onSubmit){
  let html=`<div class="prompt-overlay" id="prompt-modal"><div class="prompt-box"><h3>${esc(title)}</h3><div class="prompt-fields">`;
  fields.forEach((f,i)=>{
    html+=`<label>${esc(f.label)}</label>`;
    if(f.type==='select'){
      const opts=f.options||[];
      html+=`<div class="searchable-select" style="position:relative">`;
      html+=`<input id="pf${i}" class="prompt-input" placeholder="Search..." value="${escA(f.value||opts[0]||'')}" onclick="togglePfDD(${i})" oninput="filterPfDD(${i})">`;
      html+=`<div class="pf-dd" id="pfdd-${i}" style="display:none;position:absolute;top:100%;left:0;right:0;max-height:200px;overflow-y:auto;background:var(--bg-raised);border:1px solid var(--border-strong);border-radius:var(--r-md);z-index:60">`;
      opts.forEach(o=>{html+=`<div class="typeahead-item" data-val="${escA(o)}" onclick="pickPfOption(${i},'${escA(o)}')">${esc(o)}</div>`});
      html+=`</div></div>`;
    } else html+=`<input id="pf${i}" class="prompt-input" placeholder="${escA(f.placeholder||'')}" value="${escA(f.value||'')}">`;
  });
  html+=`</div><div class="prompt-actions"><button class="btn" onclick="document.getElementById('prompt-modal')?.remove()">Cancel</button><button class="btn btn-accent" id="prompt-ok">OK</button></div></div></div>`;
  document.body.insertAdjacentHTML('beforeend',html);
  document.getElementById('prompt-ok').onclick=()=>{
    const vals=fields.map((_,i)=>document.getElementById('pf'+i).value);
    document.getElementById('prompt-modal')?.remove();
    onSubmit(vals);
  };
  setTimeout(()=>document.getElementById('pf0')?.focus(),50);
}
function togglePfDD(idx){const dd=document.getElementById('pfdd-'+idx);if(!dd)return;dd.style.display=dd.style.display==='block'?'none':'block';
  if(dd.style.display==='block'){document.getElementById('pf'+idx)?.select();setTimeout(()=>{const h=e=>{if(!dd.contains(e.target)&&e.target!==document.getElementById('pf'+idx)){dd.style.display='none';document.removeEventListener('click',h)}};document.addEventListener('click',h)},50)}}
function filterPfDD(idx){const dd=document.getElementById('pfdd-'+idx);if(!dd)return;const q=(document.getElementById('pf'+idx)?.value||'').toLowerCase();
  dd.querySelectorAll('.typeahead-item').forEach(el=>{el.style.display=(el.dataset.val||'').toLowerCase().includes(q)?'':'none'});dd.style.display='block';
  // Reset highlight
  dd.querySelectorAll('.typeahead-item').forEach(el=>el.classList.remove('ta-highlight'));
  const vis=Array.from(dd.querySelectorAll('.typeahead-item')).filter(el=>el.style.display!=='none');
  if(vis.length)vis[0].classList.add('ta-highlight');
}
function pickPfOption(idx,val){document.getElementById('pf'+idx).value=val;document.getElementById('pfdd-'+idx).style.display='none'}

// ---- TYPEAHEAD FOR PROMPT MODAL FIELDS (wires Personnel/company search onto prompt inputs) ----
function wirePromptTypeahead(fieldIdx,table,multiValue){
  const inp=document.getElementById('pf'+fieldIdx);if(!inp)return;
  // Create dropdown container
  let dd=document.getElementById('pfta-'+fieldIdx);
  if(!dd){dd=document.createElement('div');dd.id='pfta-'+fieldIdx;dd.className='typeahead-dropdown';
    dd.style.cssText='display:none;position:absolute;top:100%;left:0;right:0;max-height:200px;overflow-y:auto;background:var(--bg-raised);border:1px solid var(--border-strong);border-radius:var(--r-md);z-index:60';
    inp.parentElement.style.position='relative';inp.parentElement.appendChild(dd)}
  let deb;
  inp.addEventListener('input',()=>{clearTimeout(deb);deb=setTimeout(()=>{
    // For multi-value (pipe-separated), search the last segment
    let q=inp.value.trim();
    if(multiValue){const parts=q.split('|');q=parts[parts.length-1].trim()}
    if(q.length<1){dd.style.display='none';return}
    fetch('/api/search-record?q='+encodeURIComponent(q)+'&table='+encodeURIComponent(table)).then(r=>r.json()).then(d=>{
      let html=(d.results||[]).slice(0,10).map(r=>
        `<div class="typeahead-item" data-name="${escA(r.name)}" onclick="pickPromptTA(${fieldIdx},'${escA(r.name)}',${multiValue})">${esc(r.name)} <span style="font-size:9px;color:var(--text-ghost)">${esc(r.table)}</span></div>`
      ).join('');
      if(!html)html='<div style="padding:8px;color:var(--text-ghost);font-size:11px">No matches</div>';
      dd.innerHTML=html;dd.style.display='block';
    });
  },200)});
  inp.addEventListener('blur',()=>{setTimeout(()=>{dd.style.display='none'},200)});
}

function pickPromptTA(fieldIdx,name,multiValue){
  const inp=document.getElementById('pf'+fieldIdx);if(!inp)return;
  if(multiValue){
    const parts=inp.value.split('|').map(p=>p.trim()).filter(Boolean);
    parts[parts.length-1]=name;
    inp.value=parts.join(' | ')+' | ';
  } else {
    inp.value=name;
  }
  const dd=document.getElementById('pfta-'+fieldIdx);if(dd)dd.style.display='none';
  inp.focus();
}

// Keyboard navigation for all searchable dropdowns
document.addEventListener('keydown',e=>{
  if(e.key!=='ArrowDown'&&e.key!=='ArrowUp'&&e.key!=='Enter')return;
  const inp=document.activeElement;if(!inp)return;
  // Find the associated dropdown
  let dd=null;
  if(inp.classList.contains('filter-field-search')){const idx=inp.dataset.fidx;dd=document.getElementById('ffd-'+idx)}
  else if(inp.id&&inp.id.startsWith('pf')){const idx=inp.id.replace('pf','');dd=document.getElementById('pfdd-'+idx)}
  else if(inp.id==='group-field-input'){dd=document.getElementById('pfdd-group')}
  else if(inp.id==='dir-group-field'){dd=document.getElementById('pfdd-dgroup')}
  else if(inp.classList.contains('filter-link-input')){const idx=inp.dataset.fidx;dd=document.getElementById('fld-'+idx)}
  if(!dd||dd.style.display==='none')return;
  const items=Array.from(dd.querySelectorAll('.typeahead-item')).filter(el=>el.style.display!=='none');
  if(!items.length)return;
  const cur=dd.querySelector('.ta-highlight');
  let ci=cur?items.indexOf(cur):-1;
  if(e.key==='ArrowDown'){e.preventDefault();ci=Math.min(ci+1,items.length-1)}
  else if(e.key==='ArrowUp'){e.preventDefault();ci=Math.max(ci-1,0)}
  else if(e.key==='Enter'){e.preventDefault();if(cur)cur.click();return}
  items.forEach(el=>el.classList.remove('ta-highlight'));
  if(items[ci]){items[ci].classList.add('ta-highlight');items[ci].scrollIntoView({block:'nearest'})}
});

// ---- CLEAN HEADER ----
function cleanH(h){return(h||'').replace(/\[✓\]\s*|\[✗\]\s*|\[\?\?\]\s*|\[∅\]\s*|\[\s*✓\]\s*/g,'').trim()}

// ---- FIELD TYPE DETECTION (LINK before LONG) ----
const LINK_FIELDS=['songwriter credits','artist','producer','record label','mixing engineer',
  'mastering engineer','mgmt company','publishing company','agent','agency','works with','studio','city','recording city',
  'artist pitches','label pitches','sync pitches','pub pitches','vocalist',
  'mgmt rep','publishing rep','agent rep','publicist rep','music sup','label parent',
  'songs written','songs produced','songs mixed','songs mastered','repertoire','produced','mixed','mastered','client'];
// Map link fields to which table they should search
const LINK_TABLE_MAP={
  'record label':'Record Labels','label':'Record Labels',
  'mgmt company':'MGMT Companies','mgmt':'MGMT Companies',
  'publishing company':'Publishing Company','publisher':'Publishing Company',
  'agent':'Agent','agency':'Agency Company','agency company':'Agency Company',
  'studio':'Studios','studios':'Studios','city':'Cities',
  'artist pitches':'Personnel','label pitches':'Record Labels',
  'sync pitches':'Music Sup Company','pub pitches':'Music Sup Company','vocalist':'Personnel'
};
function getLinkTable(fieldName){
  const h=cleanH(fieldName).toLowerCase();
  // Check overrides first
  const overrides=getFieldTypeOverrides();
  const ov=overrides[h];
  if(ov==='link_labels')return 'Record Labels';
  if(ov==='link_companies')return 'MGMT Companies';
  if(ov==='link_cities')return 'Cities';
  if(ov==='link_personnel')return 'Personnel';
  // Fall back to name-based detection
  for(const [key,tbl] of Object.entries(LINK_TABLE_MAP)){if(h.includes(key))return tbl}
  return 'Personnel';
}
const URL_FIELDS=['dropbox link','disco','song url','linkedin/socials','website','url','lyric docs','lyrics docs','lyric doc','legal docs','legal doc','attachment','attachments'];
const DATE_FIELDS=['written date','release date','recording date','last modified','created',
  'last outreach','admin due date'];
const DATETIME_FIELDS=['set out reach date/time'];
// Convert ISO 'YYYY-MM-DDTHH:MM[:SS]' or 'DD/MM/YYYY HH:MM[:SS]' to display 'DD/MM/YYYY HH:MM'
function _dtToDisplay(v){if(!v)return '';const s=String(v).trim();
  let m=s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);if(m)return `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}`;
  m=s.match(/^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2})/);if(m)return `${m[1]}/${m[2]}/${m[3]} ${m[4]}:${m[5]}`;
  return s;}
// Convert stored value to datetime-local input format 'YYYY-MM-DDTHH:MM'
function _dtToInput(v){if(!v)return '';const s=String(v).trim();
  let m=s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);if(m)return `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}`;
  m=s.match(/^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2})/);if(m)return `${m[3]}-${m[2]}-${m[1]}T${m[4]}:${m[5]}`;
  m=s.match(/^(\d{4})-(\d{2})-(\d{2})$/);if(m)return `${m[1]}-${m[2]}-${m[3]}T11:06`;
  return '';}
// Default: tomorrow 11:06 in browser local time, formatted for datetime-local input
function _dtDefault(){const d=new Date();d.setDate(d.getDate()+1);d.setHours(11,6,0,0);
  const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;}
const TAG_FIELDS=['tag','tags'];
const LONG_FIELDS=['lyrics','bio','outreach notes','label copy','alt pitch','master split','pub credit'];
const CHECKLIST_FIELDS=['song admin'];
const AUTO_FIELDS=['project','type of label','sync type'];
// Multi-value autocomplete fields (use pill editor like tags)
const MULTI_AUTO_FIELDS=['genre','countries','pro','format','audio status','dance pitches','writer ipi','pub ipi'];

// Field tooltips for interns/assistants
const FIELD_TIPS={
  'title':'The song title as it appears on release',
  'tag':'Internal tags for filtering and organizing songs',
  'audio status':'Current stage: Demo, Production, Mixed, Mastered, Released',
  'artist':'The performing/credited artist on the release',
  'producer':'Music producer(s) who created the beat/production',
  'songwriter credits':'All songwriters with publishing splits',
  'release date':'Official release date. Auto-sets status to Released when past.',
  'project':'Which project/album/EP this song belongs to',
  'song admin':'Checklist of admin tasks (metadata, registration, delivery)',
  'disco':'DISCO playlist link for pitching',
  'dropbox link':'Dropbox link to audio files and stems',
  'song url':'Public streaming link (Spotify, Apple Music, ffm.to)',
  'lyrics':'Full song lyrics text',
  'label copy':'Formatted credits for DSP metadata and liner notes',
  'master split':'Master ownership split percentages between parties',
  'pub credit':'Publishing split: writer names, companies, PROs',
  'genre':'Musical genre(s) for pitching and cataloguing',
  'isrc':'International Standard Recording Code (unique per recording)',
  'recording city':'Where the song was recorded. Auto-fills country.',
  'recording country':'Country of recording. Auto-filled from city.',
  'artist pitches':'Artists this song has been pitched to',
  'label pitches':'Labels this song has been pitched to',
  'sync pitches':'Sync companies/supervisors pitched to',
  'dance pitches':'Dance pitch round numbers (001, 002, etc)',
  'vocalist':'The vocalist(s) performing on the track',
  'writer ipi':'Songwriter IPI numbers for PRO registration',
  'pub ipi':'Publisher IPI numbers for PRO registration',
  'duration':'Song length in HH:MM:SS format',
  'modified by':'Last person who edited this record',
  'last modified':'Date and time of last edit',
  'name':'Contact full name',
  'email':'Primary email address',
  'field':'Industry role (A&R, MGMT, Sync, etc)',
  'tags':'Internal tags for filtering contacts',
  'city':'Contact location. Auto-fills country and timezone.',
  'countries':'Country/countries the contact works in',
};
function fieldTip(h){return FIELD_TIPS[cleanH(h).toLowerCase()]||''}

function fieldType(header){
  const h=cleanH(header).toLowerCase();
  // Check field type overrides first (from Add Field picker)
  const overrides=getFieldTypeOverrides();
  const ov=overrides[h];
  if(ov){
    const typeMap={
      'text':'text','long':'long','multi_select':'tag','single_select':'autocomplete',
      'link_personnel':'link','link_labels':'link','link_companies':'link','link_cities':'link',
      'date':'date','duration':'duration','number':'number','currency':'currency','percent':'percent',
      'url':'url','email':'contact','phone':'contact','checkbox':'checklist','user':'text','rating':'rating',
      'attachment':'url'
    };
    if(typeMap[ov])return typeMap[ov];
  }
  // Set Out Reach Date/Time needs HH:MM, handled before generic date match
  if(DATETIME_FIELDS.some(d=>h.includes(d)))return 'datetime';
  // Airtable lookup fields [LU] always contain linked record names
  if(h.includes('[lu]'))return 'link';
  // Default detection from field name
  if(CHECKLIST_FIELDS.some(c=>h.includes(c)))return 'checklist';
  if(TAG_FIELDS.some(t=>h===t||h===t+'s'))return 'tag';
  if(LINK_FIELDS.some(l=>h.includes(l)))return 'link';
  if(URL_FIELDS.some(u=>h.includes(u)))return 'url';
  if(DATE_FIELDS.some(d=>h.includes(d)))return 'date';
  if(LONG_FIELDS.some(l=>h.includes(l)))return 'long';
  if(h==='email'||h==='emails combined'||h==='telephone'||h==='invoice email'||h==='invoice emails')return 'contact';
  if(h==='invoice address')return 'long';
  if(h==='airtable id'||h==='system id'||h.startsWith('sx id'))return 'id';
  if(h==='field')return 'field_type';
  if(h==='duration'||h==='song duration'||h.includes('duration'))return 'duration';
  if(MULTI_AUTO_FIELDS.some(a=>h===a))return 'tag';
  if(AUTO_FIELDS.some(a=>h===a))return 'autocomplete';
  return 'text';
}

// ---- RENDER CELL ----
function renderCell(header,value,ri,table){
  if(!value||value==='undefined'||value==='null')return '';
  const type=fieldType(header);const v=String(value).trim();if(!v)return '';
  switch(type){
    case 'tag':return renderTagPills(v);
    case 'url':return renderUrls(v);
    case 'date':return `<span class="cell-date">${esc(v)}</span>`;
    case 'datetime':return `<span class="cell-date">${esc(_dtToDisplay(v))}</span>`;
    case 'long':return `<span class="cell-text" title="${escA(v)}">${esc(v.length>60?v.substring(0,60)+'...':v)}</span>`;
    case 'contact':return renderContactPill(v);
    case 'id':return `<span class="cell-text" style="font-family:var(--font-m);font-size:10px;color:var(--text-ghost)">${esc(v.substring(0,12))}</span>`;
    case 'duration':return `<span class="cell-text" style="font-family:var(--font-m);font-size:12px">${esc(v)}</span>`;
    case 'number':return `<span class="cell-text" style="font-family:var(--font-m);font-size:12px;text-align:right;display:block">${esc(v)}</span>`;
    case 'currency':{const n=parseFloat(v.replace(/[^0-9.-]/g,''));return `<span class="cell-text" style="font-family:var(--font-m);font-size:12px;text-align:right;display:block">${isNaN(n)?esc(v):'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</span>`}
    case 'percent':{const n=parseFloat(v.replace(/[^0-9.-]/g,''));return `<span class="cell-text" style="font-family:var(--font-m);font-size:12px;text-align:right;display:block">${isNaN(n)?esc(v):n+'%'}</span>`}
    case 'rating':{const n=Math.min(5,Math.max(0,parseInt(v)||0));return '<span style="color:var(--accent);letter-spacing:2px">'+('★'.repeat(n)+'☆'.repeat(5-n))+'</span>'}
    case 'link':return renderLinkedPills(v);
    case 'field_type':return renderFieldTypePill(v);
    case 'checklist':const items=v.split('\n').filter(x=>x.trim()),done=items.filter(x=>x.startsWith('[x]')||x.startsWith('[X]')).length;return `<span class="pill">${done}/${items.length} done</span>`;
    case 'autocomplete':return renderTextPills(v);
    default:{
      // Handle JSON button fields
      if(v.startsWith('{')&&v.includes('"label"')&&v.includes('"url"')){
        try{const obj=JSON.parse(v);const url=obj.url||'';const label=obj.label||'Link';
          if(url)return `<a href="${escA(url)}" target="_blank" class="pill pill-link" style="text-decoration:none">${esc(label)}</a>`;
        }catch(e){}
      }
      // Handle unresolved rec IDs (show as dimmed)
      if(/^rec[A-Za-z0-9]{10,}$/.test(v))return `<span class="pill" style="font-size:9px;color:var(--text-ghost)">${esc(v.substring(0,10))}...</span>`;
      return renderTextPills(v);
    }
  }
}

function renderTagPills(v){const tags=splitP(v);const ac='#d4a853';return '<div class="cell-pills">'+tags.map(t=>{
  if(PILL_COLORED){const c=TAG_COLORS[t]||TAG_COLORS[t.trim()]||ac;
    return `<span class="pill pill-tag" style="background:${c}20;color:${c};border:1px solid ${c}40">${esc(t)}</span>`}
  return `<span class="pill pill-tag" style="background:${ac}20;color:${ac};border:1px solid ${ac}40">${esc(t)}</span>`}).join('')+'</div>'}

function renderLinkedPills(v){const items=splitP(v).sort((a,b)=>a.localeCompare(b));return '<div class="cell-pills">'+items.map(t=>
  `<span class="pill pill-link" onclick="event.stopPropagation();navToRecord('${escA(t)}')" onmouseenter="showPeek(event,'${escA(t)}')" onmouseleave="hidePeek()" style="cursor:pointer">${esc(t)}</span>`).join('')+'</div>'}

// Navigable version for detail modal only
function renderLinkedPillsNav(v){const items=splitP(v).sort((a,b)=>a.localeCompare(b));return '<div class="cell-pills">'+items.map(t=>
  `<span class="pill pill-link" onclick="event.stopPropagation();navToRecord('${escA(t)}')" onmouseenter="showPeek(event,'${escA(t)}')" onmouseleave="hidePeek()" style="cursor:pointer">${esc(t)}</span>`).join('')+'</div>'}

// ---- HOVER PEEK CARD ----
let _peekTimer=null,_peekEl=null;
function showPeek(e,name){
  clearTimeout(_peekTimer);
  _peekTimer=setTimeout(()=>{
    fetch(`/api/quick-lookup?name=${encodeURIComponent(name)}`).then(r=>r.json()).then(d=>{
      if(!d.found)return;
      hidePeek();
      _peekEl=document.createElement('div');_peekEl.className='peek-card';
      let html=`<div class="peek-name">${esc(d.name||name)}</div>`;
      if(d.field)html+=`<div class="peek-field">${esc(d.field)}</div>`;
      if(d.city)html+=`<div class="peek-row">${esc(d.city)}</div>`;
      if(d.email)html+=`<div class="peek-row">${esc(d.email)}</div>`;
      if(d.last_outreach)html+=`<div class="peek-row">Last outreach: ${esc(d.last_outreach)}</div>`;
      _peekEl.innerHTML=html;
      const rect=e.target.getBoundingClientRect();
      _peekEl.style.left=Math.min(rect.left,window.innerWidth-320)+'px';
      _peekEl.style.top=(rect.bottom+6)+'px';
      document.body.appendChild(_peekEl);
    }).catch(()=>{});
  },400);
}
function hidePeek(){clearTimeout(_peekTimer);if(_peekEl){_peekEl.remove();_peekEl=null}}

function renderTextPills(v){const items=splitP(v);if(items.length===1&&items[0].length>50)return `<span class="cell-text">${esc(items[0])}</span>`;
  return '<div class="cell-pills">'+items.map(t=>`<span class="pill">${esc(t)}</span>`).join('')+'</div>'}

function renderFieldTypePill(v){const ac='#d4a853';return '<div class="cell-pills">'+splitP(v).map(t=>{
  if(PILL_COLORED){const c=TAG_COLORS[t]||ac;
    return `<span class="pill pill-tag" style="background:${c}20;color:${c};border:1px solid ${c}40">${esc(t)}</span>`}
  return `<span class="pill pill-tag" style="background:${ac}20;color:${ac};border:1px solid ${ac}40">${esc(t)}</span>`}).join('')+'</div>'}

function renderContactPill(v){return `<span class="pill" onclick="event.stopPropagation();copyText('${escA(v)}')" title="Click to copy">📋 ${esc(v)}</span>`}

function renderUrls(v){const urls=v.split(/[,\s]+/).filter(u=>u.startsWith('http'));
  if(!urls.length)return `<span class="cell-text">${esc(v)}</span>`;
  return urls.map(u=>{
    const short=u.replace(/https?:\/\/(www\.)?/,'').substring(0,30);
    const isDropbox=u.includes('dropbox.com');
    const isDisco=u.includes('disco.ac');
    const icon=isDropbox?'\u25B6 ':isDisco?'\uD83C\uDFB5 ':'';
    return `<span class="cell-url"><a href="${escA(u)}" target="_blank" onclick="event.stopPropagation()">${icon}${esc(short)}</a></span>`;
  }).join(' ')}

// ---- DETAIL MODAL ----
function renderDetailModal(record,headers,table){
  let name='Record';
  for(const h of headers){const ch=cleanH(h).toLowerCase();
    if(ch==='title'||ch==='name'){const v=record[h];if(v){name=v.split(' | ')[0]||v;break}}}
  if(name==='Record')name=record[headers[1]]||'Record';

  // Find record ID
  const idH=headers.find(h=>cleanH(h).toLowerCase()==='airtable id'||cleanH(h).toLowerCase()==='system id');
  const recordId=idH?record[idH]||'':'';

  const ri=record._row_index;
  const lyricsH=headers.find(h=>cleanH(h).toLowerCase()==='lyrics');
  const labelCopyH=headers.find(h=>cleanH(h).toLowerCase()==='label copy');
  const pubCreditH=headers.find(h=>cleanH(h).toLowerCase().includes('pub credit'));
  const masterSplitsH=headers.find(h=>cleanH(h).toLowerCase().includes('master splits'));
  const hasTabs=table==='songs'&&lyricsH;
  const hasDirTabs=table==='directory';
  // Only Lyrics is tab-only. Label Copy, Pub Credit, Master Splits show in detail grid as normal fields.
  const tabFields=[lyricsH].filter(Boolean);

  let actHtml='';
  if(table==='songs')actHtml=songActions(record,headers);
  else if(table==='directory')actHtml=dirActions(record,headers);

  // Back button if nav history exists
  let backBtn='';
  if(NAV_STACK.length>1){
    backBtn=`<button class="btn btn-sm" onclick="goBack()" style="margin-right:8px">← Back</button>`;
  }

  let html=`<div class="detail-actions">${backBtn}${recordId?`<span class="record-id-badge" onclick="copyText('${escA(recordId)}')" title="Click to copy ID">${esc(recordId)}</span>`:''} ${actHtml}</div>`;

  if(hasTabs){
    html+='<div class="modal-tabs">';
    html+='<div class="modal-tab active" onclick="switchTab(this,\'tab-details\')">Details</div>';
    html+='<div class="modal-tab" onclick="switchTab(this,\'tab-lyrics\')">Lyrics</div>';
    html+='<div class="modal-tab" onclick="switchTab(this,\'tab-history\');loadHistory('+ri+',\'songs\')">History</div>';
    html+='</div>';
  }

  if(hasDirTabs){
    html+='<div class="modal-tabs">';
    html+='<div class="modal-tab active" onclick="switchTab(this,\'tab-details\')">Details</div>';
    html+='<div class="modal-tab" onclick="switchTab(this,\'tab-timeline\')">Timeline</div>';
    html+='<div class="modal-tab" onclick="switchTab(this,\'tab-history\');loadHistory('+ri+',\'directory\')">History</div>';
    html+='</div>';
  }

  // Details tab
  const _hideEmpty=localStorage.getItem('rollon_hide_empty')==='true';
  html+=`<div id="tab-details" class="modal-tab-content active">`;
  html+=`<div class="detail-toolbar"><button class="hide-empty-pill ${_hideEmpty?'active':''}" onclick="toggleHideEmpty(!this.classList.contains('active'))">${_hideEmpty?'Show All Fields':'Hide Empty'}</button></div>`;
  html+=`<div class="detail-grid" ${_hideEmpty?'data-hide-empty="1"':''}>`;
  // Rights & Registration fields to group into collapsible section
  const RIGHTS_FIELDS=['writer 1 ipi','writer 2 ipi','writer 3 ipi','publisher 1','publisher 1 ipi','publisher 2','publisher 2 ipi','publisher 3','publisher 3 ipi','isrc','iswc','cat no','gtin/barcode','gtin','barcode'];
  let rightsHtml='';
  let hasRightsData=false;
  for(const h of headers){
    const ch=cleanH(h);const chLow=ch.toLowerCase();
    if(tabFields.includes(h))continue;
    const val=record[h]||'';const type=fieldType(h);
    const isEmpty=!val||!val.trim();
    if(!isEmpty&&RIGHTS_FIELDS.includes(chLow))hasRightsData=true;
    // ID field is read-only
    if(chLow==='airtable id'||chLow==='system id'){
      if(val){html+=`<div class="detail-label">System ID</div><div class="detail-value" style="font-family:var(--font-m);font-size:11px;color:var(--text-ghost);cursor:pointer" onclick="copyText('${escA(val)}')" title="Click to copy">${esc(val)}</div>`}
      continue;
    }
    html+=`<div class="detail-label${isEmpty?' empty-field':''}">${esc(ch)}${fieldTip(h)?`<span class="field-tip" title="${escA(fieldTip(h))}">ⓘ</span>`:''}</div>`;
    html+=`<div class="detail-value editable${isEmpty?' empty-field':''}" data-field="${escA(h)}" data-row="${ri}" data-table="${table}" data-type="${type}" data-current="${escData(val)}" onclick="startEdit(this)">`;
    html+=renderDetailValue(val,type,h);
    html+='</div>';
  }
  html+='</div></div>';

  // Directory timeline tab
  if(hasDirTabs){
    html+=`<div id="tab-timeline" class="modal-tab-content">${renderActivityTimeline(record,headers)}</div>`;
  }

  // Lyrics tab
  if(lyricsH){
    const v=record[lyricsH]||'';
    html+=`<div id="tab-lyrics" class="modal-tab-content"><div class="detail-value editable" data-field="${escA(lyricsH)}" data-row="${ri}" data-table="${table}" data-type="long" data-current="${escData(v)}" onclick="startEdit(this)" style="min-height:200px;white-space:pre-wrap;font-size:13px;line-height:1.7">${v?esc(v):'<span class="pill pill-empty">Click to add</span>'}</div></div>`;
  }
  // History tab (loaded on demand)
  html+=`<div id="tab-history" class="modal-tab-content"><div style="padding:12px;color:var(--text-muted)">Loading history...</div></div>`;
  openModal(name,html);
}

function loadHistory(ri,table){
  const el=document.getElementById('tab-history');if(!el)return;
  fetch(`/api/history/${table}/${ri}`).then(r=>r.json()).then(d=>{
    const edits=d.edits||[];
    if(!edits.length){el.innerHTML='<div style="padding:12px;color:var(--text-muted)">No edits recorded this session.</div>';return}
    let html='<div class="history-list">';
    edits.forEach(e=>{
      const ts=e.timestamp?new Date(e.timestamp).toLocaleString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'';
      const field=e.field?e.field.replace(/\[.*?\]\s*/g,'').trim():'';
      const oldV=(e.old_value||'').substring(0,80);
      const newV=(e.new_value||'').substring(0,80);
      html+=`<div class="history-item">`;
      html+=`<div class="history-field">${esc(field)}</div>`;
      html+=`<div class="history-change"><span class="history-old">${oldV?esc(oldV):'(empty)'}</span> → <span class="history-new">${newV?esc(newV):'(empty)'}</span></div>`;
      html+=`<div class="history-time">${ts}</div>`;
      html+=`</div>`;
    });
    html+='</div>';
    el.innerHTML=html;
  }).catch(()=>{el.innerHTML='<div style="padding:12px;color:var(--danger)">Failed to load history.</div>'});
}

function renderDetailValue(val,type){
  if(!val||!val.trim()){
    if(type==='tag')return '<span class="pill pill-empty">No tags, click to add</span>';
    return '<span class="pill pill-empty">Click to add</span>';
  }
  switch(type){
    case 'tag':return renderTagPills(val);
    case 'url':return renderUrls(val);
    case 'date':return `<span class="cell-date">${esc(val)}</span>`;
    case 'datetime':return `<span class="cell-date">${esc(_dtToDisplay(val))}</span>`;
    case 'long':return `<span class="cell-text" style="white-space:pre-wrap">${esc(val)}</span>`;
    case 'link':return renderLinkedPillsNav(val);
    case 'contact':return renderContactPill(val);
    case 'checklist':return renderChecklist(val);
    case 'autocomplete':return renderTextPills(val);
    case 'number':return `<span style="font-family:var(--font-m)">${esc(val)}</span>`;
    case 'currency':{const n=parseFloat(val.replace(/[^0-9.-]/g,''));return `<span style="font-family:var(--font-m)">${isNaN(n)?esc(val):'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</span>`}
    case 'percent':{const n=parseFloat(val.replace(/[^0-9.-]/g,''));return `<span style="font-family:var(--font-m)">${isNaN(n)?esc(val):n+'%'}</span>`}
    case 'duration':return `<span style="font-family:var(--font-m)">${esc(val)}</span>`;
    case 'rating':{const n=Math.min(5,Math.max(0,parseInt(val)||0));return '<span style="color:var(--accent);font-size:18px;letter-spacing:2px">'+('★'.repeat(n)+'☆'.repeat(5-n))+'</span>'}
    default:{
      // Handle JSON button fields
      if(val.startsWith('{')&&val.includes('"label"')&&val.includes('"url"')){
        try{const obj=JSON.parse(val);const url=obj.url||'';const label=obj.label||'Link';
          if(url)return `<a href="${escA(url)}" target="_blank" class="btn btn-sm" style="text-decoration:none">${esc(label)}</a>`;
        }catch(e){}
      }
      return renderTextPills(val);
    }
  }
}

function switchTab(el,tabId){
  el.closest('.modal-body').querySelectorAll('.modal-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  el.closest('.modal-body').querySelectorAll('.modal-tab-content').forEach(t=>t.classList.remove('active'));
  document.getElementById(tabId)?.classList.add('active');
}

function renderChecklist(val){
  if(!val||!val.trim())return '<div style="width:100%"><div class="checklist-item" style="opacity:.6"><span class="pill pill-add" onclick="addChecklistItem(this)" style="font-size:12px;padding:2px 10px">+ Add item</span></div></div>';
  let items;
  // Check if data has proper checklist format ([x] or [ ] prefixes)
  if(val.includes('[x]')||val.includes('[ ]')||val.includes('[X]')){
    items=val.split('\n').filter(x=>x.trim());
  } else if(val.includes('\n')){
    // Has newlines but no markers - treat each line as unchecked
    items=val.split('\n').filter(x=>x.trim()).map(x=>x.startsWith('[ ]')||x.startsWith('[x]')?x:'[ ] '+x);
  } else {
    // Flat text from Airtable sync - no newlines, no markers
    // Render as editable textarea so user can reformat
    return `<div style="width:100%"><div style="font-size:12px;color:var(--text-dim);margin-bottom:6px;white-space:pre-wrap">${esc(val)}</div><div class="checklist-item" style="opacity:.6"><span class="pill pill-add" onclick="convertToChecklist(this)" style="font-size:12px;padding:2px 10px">↻ Convert to checklist</span></div></div>`;
  }
  let html='<div style="width:100%">';
  items.forEach((item,i)=>{
    const done=item.startsWith('[x]')||item.startsWith('[X]');
    const text=item.replace(/^\[.\]\s*/,'');
    html+=`<div class="checklist-item ${done?'checked':''}"><input type="checkbox" ${done?'checked':''} onclick="toggleChecklist(this,${i})"><span onclick="editChecklistItem(this,${i})" style="flex:1;cursor:text">${esc(text)}</span><span class="pill-x" onclick="deleteChecklistItem(this,${i})" title="Delete task" style="cursor:pointer;opacity:.4;margin-left:4px">&times;</span></div>`;
  });
  html+=`<div class="checklist-item" style="opacity:.6"><span class="pill pill-add" onclick="addChecklistItem(this)" style="font-size:12px;padding:2px 10px">+ Add item</span></div>`;
  html+='</div>';
  return html;
}

function convertToChecklist(btn){
  const dv=btn.closest('.detail-value');if(!dv)return;
  const field=dv.dataset.field,ri=parseInt(dv.dataset.row),table=dv.dataset.table;
  const cv=readData(dv)||'';
  // Try to split flat text into separate items
  // Common patterns: sentences ending with periods, or phrases separated by multiple spaces
  let items=cv.split(/(?<=[a-z])\s*(?=[A-Z])/g).filter(x=>x.trim());
  if(items.length<=1)items=cv.split(/[.;]\s*/).filter(x=>x.trim());
  if(items.length<=1)items=[cv];
  const formatted=items.map(x=>'[ ] '+x.trim()).join('\n');
  saveEdit(dv,field,ri,table,formatted);
}

function addChecklistItem(btn){
  const dv=btn.closest('.detail-value');if(!dv)return;
  const field=dv.dataset.field,ri=parseInt(dv.dataset.row),table=dv.dataset.table;
  const cv=readData(dv)||'';
  // Insert input inline
  const wrap=document.createElement('div');wrap.className='checklist-item';
  wrap.innerHTML='<input type="checkbox" disabled><input class="inline-edit" placeholder="New task..." style="flex:1">';
  btn.closest('.checklist-item').replaceWith(wrap);
  const inp=wrap.querySelector('.inline-edit');inp.focus();
  inp.addEventListener('blur',()=>{
    const text=inp.value.trim();
    if(!text){wrap.remove();dv.insertAdjacentHTML('beforeend','<div class="checklist-item" style="opacity:.6"><span class="pill pill-add" onclick="addChecklistItem(this)" style="font-size:12px;padding:2px 10px">+ Add item</span></div>');return}
    // Build new value from current DOM items + new item
    const items=[];
    dv.querySelectorAll('.checklist-item').forEach(el=>{
      const cbx=el.querySelector('input[type="checkbox"]');
      const span=el.querySelector('span[onclick*="editChecklistItem"]');
      if(cbx&&span) items.push((cbx.checked?'[x] ':'[ ] ')+span.textContent);
    });
    items.push('[ ] '+text);
    saveEdit(dv,field,ri,table,items.join('\n'),false);
  });
  inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();inp.blur()}
    if(e.key==='Escape'){e.stopPropagation();refreshDetail(ri,table)}
  });
}
function toggleChecklist(cb,idx){
  const dv=cb.closest('.detail-value');if(!dv)return;
  const field=dv.dataset.field,ri=parseInt(dv.dataset.row),table=dv.dataset.table;
  // Optimistic: toggle UI immediately from current DOM state, save in background
  const allItems=dv.querySelectorAll('.checklist-item');
  const itemDiv=allItems[idx];
  if(itemDiv){
    const isNowChecked=cb.checked;
    itemDiv.classList.toggle('checked',isNowChecked);
  }
  // Build new value from all checklist items in current DOM
  const items=[];
  dv.querySelectorAll('.checklist-item').forEach(el=>{
    const cbx=el.querySelector('input[type="checkbox"]');
    const span=el.querySelector('span[onclick*="editChecklistItem"]');
    if(cbx&&span){
      items.push((cbx.checked?'[x] ':'[ ] ')+span.textContent);
    }
  });
  if(items.length) saveEdit(dv,field,ri,table,items.join('\n'),true);
}

function editChecklistItem(span,idx){
  const dv=span.closest('.detail-value');if(!dv)return;
  const field=dv.dataset.field,ri=parseInt(dv.dataset.row),table=dv.dataset.table;
  const currentText=span.textContent;
  const inp=document.createElement('input');
  inp.className='inline-edit';inp.value=currentText;inp.style.flex='1';
  span.replaceWith(inp);inp.focus();inp.select();
  const save=()=>{
    const ep2=table==='songs'?`/api/songs/${ri}`:`/api/directory/${ri}`;
    fetch(ep2).then(r=>r.json()).then(rec=>{
      const cv=rec[field]||'';
      const items=cv.split('\n').filter(x=>x.trim());
      if(idx<items.length){
        const done=items[idx].startsWith('[x]')||items[idx].startsWith('[X]');
        items[idx]=(done?'[x] ':'[ ] ')+inp.value.trim();
        saveEdit(dv,field,ri,table,items.join('\n'));
      }
    });
  };
  inp.addEventListener('blur',save);
  inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();inp.blur()}if(e.key==='Escape'){refreshDetail(ri,table)}});
}

function deleteChecklistItem(xEl,idx){
  const dv=xEl.closest('.detail-value');if(!dv)return;
  const field=dv.dataset.field,ri=parseInt(dv.dataset.row),table=dv.dataset.table;
  const ep=table==='songs'?`/api/songs/${ri}`:`/api/directory/${ri}`;
  fetch(ep).then(r=>r.json()).then(rec=>{
    const cv=rec[field]||'';
    const items=cv.split('\n').filter(x=>x.trim());
    if(idx<items.length){items.splice(idx,1);saveEdit(dv,field,ri,table,items.join('\n'))}
  });
}

function goBack(){
  if(NAV_STACK.length<2)return;
  NAV_STACK.pop();
  const prev=NAV_STACK[NAV_STACK.length-1];
  const ep=prev.table==='songs'?`/api/songs/${prev.ri}`:`/api/directory/${prev.ri}`;
  const hep=prev.table==='songs'?'/api/songs?per_page=1':'/api/directory?per_page=1';
  Promise.all([fetch(ep).then(r=>r.json()),fetch(hep).then(r=>r.json())]).then(([rec,dd])=>{
    window._currentHeaders=dd.headers;window._currentTable=prev.table;
    renderDetailModal(rec,dd.headers,prev.table);
  });
}

// ---- ACTIONS ----
function songActions(rec,headers){
  let b='';
  const disco=fv(rec,headers,'disco'),db=fv(rec,headers,'dropbox link');
  const songUrl=fv(rec,headers,'song url')||fv(rec,headers,'spotify url');
  const pubSplit=fvExact(rec,headers,'pub credit')||fv(rec,headers,'pub credit');
  const labelCopy=fvExact(rec,headers,'label copy')||fv(rec,headers,'label copy');
  const masterSplit=fvExact(rec,headers,'master splits')||fv(rec,headers,'master split');
  const admin=fv(rec,headers,'song admin');
  // Quick copy buttons with icons
  if(disco)b+=`<button class="btn btn-sm" onclick="copyText('${escA(disco)}')" title="Copy DISCO link to clipboard">📋 DISCO</button>`;
  if(db){
    b+=`<button class="btn btn-sm" onclick="copyText('${escA(db)}')" title="Copy Dropbox link to clipboard">📋 Dropbox</button>`;
    const directUrl=db.replace('dl=0','dl=1').includes('dl=1')?db.replace('dl=0','dl=1'):db+(db.includes('?')?'&':'?')+'dl=1';
    b+=`<button class="btn btn-sm" onclick="playAudioPreview('${escA(directUrl)}',this)" title="Play audio preview">▶ Play</button>`;
  }
  if(songUrl)b+=`<button class="btn btn-sm" onclick="window.open('${escA(songUrl)}','_blank')" title="Open song link">🔗 Song URL</button>`;
  b+=`<button class="btn btn-sm" onclick="copyLyrics(${rec._row_index})" title="Copy full lyrics text to clipboard">📋 Lyrics</button>`;
  b+=`<button class="btn btn-sm btn-accent" onclick="calcPubSplits(${rec._row_index})" title="Calculate publishing splits from songwriter credits">🧮 Calc. Pub</button>`;
  if(pubSplit)b+=`<button class="btn btn-sm" data-copy="${escA(pubSplit)}" onclick="copyText(this.dataset.copy)" title="Copy publishing split breakdown">📋 Pub Split</button>`;
  if(labelCopy)b+=`<button class="btn btn-sm" data-copy="${escA(labelCopy)}" onclick="copyText(this.dataset.copy)" title="Copy label copy text (for DSP metadata)">📋 Label Copy</button>`;
  if(masterSplit)b+=`<button class="btn btn-sm" data-copy="${escA(masterSplit)}" onclick="copyText(this.dataset.copy)" title="Copy master ownership split">📋 Master Split</button>`;
  // Admin at a glance
  if(admin){
    const items=admin.split('\n').filter(x=>x.trim());
    const done=items.filter(x=>x.startsWith('[x]')||x.startsWith('[X]')).length;
    const pct=items.length?Math.round((done/items.length)*100):0;
    const color=pct===100?'var(--success)':pct>50?'var(--accent)':'var(--danger)';
    b+=`<span class="admin-badge" style="color:${color}" title="Song Admin: ${done}/${items.length} tasks done">☑ ${done}/${items.length}</span>`;
  }
  b+=`<button class="btn btn-sm" onclick="exportSongMeta(${rec._row_index})" title="Copy full song metadata as formatted text">📄 Export</button>`;
  b+=`<button class="btn btn-sm" onclick="downloadLyricDoc(${rec._row_index})" title="Download formatted lyric doc PDF">📄 Lyric Doc</button>`;
  return b;
}
function downloadLyricDoc(ri){
  window.open('/api/songs/'+ri+'/lyric-doc','_blank');
}
function dirActions(rec,headers){
  let b='';const email=fv(rec,headers,'email'),ri=rec._row_index,name=fv(rec,headers,'name');
  const phone=fv(rec,headers,'phone'),linkedin=fv(rec,headers,'linkedin')||fv(rec,headers,'socials')||fv(rec,headers,'website');
  const field=fv(rec,headers,'field'),company=fv(rec,headers,'mgmt company')||fv(rec,headers,'record label')||fv(rec,headers,'publishing company');
  // Quick info badge
  if(field)b+=`<span class="admin-badge" title="Field: ${escA(field)}">${esc(field.split('|')[0].trim())}</span>`;
  if(email)b+=`<button class="btn btn-sm" onclick="copyText('${escA(email)}')" title="Copy email address to clipboard">📋 Email</button>`;
  if(phone)b+=`<button class="btn btn-sm" onclick="copyText('${escA(phone)}')" title="Copy phone number">📋 Phone</button>`;
  if(linkedin)b+=`<button class="btn btn-sm" onclick="window.open('${escA(linkedin)}','_blank')" title="Open LinkedIn or website">🔗 Profile</button>`;
  b+=`<button class="btn btn-sm" onclick="logOutreach(${ri})" title="Log today as last outreach date">📅 Log Outreach</button>`;
  b+=`<button class="btn btn-sm" onclick="viewPersonSongs('${escA(name)}')" title="View all songs this person is credited on">🎵 Songs</button>`;
  b+=`<button class="btn btn-sm" onclick="worksWithUI(${ri},'${escA(name)}')" title="See and edit who this person works with">🔗 Works With</button>`;
  b+=`<button class="btn btn-sm" onclick="relationshipsUI(${ri},'${escA(name)}')" title="Manage Manager / Agent / A&R / Publishing relationships">🕸️ Relationships</button>`;
  if(company)b+=`<button class="btn btn-sm" onclick="navToRecord('${escA(company)}')" title="Open company record">🏢 ${esc(company.split('|')[0].trim().substring(0,15))}</button>`;
  return b;
}
function fv(rec,headers,term){for(const h of headers){if(cleanH(h).toLowerCase().includes(term.toLowerCase()))return rec[h]||''}return ''}
function fvExact(rec,headers,term){for(const h of headers){if(cleanH(h).toLowerCase()===term.toLowerCase())return rec[h]||''}return ''}

function toggleHideEmpty(checked){
  localStorage.setItem('rollon_hide_empty',checked?'true':'false');
  const grid=document.querySelector('.detail-grid');
  if(grid){if(checked)grid.setAttribute('data-hide-empty','1');else grid.removeAttribute('data-hide-empty')}
  const pill=document.querySelector('.hide-empty-pill');
  if(pill){pill.textContent=checked?'Show All Fields':'Hide Empty';if(checked)pill.classList.add('active');else pill.classList.remove('active')}
}

let _audioPreview=null;
function playAudioPreview(url,btn){
  if(_audioPreview){_audioPreview.pause();_audioPreview=null;if(btn)btn.textContent='▶ Play';return}
  _audioPreview=new Audio(url);
  _audioPreview.volume=0.8;
  _audioPreview.play().catch(()=>{toast('Audio playback failed','error')});
  if(btn)btn.textContent='⏸ Pause';
  _audioPreview.addEventListener('ended',()=>{_audioPreview=null;if(btn)btn.textContent='▶ Play'});
}

function copyLyrics(ri){
  fetch('/api/songs/'+ri).then(r=>r.json()).then(rec=>{
    let lyrics='';
    for(const h of Object.keys(rec)){if(cleanH(h).toLowerCase()==='lyrics'){lyrics=rec[h]||'';break}}
    if(!lyrics){toast('No lyrics found','error');return}
    navigator.clipboard.writeText(lyrics).then(()=>toast('Lyrics copied!')).catch(()=>toast('Copy failed','error'));
  });
}

function exportSongMeta(ri){
  fetch('/api/songs/'+ri).then(r=>r.json()).then(rec=>{
    const get=(term)=>{for(const h of Object.keys(rec)){if(cleanH(h).toLowerCase().includes(term.toLowerCase()))return rec[h]||''}return ''};
    const lines=[];
    lines.push('SONG METADATA');
    lines.push('='.repeat(40));
    if(get('title'))lines.push('Title: '+get('title'));
    if(get('artist'))lines.push('Artist: '+get('artist'));
    if(get('producer'))lines.push('Producer: '+get('producer'));
    if(get('songwriter credit'))lines.push('Songwriters: '+get('songwriter credit'));
    if(get('isrc'))lines.push('ISRC: '+get('isrc'));
    if(get('release date'))lines.push('Release Date: '+get('release date'));
    if(get('audio status'))lines.push('Audio Status: '+get('audio status'));
    if(get('genre'))lines.push('Genre: '+get('genre'));
    if(get('duration'))lines.push('Duration: '+get('duration'));
    if(get('record label'))lines.push('Record Label: '+get('record label'));
    if(get('format'))lines.push('Format: '+get('format'));
    lines.push('');
    if(get('pub credit')){lines.push('PUBLISHING SPLITS');lines.push('-'.repeat(40));lines.push(get('pub credit'));lines.push('')}
    if(get('master split')){lines.push('MASTER SPLITS');lines.push('-'.repeat(40));lines.push(get('master split'));lines.push('')}
    if(get('label copy')){lines.push('LABEL COPY');lines.push('-'.repeat(40));lines.push(get('label copy'));lines.push('')}
    if(get('disco'))lines.push('DISCO: '+get('disco'));
    if(get('dropbox link'))lines.push('Dropbox: '+get('dropbox link'));
    if(get('song url')||get('spotify url'))lines.push('Song URL: '+(get('song url')||get('spotify url')));
    const text=lines.join('\n');
    navigator.clipboard.writeText(text).then(()=>toast('Song metadata copied to clipboard!')).catch(()=>toast('Copy failed','error'));
  });
}

// ---- CALCULATE PUBLISHING (FIXED: uses find approach) ----
function calcPubSplits(ri){
  const headers=window._currentHeaders||[];
  fetch(`/api/songs/${ri}`).then(r=>r.json()).then(rec=>{
    // Find songwriter credits by scanning headers
    let swVal='';
    for(const h of headers){if(cleanH(h).toLowerCase().includes('songwriter credit')){swVal=rec[h]||'';break}}
    // Fallback: try 'songwriter'
    if(!swVal){for(const h of headers){if(cleanH(h).toLowerCase().includes('songwriter')){swVal=rec[h]||'';break}}}
    const writers=splitP(swVal).filter(w=>w);
    if(!writers.length){toast('No songwriters found in Songwriter Credits field','error');return}
    // Find vocalist/artist for remainder
    let vocVal='';
    for(const h of headers){if(cleanH(h).toLowerCase()==='vocalist'){vocVal=rec[h]||'';break}}
    if(!vocVal){for(const h of headers){if(cleanH(h).toLowerCase()==='artist'){vocVal=rec[h]||'';break}}}
    const vocName=splitP(vocVal)[0]||'';
    const writerObjs=writers.map(w=>({name:w}));
    fetch('/api/splits/calculate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({writers:writerObjs,mode:'equal',vocalist:vocName})
    }).then(r=>r.json()).then(d=>{
      if(d.formatted){
        let pcH=null;
        for(const h of headers){if(cleanH(h).toLowerCase().includes('pub credit')){pcH=h;break}}
        if(pcH){
          fetch('/api/songs/update',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({field:pcH,row_index:ri,value:d.formatted})
          }).then(r=>r.json()).then(u=>{
            if(u.success){toast('Publishing: '+d.formatted);refreshDetail(ri,'songs')}
            else toast(u.error||'Failed','error');
          });
        } else toast('Pub Credit field not found','error');
      } else toast('Calculation failed','error');
    });
  });
}

// ---- INLINE EDITING ----
function startEdit(el){
  if(el.querySelector('.inline-edit')||el.querySelector('.typeahead-wrap'))return;
  const field=el.dataset.field,ri=parseInt(el.dataset.row),table=el.dataset.table,type=el.dataset.type;
  const currentVal=readData(el)||'';

  // Checklist has its own click handlers (checkboxes, +Add, Convert)
  // Don't replace content - let individual handlers work
  if(type==='checklist')return;

  if(type==='tag'){startPillEdit(el,field,ri,table,currentVal,'tag');return}
  if(type==='link'){
    // Special: city field uses city search
    if(cleanH(field).toLowerCase()==='city'){startCityEdit(el,field,ri,table,currentVal);return}
    startPillEdit(el,field,ri,table,currentVal,'link');return
  }
  if(type==='autocomplete'){startPillEdit(el,field,ri,table,currentVal,'auto');return}
  if(type==='field_type'){startPillEdit(el,field,ri,table,currentVal,'auto');return}

  // Long text fields open popup modal
  if(type==='long'){
    openLongTextPopup(field,currentVal,(newVal)=>{
      saveEdit(el,field,ri,table,newVal);
    });
    return;
  }

  if(type==='date'){
    el.innerHTML=`<input type="date" class="inline-edit">`;
    el.querySelector('.inline-edit').value=currentVal;
  } else if(type==='datetime'){
    el.innerHTML=`<input type="datetime-local" class="inline-edit">`;
    el.querySelector('.inline-edit').value=_dtToInput(currentVal)||_dtDefault();
  } else {
    el.innerHTML=`<input class="inline-edit">`;
    el.querySelector('.inline-edit').value=currentVal;
  }
  const inp=el.querySelector('.inline-edit');inp.focus();
  // URL prefill: if URL field is empty, seed with http://
  if(type==='url'&&!currentVal){inp.value='http://';inp.setSelectionRange(7,7)}
  inp.addEventListener('blur',()=>{let v=inp.value;if(type==='url'&&(v==='http://'||v==='https://'))v='';if(type==='datetime'&&v)v=v+':00';saveEdit(el,field,ri,table,v)});
  inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();inp.blur()}
    if(e.key==='Escape'){e.stopPropagation();refreshDetail(ri,table)}
  });
}

function saveEdit(el,field,ri,table,value,skipRefresh){
  const ep=table==='songs'?'/api/songs/update':'/api/directory/update';
  fetch(ep,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({field,row_index:ri,value})
  }).then(r=>r.json()).then(d=>{
    if(d.success){toast('Saved');
      if(d.automations?.length)d.automations.forEach(a=>toast(a));
      if(!skipRefresh)refreshDetail(ri,table,field);
    } else toast(d.error||'Save failed','error');
  }).catch(()=>toast('Network error','error'));
}

function refreshDetail(ri,table,scrollToField){
  const ep=table==='songs'?`/api/songs/${ri}`:`/api/directory/${ri}`;
  if(window._currentTable===table&&window._currentHeaders?.length>5){
    fetch(ep).then(r=>r.json()).then(rec=>{
      renderDetailModal(rec,window._currentHeaders,table);
      if(scrollToField)setTimeout(()=>{const el=document.querySelector(`.detail-value[data-field="${scrollToField}"]`);if(el)el.scrollIntoView({behavior:'smooth',block:'center'})},50);
    });
  } else {
    const hep=table==='songs'?'/api/songs?per_page=1':'/api/directory?per_page=1';
    Promise.all([fetch(ep).then(r=>r.json()),fetch(hep).then(r=>r.json())]).then(([rec,dd])=>{
      window._currentHeaders=dd.headers;window._currentTable=table;
      renderDetailModal(rec,dd.headers,table);
      if(scrollToField)setTimeout(()=>{const el=document.querySelector(`.detail-value[data-field="${scrollToField}"]`);if(el)el.scrollIntoView({behavior:'smooth',block:'center'})},50);
    });
  }
}

// ---- PILL EDITING (tags, links, autocomplete - all use same pattern) ----
function startPillEdit(el,field,ri,table,currentVal,mode){
  const items=splitP(currentVal);
  let html='<div class="tag-editor"><div class="existing-tags">';
  items.forEach(t=>{
    let pillClass='pill';let style='';
    if(mode==='tag'){pillClass='pill pill-tag';const ac='#d4a853';if(PILL_COLORED){const c=TAG_COLORS[t]||ac;style=`style="background:${c}20;color:${c};border:1px solid ${c}40"`}else{style=`style="background:${ac}20;color:${ac};border:1px solid ${ac}40"`}}
    else if(mode==='link')pillClass='pill pill-link';
    html+=`<span class="${pillClass}" ${style}>${esc(t)} <span class="pill-x" onclick="removePill(this,'${escA(field)}',${ri},'${table}','${escA(t)}')">&times;</span></span>`;
  });
  const searchMode=mode==='link'?'link':mode==='tag'?'tag':'auto';
  html+=`<span class="pill pill-add" onclick="showTypeahead(this.parentElement,'${escA(field)}',${ri},'${table}','${searchMode}')">+</span></div></div>`;
  el.innerHTML=html;
}

function removePill(xEl,field,ri,table,valToRemove){
  // Always fetch fresh value from API before modifying
  const ep=table==='songs'?`/api/songs/${ri}`:`/api/directory/${ri}`;
  fetch(ep).then(r=>r.json()).then(rec=>{
    const current=rec[field]||'';
    const remaining=splitP(current).filter(t=>t!==valToRemove);
    const dv=xEl.closest('.detail-value');
    saveEdit(dv,field,ri,table,remaining.join(' | '));
  });
}

// ---- CITY EDIT (uses /api/cities/search) ----
function startCityEdit(el,field,ri,table,currentVal){
  const items=splitP(currentVal);
  let html='<div class="tag-editor"><div class="existing-tags">';
  items.forEach(t=>{html+=`<span class="pill pill-link">${esc(t)} <span class="pill-x" onclick="removePill(this,'${escA(field)}',${ri},'${table}','${escA(t)}')">&times;</span></span>`});
  html+=`<span class="pill pill-add" onclick="showCityTypeahead(this.parentElement,'${escA(field)}',${ri},'${table}')">+</span></div></div>`;
  el.innerHTML=html;
}

function showCityTypeahead(container,field,ri,table){
  if(container.querySelector('.typeahead-wrap'))return;
  const wrap=document.createElement('div');wrap.className='typeahead-wrap';
  wrap.innerHTML='<input class="typeahead-input" placeholder="Search cities..."><div class="typeahead-dropdown" style="display:none"></div>';
  container.appendChild(wrap);
  const inp=wrap.querySelector('.typeahead-input'),dd=wrap.querySelector('.typeahead-dropdown');
  inp.focus();
  let deb;
  inp.addEventListener('input',()=>{clearTimeout(deb);deb=setTimeout(()=>{
    const q=inp.value.trim();if(q.length<1){dd.style.display='none';return}
    fetch(`/api/cities/search?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(d=>{
      const results=d.results||[];
      let html=results.map(r=>`<div class="typeahead-item" onclick="addPill('${escA(field)}',${ri},'${table}','${escA(r.name)}')">${esc(r.name)}${r.country?` <span class="table-hint">${esc(r.country)}</span>`:''}</div>`).join('');
      dd.innerHTML=html||'<div class="typeahead-item" style="color:var(--text-ghost)">No cities found</div>';
      dd.style.display='block';
    });
  },30)});
  inp.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();wrap.remove()}});
}

// ---- TYPEAHEAD ----
function showTypeahead(container,field,ri,table,mode){
  if(container.querySelector('.typeahead-wrap'))return;
  const wrap=document.createElement('div');wrap.className='typeahead-wrap';
  wrap.innerHTML='<input class="typeahead-input" placeholder="Search..."><div class="typeahead-dropdown" style="display:none"></div>';
  container.appendChild(wrap);
  const inp=wrap.querySelector('.typeahead-input'),dd=wrap.querySelector('.typeahead-dropdown');
  inp.focus();
  let deb;
  inp.addEventListener('input',()=>{clearTimeout(deb);deb=setTimeout(()=>{
    const q=inp.value.trim();if(q.length<1){dd.style.display='none';return}
    if(mode==='link'){
      fetch(`/api/search-record?q=${encodeURIComponent(q)}&table=${encodeURIComponent(getLinkTable(field))}`).then(r=>r.json()).then(d=>{
        let html=(d.results||[]).map(r=>`<div class="typeahead-item" onclick="addPill('${escA(field)}',${ri},'${table}','${escA(r.name)}')">${esc(r.name)}</div>`).join('');
        html+=`<div class="typeahead-item create" onclick="createAndLink('${escA(field)}',${ri},'${table}','${escA(inp.value)}')">+ Create "${esc(inp.value)}"</div>`;
        dd.innerHTML=html;dd.style.display='block';
      });
    } else {
      const tbl=table==='songs'?'songs':'directory';
      fetch(`/api/autocomplete/${tbl}/${encodeURIComponent(cleanH(field))}?q=${encodeURIComponent(q)}&limit=15`).then(r=>r.json()).then(d=>{
        let html=(d.values||[]).map(v=>`<div class="typeahead-item" onclick="addPill('${escA(field)}',${ri},'${table}','${escA(v)}')">${esc(v)}</div>`).join('');
        html+=`<div class="typeahead-item create" onclick="addPill('${escA(field)}',${ri},'${table}','${escA(inp.value)}')">+ Add "${esc(inp.value)}"</div>`;
        dd.innerHTML=html;dd.style.display='block';
      });
    }
  },30)});
  inp.addEventListener('keydown',e=>{
    const items=dd.querySelectorAll('.typeahead-item');
    let ai=[...items].findIndex(x=>x.classList.contains('ta-active'));
    if(e.key==='ArrowDown'){e.preventDefault();items.forEach(x=>x.classList.remove('ta-active'));ai=Math.min(ai+1,items.length-1);items[ai]?.classList.add('ta-active');items[ai]?.scrollIntoView({block:'nearest'})}
    else if(e.key==='ArrowUp'){e.preventDefault();items.forEach(x=>x.classList.remove('ta-active'));ai=Math.max(ai-1,0);items[ai]?.classList.add('ta-active');items[ai]?.scrollIntoView({block:'nearest'})}
    else if(e.key==='Enter'){e.preventDefault();const active=dd.querySelector('.ta-active');if(active){active.click()}else if(inp.value.trim()){addPill(field,ri,table,inp.value.trim());wrap.remove()}}
    else if(e.key==='Escape'){e.stopPropagation();wrap.remove()}
  });
}

function addPill(field,ri,table,val){
  // ALWAYS fetch current from API, then append
  const ep=table==='songs'?`/api/songs/${ri}`:`/api/directory/${ri}`;
  fetch(ep).then(r=>r.json()).then(rec=>{
    const current=rec[field]||'';
    const existing=splitP(current);
    if(!existing.includes(val))existing.push(val);
    const dv=document.querySelector(`.detail-value[data-field="${field}"][data-row="${ri}"]`);
    if(dv)saveEdit(dv,field,ri,table,existing.join(' | '));
  });
}

function createAndLink(field,ri,table,name){
  fetch('/api/directory/new',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({Name:name})}).then(r=>r.json()).then(d=>{
    if(d.success){toast('Created '+name);addPill(field,ri,table,name)}
    else toast(d.error||'Failed','error');
  });
}

// ---- WORKS WITH (v36: typeahead + chips, bidirectional engine) ----
// Flow: open a modal for contact ri/masterName. Fetch their existing Works With
// via /api/relationships/works-with/<airtable_id>, render chips. Show a
// typeahead input. Pick a match -> call /add. Click chip X -> call /remove.
function worksWithUI(ri,masterName){
  fetch('/api/directory/'+ri).then(r=>r.json()).then(rec=>{
    let airtableId='';
    for(const h of Object.keys(rec)){
      if(cleanH(h).toLowerCase()==='airtable id'){airtableId=(rec[h]||'').trim();break}
    }
    if(!airtableId){toast('This contact has no Airtable ID - cannot link','error');return}
    _openWorksWithModal(ri,airtableId,masterName);
  });
}

function _openWorksWithModal(masterRowIndex,masterId,masterName){
  let modal=document.getElementById('ww-modal');
  if(modal)modal.remove();
  modal=document.createElement('div');
  modal.id='ww-modal';
  modal.className='modal';
  modal.style.display='flex';
  modal.innerHTML=`
    <div class="modal-content" style="max-width:560px">
      <div class="modal-header">
        <div class="modal-title">Works With: ${esc(masterName)}</div>
        <span class="modal-close" onclick="document.getElementById('ww-modal').remove()">&times;</span>
      </div>
      <div class="modal-body">
        <div style="font-size:11px;color:var(--text-ghost);margin-bottom:10px">
          Linked contacts share one pitch email. Bidirectional - adding here updates the other side too.
        </div>
        <div id="ww-chips" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;min-height:24px"></div>
        <input id="ww-input" class="typeahead-input" placeholder="Type a name to link..." autocomplete="off" style="width:100%">
        <div id="ww-dropdown" class="typeahead-dropdown" style="display:none;position:relative;margin-top:4px"></div>
        <div id="ww-greeting" style="margin-top:14px;padding:10px;background:var(--panel);border-radius:6px;font-size:12px;display:none"></div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.dataset.masterId=masterId;
  modal.dataset.masterRi=masterRowIndex;
  const inp=document.getElementById('ww-input');
  const dd=document.getElementById('ww-dropdown');
  let t=null;
  inp.addEventListener('input',()=>{
    clearTimeout(t);
    const q=inp.value.trim();
    if(q.length<2){dd.style.display='none';return}
    t=setTimeout(()=>{
      fetch('/api/relationships/search',{method:'POST',headers:_jsonHeaders(),body:JSON.stringify({q,exclude_id:masterId})})
      .then(r=>r.json()).then(d=>{
        const res=d.results||[];
        if(!res.length){dd.innerHTML='<div class="typeahead-item" style="color:var(--text-ghost)">No matches</div>';dd.style.display='block';return}
        dd.innerHTML=res.map(r=>
          `<div class="typeahead-item" onclick="_wwAddLink('${escA(r.id)}','${escA(r.name)}')">${esc(r.name)}`+
          (r.company?` <span class="table-hint" style="color:var(--text-ghost)">${esc(r.company)}</span>`:'')+
          (r.field?` <span class="table-hint" style="color:var(--text-ghost);margin-left:8px">${esc(r.field)}</span>`:'')+
          `</div>`
        ).join('');
        dd.style.display='block';
      });
    },200);
  });
  _wwRenderChips();
}

function _jsonHeaders(){
  const h={'Content-Type':'application/json'};
  const t=document.cookie.split(';').map(c=>c.trim()).find(c=>c.startsWith('csrf_token='));
  const csrfMeta=document.querySelector('meta[name="csrf-token"]');
  if(csrfMeta)h['X-CSRF-Token']=csrfMeta.content;
  return h;
}

function _wwRenderChips(){
  const modal=document.getElementById('ww-modal');
  if(!modal)return;
  const masterId=modal.dataset.masterId;
  fetch('/api/relationships/works-with/'+encodeURIComponent(masterId))
    .then(r=>r.json()).then(d=>{
      const chipsBox=document.getElementById('ww-chips');
      const links=d.links||[];
      if(!links.length){chipsBox.innerHTML='<span style="color:var(--text-ghost);font-size:11px">No links yet.</span>'}
      else{
        chipsBox.innerHTML=links.map(l=>
          `<span class="pill" style="background:#1d4ed8;color:#fff;padding:4px 8px;border-radius:12px;font-size:11px;display:inline-flex;align-items:center;gap:6px">
            ${esc(l.name||l.id)}
            <span style="cursor:pointer;font-weight:bold" onclick="_wwRemoveLink('${escA(l.id)}')" title="Remove link">&times;</span>
           </span>`
        ).join('');
      }
      // preview greeting
      const ids=[masterId].concat(links.map(l=>l.id));
      fetch('/api/relationships/greeting',{method:'POST',headers:_jsonHeaders(),body:JSON.stringify({ids})})
        .then(r=>r.json()).then(g=>{
          const box=document.getElementById('ww-greeting');
          if(!box)return;
          if(!g||!g.named){box.style.display='none';return}
          box.style.display='block';
          box.innerHTML=`<div><strong>Named greeting:</strong> ${esc(g.named)}</div>`+
            (g.alt!==g.named?`<div style="margin-top:4px;color:var(--text-ghost)"><strong>Alt:</strong> ${esc(g.alt)}</div>`:'');
        });
    });
}

function _wwAddLink(toId,toName){
  const modal=document.getElementById('ww-modal');
  if(!modal)return;
  const masterId=modal.dataset.masterId;
  fetch('/api/relationships/works-with/add',{method:'POST',headers:_jsonHeaders(),
    body:JSON.stringify({from_id:masterId,to_id:toId})})
  .then(r=>r.json()).then(d=>{
    if(d.error){toast(d.error,'error');return}
    toast('Linked '+toName);
    document.getElementById('ww-input').value='';
    document.getElementById('ww-dropdown').style.display='none';
    _wwRenderChips();
    const masterRi=modal.dataset.masterRi;
    if(masterRi)refreshDetail(parseInt(masterRi,10),'directory');
    openGroupLeaderPicker(masterId);
  });
}

// Leader-picker (v36 Phase 6.5): after linking two contacts, prompt the
// Captain to pick which one receives mass pitches. The non-leaders get
// the "Don't Mass Pitch" tag appended (idempotent on the server).
function openGroupLeaderPicker(anyMemberId){
  fetch('/api/relationships/group-leader/'+encodeURIComponent(anyMemberId)).then(r=>r.json()).then(d=>{
    const groupIds=(d&&d.group_ids)||[];
    if(groupIds.length<2)return; // solo, nothing to pick
    const currentLeader=d.leader||'';
    // Fetch each member's name for the picker
    Promise.all(groupIds.map(gid=>fetch('/api/relationships/works-with/'+encodeURIComponent(gid)).then(r=>r.json()).then(rec=>{
      // Fall back: need a display name. Use search-by-id through a quick lookup.
      return fetch('/api/relationships/search',{method:'POST',headers:_jsonHeaders(),body:JSON.stringify({q:gid.substring(3,6)})}).then(r=>r.json()).then(s=>{
        const match=(s.results||[]).find(x=>x.id===gid);
        return {id:gid,name:match?match.name:gid};
      });
    }))).then(members=>{
      _renderLeaderPickerModal(groupIds,members,currentLeader);
    }).catch(()=>{
      _renderLeaderPickerModal(groupIds,groupIds.map(id=>({id,name:id})),currentLeader);
    });
  });
}

function _renderLeaderPickerModal(groupIds,members,currentLeader){
  // Remove any prior modal
  document.getElementById('leader-picker-modal')?.remove();
  const picked=currentLeader||(members[0]&&members[0].id)||'';
  const rows=members.map(m=>(
    `<label style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:6px;cursor:pointer;${m.id===picked?'background:rgba(212,168,83,0.12);border:1px solid rgba(212,168,83,0.4)':'border:1px solid var(--border,#2a2a30)'}">
      <input type="radio" name="group-leader-choice" value="${escA(m.id)}" ${m.id===picked?'checked':''}>
      <span style="flex:1;color:var(--text,#eaeaea)">${esc(m.name||m.id)}</span>
      <span style="font-size:10px;color:var(--text-ghost)">${esc(m.id.substring(0,10))}...</span>
    </label>`
  )).join('');
  const wrap=document.createElement('div');
  wrap.id='leader-picker-modal';wrap.className='modal-overlay';wrap.style.display='flex';
  wrap.innerHTML=`<div class="modal-content" style="max-width:480px">
    <div class="modal-header"><h2>Pick Group Leader</h2><button class="modal-close" onclick="document.getElementById('leader-picker-modal').remove()">&times;</button></div>
    <div class="modal-body">
      <p style="color:var(--text-ghost);font-size:12px;margin:0 0 12px">These ${groupIds.length} contacts are now linked. Pick the Leader (the one who receives mass pitches). The others will be auto-tagged <span style="color:#dc2626">Don't Mass Pitch</span> so bulk exports skip them.</p>
      <div style="display:flex;flex-direction:column;gap:6px">${rows}</div>
      <label style="display:flex;align-items:center;gap:8px;margin-top:14px;font-size:12px;color:var(--text-dim)">
        <input type="checkbox" id="lp-auto-tag" checked>
        Tag secondaries with Don't Mass Pitch
      </label>
      <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end">
        <button class="btn" onclick="document.getElementById('leader-picker-modal').remove()">Skip</button>
        <button class="btn btn-accent" onclick="_saveLeaderPick(${JSON.stringify(groupIds).replace(/"/g,'&quot;')})">Save Leader</button>
      </div>
    </div></div>`;
  document.body.appendChild(wrap);
}

function _saveLeaderPick(groupIds){
  const picked=document.querySelector('input[name="group-leader-choice"]:checked');
  if(!picked){toast('Pick a leader first','error');return}
  const auto=document.getElementById('lp-auto-tag').checked;
  fetch('/api/relationships/group-leader',{method:'POST',headers:_jsonHeaders(),
    body:JSON.stringify({group_ids:groupIds,leader_id:picked.value,auto_tag_secondaries:auto})})
  .then(r=>r.json()).then(d=>{
    if(d.error){toast(d.error,'error');return}
    toast('Leader set'+(d.tagged&&d.tagged.length?` (tagged ${d.tagged.length})`:''));
    document.getElementById('leader-picker-modal')?.remove();
    // Refresh master detail so the new star icon lands in the grid
    const wwModal=document.getElementById('ww-modal');
    const masterRi=wwModal&&wwModal.dataset.masterRi;
    if(masterRi)refreshDetail(parseInt(masterRi,10),'directory');
    if(typeof D!=='undefined'&&D.reload)D.reload();
  });
}

function _wwRemoveLink(toId){
  const modal=document.getElementById('ww-modal');
  if(!modal)return;
  const masterId=modal.dataset.masterId;
  fetch('/api/relationships/works-with/remove',{method:'POST',headers:_jsonHeaders(),
    body:JSON.stringify({from_id:masterId,to_id:toId})})
  .then(r=>r.json()).then(d=>{
    if(d.error){toast(d.error,'error');return}
    toast('Unlinked');
    _wwRenderChips();
    const masterRi=modal.dataset.masterRi;
    if(masterRi)refreshDetail(parseInt(masterRi,10),'directory');
  });
}

// ---- RELATIONSHIPS (v36: Manager / Agent / A&R / Publishing linked-record UI) ----
function relationshipsUI(ri,masterName){
  fetch('/api/directory/'+ri).then(r=>r.json()).then(rec=>{
    let airtableId='';
    for(const h of Object.keys(rec)){
      if(cleanH(h).toLowerCase()==='airtable id'){airtableId=(rec[h]||'').trim();break}
    }
    if(!airtableId){toast('Contact has no Airtable ID','error');return}
    Promise.all([
      fetch('/api/relationships/types').then(r=>r.json()),
      fetch('/api/relationships/lookup/'+encodeURIComponent(airtableId)).then(r=>r.json()),
    ]).then(([t,l])=>_openRelModal(ri,airtableId,masterName,t.types||[],l||{}));
  });
}

function _openRelModal(masterRi,masterId,masterName,types,linksByType){
  let modal=document.getElementById('rel-modal');
  if(modal)modal.remove();
  modal=document.createElement('div');
  modal.id='rel-modal';
  modal.className='modal';
  modal.style.display='flex';
  const labelFor=(k)=>({
    manages:'Manages (Artists)',
    managed_by:'Managed By (Rep)',
    represents:'Represents (Artists)',
    represented_by:'Agent',
    ar_rep:"A&R's Artists",
    is_ar_for:'Record Label A&R',
    publishing_rep:"Publishing Rep's Artists",
    is_publishing_rep_for:'Publishing Rep',
    creative_of:'Creatives',
    works_with_creative:'Creative Works For',
  })[k]||k;
  let html=`
    <div class="modal-content" style="max-width:640px">
      <div class="modal-header">
        <div class="modal-title">Relationships: ${esc(masterName)}</div>
        <span class="modal-close" onclick="document.getElementById('rel-modal').remove()">&times;</span>
      </div>
      <div class="modal-body">
        <div style="font-size:11px;color:var(--text-ghost);margin-bottom:12px">
          Linked records are bidirectional. Adding "Manages" writes "Managed By" on the other side.
        </div>`;
  for(const t of types){
    const links=linksByType[t.key]||[];
    html+=`<div class="rel-block" data-link-type="${escA(t.key)}" style="margin-bottom:14px;padding:10px;background:var(--bg-surface);border-radius:6px">
      <div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:6px">${esc(labelFor(t.key))}</div>
      <div class="rel-chips" style="display:flex;flex-wrap:wrap;gap:6px;min-height:22px;margin-bottom:6px">${
        links.length?links.map(l=>
          `<span class="pill" style="background:#374151;color:#fff;padding:3px 8px;border-radius:12px;font-size:11px;display:inline-flex;gap:6px;align-items:center">
            ${esc(l.name||l.id)}
            <span style="cursor:pointer;font-weight:bold" onclick="_relRemoveLink('${escA(t.key)}','${escA(l.id)}')" title="Remove">&times;</span>
          </span>`
        ).join(''):'<span style="color:var(--text-ghost);font-size:11px">No links.</span>'
      }</div>
      <input class="rel-input" data-link-type="${escA(t.key)}" class="typeahead-input" placeholder="Type a name to link..." autocomplete="off" style="width:100%;font-size:11px">
      <div class="rel-dropdown" style="display:none;background:var(--bg-raised);border:1px solid var(--border);border-radius:6px;margin-top:4px;max-height:160px;overflow-y:auto"></div>
    </div>`;
  }
  html+='</div></div>';
  modal.innerHTML=html;
  document.body.appendChild(modal);
  modal.dataset.masterId=masterId;
  modal.dataset.masterRi=masterRi;
  modal.querySelectorAll('.rel-input').forEach(inp=>{
    const lt=inp.dataset.linkType;
    const dd=inp.parentElement.querySelector('.rel-dropdown');
    let t=null;
    inp.addEventListener('input',()=>{
      clearTimeout(t);
      const q=inp.value.trim();
      if(q.length<2){dd.style.display='none';return}
      t=setTimeout(()=>{
        fetch('/api/relationships/search',{method:'POST',headers:_jsonHeaders(),
          body:JSON.stringify({q,exclude_id:masterId})})
        .then(r=>r.json()).then(d=>{
          const res=d.results||[];
          dd.innerHTML=res.length?res.map(r=>
            `<div class="typeahead-item" style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--border)" onclick="_relAddLink('${escA(lt)}','${escA(r.id)}','${escA(r.name)}')">${esc(r.name)}${r.company?` <span style="color:var(--text-ghost);font-size:10px">${esc(r.company)}</span>`:''}</div>`
          ).join(''):'<div style="padding:6px 10px;color:var(--text-ghost);font-size:11px">No matches</div>';
          dd.style.display='block';
        });
      },200);
    });
  });
}

function _relAddLink(linkType,toId,toName){
  const modal=document.getElementById('rel-modal');
  if(!modal)return;
  const masterId=modal.dataset.masterId;
  fetch('/api/relationships/generic-add',{method:'POST',headers:_jsonHeaders(),
    body:JSON.stringify({from_id:masterId,to_id:toId,link_type:linkType})})
  .then(r=>r.json()).then(d=>{
    if(d.error){toast(d.error,'error');return}
    toast('Linked '+toName);
    const masterRi=parseInt(modal.dataset.masterRi,10);
    const name=modal.querySelector('.modal-title').textContent.replace('Relationships: ','');
    modal.remove();
    relationshipsUI(masterRi,name);
  });
}

function _relRemoveLink(linkType,toId){
  const modal=document.getElementById('rel-modal');
  if(!modal)return;
  const masterId=modal.dataset.masterId;
  fetch('/api/relationships/generic-remove',{method:'POST',headers:_jsonHeaders(),
    body:JSON.stringify({from_id:masterId,to_id:toId,link_type:linkType})})
  .then(r=>r.json()).then(d=>{
    if(d.error){toast(d.error,'error');return}
    toast('Unlinked');
    const masterRi=parseInt(modal.dataset.masterRi,10);
    const name=modal.querySelector('.modal-title').textContent.replace('Relationships: ','');
    modal.remove();
    relationshipsUI(masterRi,name);
  });
}

// ---- NAVIGATION ----
function navToRecord(name){
  // FAST PATH: use pre-built name cache (single API call, no search)
  fetch(`/api/quick-lookup?name=${encodeURIComponent(name)}`).then(r=>{
    if(!r.ok)throw new Error('not found');return r.json()
  }).then(entry=>{
    if(entry.route==='songs'){
      pushNav(entry.row_index,'songs');
      fetch(`/api/songs/${entry.row_index}`).then(r=>r.json()).then(rec=>{
        if(window._currentHeaders?.length>5&&window._currentTable==='songs'){
          renderDetailModal(rec,window._currentHeaders,'songs');
        } else {
          fetch('/api/songs?per_page=1').then(r=>r.json()).then(dd=>{
            window._currentHeaders=dd.headers;window._currentTable='songs';
            renderDetailModal(rec,dd.headers,'songs');
          });
        }
      });
    } else if(entry.route==='directory'){
      pushNav(entry.row_index,'directory');
      fetch(`/api/directory/${entry.row_index}`).then(r=>r.json()).then(rec=>{
        if(window._currentHeaders?.length>5&&window._currentTable==='directory'){
          renderDetailModal(rec,window._currentHeaders,'directory');
        } else {
          fetch('/api/directory?per_page=1').then(r=>r.json()).then(dd=>{
            window._currentHeaders=dd.headers;window._currentTable='directory';
            renderDetailModal(rec,dd.headers,'directory');
          });
        }
      });
    } else {
      // Peek modal for supporting tables
      fetch(`/api/table-record/${encodeURIComponent(entry.table)}/${entry.row_index}`).then(r=>r.json()).then(rec=>{
        if(rec.error){toast(rec.error,'error');return}
        showPeekModal(entry.table,entry.name,rec);
      });
    }
  }).catch(()=>{
    // SLOW FALLBACK: full search (only if cache misses)
    fetch(`/api/search-record?q=${encodeURIComponent(name)}`).then(r=>r.json()).then(d=>{
      const results=d.results||[];
      const exact=results.find(r=>r.name.toLowerCase()===name.toLowerCase()&&r.table==='Personnel')
        ||results.find(r=>r.name.toLowerCase()===name.toLowerCase())
        ||results.find(r=>r.table==='Personnel')
        ||results[0];
      if(!exact){toast('Not found: '+name,'error');return}
      const isSong=exact.route==='songs';
      const isDir=exact.route==='directory';
      if(isSong||isDir){
        const tbl=isSong?'songs':'directory';
        pushNav(exact.row_index,tbl);
        fetch(isSong?`/api/songs/${exact.row_index}`:`/api/directory/${exact.row_index}`).then(r=>r.json()).then(rec=>{
          if(window._currentHeaders?.length>5){renderDetailModal(rec,window._currentHeaders,tbl)}
          else{fetch(`/api/${tbl}?per_page=1`).then(r=>r.json()).then(dd=>{window._currentHeaders=dd.headers;renderDetailModal(rec,dd.headers,tbl)})}
        });
      } else {
        fetch(`/api/table-record/${encodeURIComponent(exact.table)}/${exact.row_index}`).then(r=>r.json()).then(rec=>{
          if(rec.error){toast(rec.error,'error');return}
          showPeekModal(exact.table,exact.name,rec);
        });
      }
    });
  });
}

function showPeekModal(tableName,title,rec){
  const modal=document.getElementById('detail-modal');
  const mTitle=document.getElementById('modal-title');
  const mBody=document.getElementById('modal-body');
  mTitle.textContent=title;
  let html=`<div style="font-size:11px;color:var(--text-ghost);margin-bottom:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px">${tableName}</div>`;
  html+='<div class="detail-grid">';
  for(const [key,val] of Object.entries(rec)){
    if(key.startsWith('_'))continue;
    const ch=cleanH(key);if(!ch)continue;
    const v=String(val||'').trim();if(!v)continue;
    html+=`<div class="detail-label">${esc(ch)}</div>`;
    // Render linked pills for pipe-separated values
    if(v.includes(' | ')){
      html+=`<div class="detail-value">${splitP(v).map(t=>`<span class="pill pill-link" onclick="event.stopPropagation();navToRecord('${escA(t)}')" style="cursor:pointer">${esc(t)}</span>`).join(' ')}</div>`;
    } else if(v.startsWith('http')){
      html+=`<div class="detail-value"><a href="${escA(v)}" target="_blank" style="color:var(--accent)">${esc(v.substring(0,60))}</a></div>`;
    } else {
      html+=`<div class="detail-value">${esc(v)}</div>`;
    }
  }
  html+='</div>';
  mBody.innerHTML=html;
  modal.style.display='flex';
}

function logOutreach(ri){
  const today=new Date().toISOString().split('T')[0];
  const headers=window._currentHeaders||[];
  const rawField=headers.find(h=>cleanH(h).toLowerCase().includes('last outreach'))||'Last Outreach';
  fetch('/api/directory/update',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({field:rawField,row_index:ri,value:today})
  }).then(r=>r.json()).then(d=>{if(d.success){toast('Logged: '+today);refreshDetail(ri,'directory')}else toast(d.error,'error')});
}
function viewPersonSongs(name){closeModal();window.location.href=`/songs?search=${encodeURIComponent(name)}`}

// ---- SEARCH AUTOSUGGEST ----
function setupSearchAutosuggest(inputId,table){
  const inp=document.getElementById(inputId);if(!inp)return;
  const wrap=inp.parentElement;wrap.style.position='relative';
  let dd=wrap.querySelector('.search-dropdown');
  if(!dd){dd=document.createElement('div');dd.className='search-dropdown';dd.style.display='none';wrap.appendChild(dd)}
  let deb;
  inp.addEventListener('input',()=>{clearTimeout(deb);deb=setTimeout(()=>{
    const q=inp.value.trim();if(q.length<1){dd.style.display='none';return}
    const ep=table==='songs'?'songs':'directory';
    fetch(`/api/search-record?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(d=>{
      const results=(d.results||[]).filter(r=>table==='songs'?r.route==='songs':r.table==='Personnel');
      if(!results.length){dd.style.display='none';return}
      dd.innerHTML='';
      results.slice(0,8).forEach(r=>{
        const item=document.createElement('div');
        item.className='typeahead-item';
        item.textContent=r.name;
        item.addEventListener('click',()=>{inp.value=r.name;inp.dispatchEvent(new Event('input'));dd.style.display='none'});
        dd.appendChild(item);
      });
      dd.style.display='block';
    });
  },200)});
}

// ---- GLOBAL SEARCH (v36 Phase 6.5) ----
// Topbar search: dropdown of cross-table results via /api/global-search,
// Cmd+K (or Ctrl+K) focuses the input from any page, Esc clears/closes.
(function(){
  const gs=document.getElementById('global-search');
  if(!gs)return;
  const wrap=gs.parentElement||gs;
  wrap.style.position='relative';
  let dd=document.createElement('div');
  dd.className='global-search-dropdown';
  dd.style.cssText='position:absolute;top:100%;right:0;min-width:320px;max-height:380px;overflow-y:auto;background:var(--bg-elev,#1b1b1f);border:1px solid var(--border,#2a2a30);border-radius:8px;margin-top:4px;box-shadow:0 6px 24px rgba(0,0,0,.45);display:none;z-index:1000';
  wrap.appendChild(dd);
  let active=-1,results=[],deb;
  function close(){dd.style.display='none';active=-1}
  function openRes(r){
    close();gs.value='';
    if(r.route==='directory'){window.location.href='/directory?open='+r.row_index}
    else if(r.route==='songs'){window.location.href='/songs?open='+r.row_index}
    else{openTableRecord(r.table,r.row_index)}
  }
  function render(){
    if(!results.length){dd.innerHTML='<div style="padding:10px 12px;color:var(--text-ghost);font-size:12px">No matches.</div>';dd.style.display='block';return}
    dd.innerHTML=results.slice(0,12).map((r,i)=>{
      const subtitle=r.subtitle||r.table||'';
      return `<div class="gs-item" data-idx="${i}" style="padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border,#2a2a30);${i===active?'background:var(--accent-20,#d4a85322)':''}">
        <div style="color:var(--text,#eaeaea);font-size:13px">${esc(r.name)}</div>
        <div style="color:var(--text-ghost);font-size:11px;margin-top:2px">${esc(subtitle)}</div>
      </div>`;
    }).join('');
    dd.querySelectorAll('.gs-item').forEach(it=>{
      it.addEventListener('mousedown',e=>{e.preventDefault();openRes(results[parseInt(it.dataset.idx,10)])});
    });
    dd.style.display='block';
  }
  gs.addEventListener('input',()=>{
    clearTimeout(deb);
    const q=gs.value.trim();
    if(q.length<1){close();return}
    deb=setTimeout(()=>{
      fetch('/api/global-search?q='+encodeURIComponent(q)).then(r=>r.json()).then(d=>{
        results=d.results||[];active=results.length?0:-1;render();
      }).catch(()=>{close()});
    },180);
  });
  gs.addEventListener('keydown',e=>{
    if(dd.style.display!=='block'){
      if(e.key==='Escape'){gs.blur();return}
      return;
    }
    if(e.key==='ArrowDown'){e.preventDefault();active=Math.min(active+1,results.length-1);render()}
    else if(e.key==='ArrowUp'){e.preventDefault();active=Math.max(active-1,0);render()}
    else if(e.key==='Enter'){e.preventDefault();if(active>=0&&results[active])openRes(results[active])}
    else if(e.key==='Escape'){e.preventDefault();close();gs.value=''}
  });
  document.addEventListener('click',e=>{if(!wrap.contains(e.target))close()});
  // Cmd+K / Ctrl+K focuses the global search from anywhere.
  document.addEventListener('keydown',e=>{
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){
      e.preventDefault();gs.focus();gs.select();
    }
  });
})();

function openTableRecord(table,rowIndex){
  fetch('/api/table-record/'+encodeURIComponent(table)+'/'+rowIndex).then(r=>r.json()).then(rec=>{
    if(rec.error){toast(rec.error,'error');return}
    const title=rec.Name||rec.Title||table+' record';
    const bodyEl=document.getElementById('modal-body');const titleEl=document.getElementById('modal-title');
    if(titleEl)titleEl.textContent=title;
    if(bodyEl){
      const rows=Object.keys(rec).filter(k=>!k.startsWith('_')).map(k=>{
        const v=rec[k]; if(v===''||v==null)return '';
        return `<div style="display:grid;grid-template-columns:160px 1fr;gap:8px;padding:6px 0;border-bottom:1px solid var(--border,#2a2a30)"><div style="color:var(--text-ghost);font-size:11px">${esc(k)}</div><div style="font-size:12px">${esc(String(v))}</div></div>`;
      }).join('');
      bodyEl.innerHTML=`<div style="font-size:11px;color:var(--text-ghost);margin-bottom:8px">${esc(table)} · row ${rowIndex}</div>${rows}`;
    }
    document.getElementById('detail-modal').style.display='flex';
  });
}

// ---- UTILITIES ----
function splitP(v){if(!v)return [];return String(v).split(/\s*\|\s*/).map(p=>p.trim()).filter(p=>p&&p!=='undefined'&&p!=='null')}
function esc(s){const el=document.createElement('span');el.textContent=s||'';return el.innerHTML}
function escA(s){return (s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;').replace(/\n/g,'\\n').replace(/\r/g,'')}
// Safe encoding for HTML data attributes (no backslash corruption)
function escData(s){return encodeURIComponent(s||'')}
function readData(el){return decodeURIComponent(el.dataset.current||'')}
function copyText(text){const ct=text.includes(' | ')?text.split(' | ').join(', '):text;navigator.clipboard.writeText(ct).then(()=>toast('Copied!')).catch(()=>{const ta=document.createElement('textarea');ta.value=ct;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);toast('Copied!')})}
function togglePillColors(){PILL_COLORED=!PILL_COLORED;localStorage.setItem('pill_colored',PILL_COLORED);toast(PILL_COLORED?'Pill colors ON':'Pill colors OFF');if(typeof reload==='function')reload()}

// ==================== PAGE CACHE ====================
const _cache={records:new Map(),table:null};
function cacheStore(records,table){_cache.records.clear();_cache.table=table;records.forEach(rec=>{if(rec._row_index)_cache.records.set(rec._row_index,{...rec})})}
function cacheGet(ri){return _cache.records.get(ri)||null}
function cacheUpdate(ri,field,value){const rec=_cache.records.get(ri);if(rec){rec[field]=value;_cache.records.set(ri,rec)}}

// v36 Phase 6.5: a row is a "Group Leader" when its Group Leader column
// value equals its own Airtable ID. Renders a gold star next to Name.
function _isGroupLeader(rec){
  if(!rec)return false;
  let airtableId='',groupLeader='';
  for(const k of Object.keys(rec)){
    const kc=cleanH(k).toLowerCase();
    if(kc==='airtable id')airtableId=String(rec[k]||'').trim();
    else if(kc==='group leader')groupLeader=String(rec[k]||'').trim();
  }
  return airtableId&&groupLeader&&airtableId===groupLeader;
}

// ==================== GRID BUILDER (V2 with inline edit + header dropdowns) ====================
const _ED_TYPES=['tag','link','autocomplete','field_type','text','date','datetime','contact','url','long','duration','number','currency','percent','rating'];
function buildGridV2(cid,headers,records,table,visCols,sortField,sortDir,onSort,selRows){
  const c=document.getElementById(cid);if(!c)return;cacheStore(records,table);
  const shown=visCols||headers.map(h=>cleanH(h));
  // Build indices in visCols ORDER (not sheet order) so column reorder works
  const indices=[];shown.forEach(vc=>{const idx=headers.findIndex(h=>cleanH(h)===vc);if(idx>=0)indices.push(idx)});
  const sel=selRows||new Set();
  let html='<table class="data-grid"><thead><tr><th class="check-col"><input type="checkbox" class="row-check" onchange="toggleAllRows(this)"></th><th class="expand-col"></th>';
  indices.forEach(i=>{const ch=cleanH(headers[i]),arrow=sortField===headers[i]?(sortDir==='asc'?' ▲':' ▼'):'';
    html+=`<th draggable="true" data-col-name="${esc(ch).replace(/"/g,'&quot;')}" onclick="if(typeof _dragHappened!=='undefined'&&_dragHappened)return;window._gridSort('${escA(headers[i])}')" oncontextmenu="showHeaderMenu(event,'${escA(headers[i])}','${table}')" ondragstart="colDragStart(event)" ondragover="colDragOver(event)" ondrop="colDrop(event)" ondragend="colDragEnd(event)"><span class="th-label">${esc(ch)}</span><span class="sort-arrow">${arrow}</span><span class="th-dropdown" onclick="event.stopPropagation();showHeaderMenu(event,'${escA(headers[i])}','${table}')">▾</span></th>`});
  html+=`<th class="add-col-th" onclick="addNewField('${table}')" title="Add field"><span class="add-col-icon">+</span></th>`;
  html+='</tr></thead><tbody>';
  records.forEach(rec=>{const ri=rec._row_index;
    // Conditional formatting: row class based on table context
    let rowClass='';
    if(table==='songs'){
      for(const h of headers){
        if(cleanH(h).toLowerCase()==='audio status'){
          const st=(rec[h]||'').toLowerCase();
          if(st.includes('released'))rowClass='row-released';
          else if(st.includes('mastered'))rowClass='row-mastered';
          else if(st.includes('mixed'))rowClass='row-mixed';
          else if(st.includes('production'))rowClass='row-production';
          else if(st.includes('demo'))rowClass='row-demo';
          break;
        }
      }
    } else if(table==='directory'){
      for(const h of headers){
        if(cleanH(h).toLowerCase()==='field'){
          const fv=(rec[h]||'').toLowerCase();
          if(fv.includes('a&r')||fv.includes('record'))rowClass='row-ar';
          else if(fv.includes('mgmt')||fv.includes('management'))rowClass='row-mgmt';
          else if(fv.includes('sync')||fv.includes('supervisor'))rowClass='row-sync';
          else if(fv.includes('publish'))rowClass='row-pub';
          else if(fv.includes('agent'))rowClass='row-agent';
          else if(fv.includes('artist'))rowClass='row-artist';
          break;
        }
      }
    } else if(table==='invoices'){
      for(const h of headers){
        if(cleanH(h).toLowerCase()==='status'){
          const sv=(rec[h]||'').toLowerCase();
          if(sv==='paid')rowClass='row-released';
          else if(sv==='sent')rowClass='row-mixed';
          else if(sv==='overdue')rowClass='row-demo';
          else if(sv==='draft')rowClass='row-production';
          break;
        }
      }
    }
    html+=`<tr data-ri="${ri}" class="${rowClass}"><td class="check-col"><input type="checkbox" class="row-check" ${sel.has(ri)?'checked':''} onchange="toggleRow(${ri},this.checked)" onclick="event.stopPropagation()"></td><td class="expand-col" onclick="openRecord(${ri},'${table}')" title="Open full record"><span class="expand-icon">↗</span></td>`;
    const isLeader=table==='directory'&&_isGroupLeader(rec);
    indices.forEach(i=>{const rawH=headers[i],type=fieldType(rawH),isEd=_ED_TYPES.includes(type);
      const cleanName=cleanH(rawH).toLowerCase();
      let cellHtml=renderCell(rawH,rec[rawH],ri,table);
      if(isLeader&&cleanName==='name'){
        cellHtml='<span class="leader-star" title="Group Leader — receives mass pitches for this group" style="color:#d4a853;margin-right:6px;font-size:13px">★</span>'+cellHtml;
      }
      html+=`<td data-field="${esc(rawH).replace(/"/g,'&quot;')}" data-ri="${ri}" class="${isEd?'cell-editable':''}" onclick="${isEd?`if(event.target.closest('.pill-link,.pill-x,.pill'))return;event.stopPropagation();cellSelect(this)`:`if(event.target.closest('.pill-link'))return;openRecord(${ri},'${table}')`}" ondblclick="${isEd?`event.stopPropagation();gridEdit(this,'${escA(rawH)}',${ri},'${table}')`:''}">${cellHtml}</td>`});
    html+='</tr>'});
  html+='</tbody></table>';c.innerHTML=html;window._gridSort=onSort||function(){};window._currentTable=table;
  // Apply freeze panes if set
  if(window._freezeCount)setTimeout(()=>applyFreezePanes(),50);
}

// Freeze panes - make first N columns sticky
window._freezeCount=parseInt(localStorage.getItem('rollon_freeze')||'0');
function applyFreezePanes(){
  const n=window._freezeCount||0;
  localStorage.setItem('rollon_freeze',n);
  const table=document.querySelector('.data-grid');if(!table)return;
  // Reset all sticky
  table.querySelectorAll('th,td').forEach(cell=>{
    cell.style.position='';cell.style.left='';cell.style.zIndex='';
    cell.style.background='';cell.classList.remove('freeze-border');
  });
  if(n<=0)return;
  // The first 2 columns are checkbox + expand, so freeze those + n data columns
  const freezeTotal=n+2;
  // Calculate column widths from header row first
  const headerRow=table.querySelector('thead tr');
  if(!headerRow)return;
  const headerCells=headerRow.querySelectorAll('th');
  const widths=[];let left=0;
  for(let i=0;i<Math.min(freezeTotal,headerCells.length);i++){
    widths.push(left);
    left+=headerCells[i].getBoundingClientRect().width;
  }
  // Apply sticky to all rows using pre-calculated widths
  table.querySelectorAll('tr').forEach(row=>{
    const cells=row.querySelectorAll('th,td');
    const isHead=!!row.closest('thead');
    for(let i=0;i<Math.min(freezeTotal,cells.length);i++){
      const cell=cells[i];
      cell.style.position='sticky';
      cell.style.left=(widths[i]||0)+'px';
      cell.style.zIndex=isHead?'12':'3';
      cell.style.background=isHead?'var(--bg-surface)':'var(--bg-raised)';
      if(i===freezeTotal-1)cell.classList.add('freeze-border');
    }
  });
}
// Alias so any old calls still work
function buildGrid(a,b,c,d,e,f,g,h,i){buildGridV2(a,b,c,d,e,f,g,h,i)}

// ==================== INLINE GRID EDITING ====================
function gridEdit(td,header,ri,table){
  if(td.querySelector('.inline-edit')||td.querySelector('.tag-editor')||td.querySelector('.typeahead-wrap'))return;
  const type=fieldType(header);const cached=cacheGet(ri);
  if(cached){_gridDoEdit(td,header,ri,table,type,cached[header]||'')}
  else{td.classList.add('cell-loading');
    fetch((table==='songs'?'/api/songs/':'/api/directory/')+ri).then(r=>r.json()).then(rec=>{
      td.classList.remove('cell-loading');_gridDoEdit(td,header,ri,table,type,rec[header]||'')
    }).catch(()=>{td.classList.remove('cell-loading');toast('Load failed','error')})}
}
function _gridDoEdit(td,rawH,ri,table,type,val){
  if(type==='tag'||type==='field_type'){_gridPillEdit(td,rawH,ri,table,val,'tag');return}
  if(type==='link'){_gridPillEdit(td,rawH,ri,table,val,'link');return}
  if(type==='autocomplete'){_gridAutoEdit(td,rawH,ri,table,val);return}
  if(type==='checklist'){openRecord(ri,table);return}
  // Long text fields open popup modal instead of inline textarea
  if(type==='long'){
    openLongTextPopup(rawH,val,(newVal)=>{
      _gridSave(td,rawH,ri,table,newVal);
    });
    return;
  }
  td.dataset.origHtml=td.innerHTML;
  if(type==='date')td.innerHTML='<input type="date" class="inline-edit grid-inline">';
  else if(type==='datetime')td.innerHTML='<input type="datetime-local" class="inline-edit grid-inline">';
  else if(type==='duration')td.innerHTML='<input class="inline-edit grid-inline" placeholder="00:00:00" style="font-family:var(--font-m)">';
  else if(type==='number')td.innerHTML='<input type="number" class="inline-edit grid-inline" style="font-family:var(--font-m);text-align:right">';
  else if(type==='currency')td.innerHTML='<input class="inline-edit grid-inline" placeholder="0.00" style="font-family:var(--font-m);text-align:right">';
  else if(type==='percent')td.innerHTML='<input type="number" class="inline-edit grid-inline" placeholder="0" style="font-family:var(--font-m);text-align:right" min="0" max="100">';
  else if(type==='rating'){
    td.dataset.origHtml=td.innerHTML;
    const cur=parseInt(val)||0;
    td.innerHTML='<div class="rating-edit" onclick="event.stopPropagation()">'+[1,2,3,4,5].map(n=>
      `<span style="cursor:pointer;font-size:18px;color:var(--accent)" onclick="_gridSave(this.closest('td'),'${escA(rawH)}',${ri},'${table}','${n}')">${n<=cur?'★':'☆'}</span>`
    ).join('')+'</div>';
    return;
  }
  else td.innerHTML='<input class="inline-edit grid-inline">';
  const inp=td.querySelector('.inline-edit');
  if(type==='datetime')inp.value=_dtToInput(val)||_dtDefault();
  else inp.value=val;
  inp.focus();
  // URL prefill: if URL field is empty, seed with http://
  if(type==='url'&&!val){inp.value='http://';inp.setSelectionRange(7,7)}
  inp.addEventListener('blur',()=>{let v=inp.value;if(type==='url'&&(v==='http://'||v==='https://'))v='';if(type==='datetime'&&v)v=v+':00';_gridSave(td,rawH,ri,table,v);setTimeout(()=>{if(td)cellSelect(td)},50)});
  inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&type!=='long'){e.preventDefault();inp.blur();setTimeout(()=>cellMove('down'),80)}
    if(e.key==='Escape'){e.stopPropagation();td.innerHTML=td.dataset.origHtml||'';delete td.dataset.origHtml;cellSelect(td)}
    if(e.key==='Tab'){e.preventDefault();inp.blur();setTimeout(()=>cellMove(e.shiftKey?'left':'right'),80)}
    if(e.key==='ArrowDown'&&type!=='long'){e.preventDefault();inp.blur();setTimeout(()=>cellMove('down'),80)}
    if(e.key==='ArrowUp'&&type!=='long'){e.preventDefault();inp.blur();setTimeout(()=>cellMove('up'),80)}
  });
  inp.addEventListener('click',e=>e.stopPropagation());
}
function _gridSave(td,field,ri,table,value){
  cacheUpdate(ri,field,value);td.innerHTML=renderCell(field,value,ri,table);delete td.dataset.origHtml;td.classList.add('cell-saving');
  fetch(table==='songs'?'/api/songs/update':(table==='invoices'?'/api/invoices/update':'/api/directory/update'),{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({field,row_index:ri,value})
  }).then(r=>r.json()).then(d=>{td.classList.remove('cell-saving');
    if(d.success){
      if(d.automations?.length)d.automations.forEach(a=>toast(a));
      // Re-sort grid after edit if sort is active (debounced)
      clearTimeout(window._resortTimer);
      window._resortTimer=setTimeout(()=>{
        const page=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);
        if(page&&page.sortField){page.load()}
      },1500);
    }
    else{toast(d.error||'Save failed','error')}
  }).catch(()=>{td.classList.remove('cell-saving');toast('Network error','error')});
}
function _gridPillEdit(td,field,ri,table,val,mode){
  td.dataset.origHtml=td.innerHTML;const items=splitP(val);const ac='#d4a853';
  let html='<div class="tag-editor grid-tag-editor" onclick="event.stopPropagation()"><div class="existing-tags">';
  items.forEach(t=>{let cls='pill',st='';
    if(mode==='tag'){cls='pill pill-tag';const c=PILL_COLORED?(TAG_COLORS[t]||ac):ac;st=`style="background:${c}20;color:${c};border:1px solid ${c}40"`}
    else if(mode==='link')cls='pill pill-link';
    html+=`<span class="${cls}" ${st}>${esc(t)} <span class="pill-x" onclick="event.stopPropagation();_gridRemPill(this,'${escA(field)}',${ri},'${table}','${escA(t)}')">&times;</span></span>`});
  // Auto-show search input (no need to click + first)
  html+=`<div class="typeahead-wrap" style="display:inline-flex;min-width:120px"><input class="typeahead-input grid-ta-input" placeholder="Add..." style="min-width:100px"><div class="typeahead-dropdown" style="display:none"></div></div>`;
  html+=`</div></div>`;
  td.innerHTML=html;
  // Wire up the input immediately
  const inp=td.querySelector('.typeahead-input'),dd=td.querySelector('.typeahead-dropdown');
  if(inp){inp.focus();let deb;
    inp.addEventListener('click',e=>e.stopPropagation());
    inp.addEventListener('input',()=>{clearTimeout(deb);deb=setTimeout(()=>{
      const q=inp.value.trim();if(q.length<1){dd.style.display='none';return}
      const ep=mode==='link'?`/api/search-record?q=${encodeURIComponent(q)}&table=${encodeURIComponent(getLinkTable(field))}`:`/api/autocomplete/${table==='songs'?'songs':'directory'}/${encodeURIComponent(cleanH(field))}?q=${encodeURIComponent(q)}&limit=15`;
      fetch(ep).then(r=>r.json()).then(d=>{
        const items=mode==='link'?(d.results||[]).map(r=>r.name):(d.values||[]);
        let h=items.map(v=>`<div class="typeahead-item" onclick="event.stopPropagation();_gridAddPill('${escA(field)}',${ri},'${table}','${escA(v)}')">${esc(v)}</div>`).join('');
        h+=`<div class="typeahead-item create" onclick="event.stopPropagation();_gridAddPill('${escA(field)}',${ri},'${table}','${escA(inp.value)}')">+ Add "${esc(inp.value)}"</div>`;
        dd.innerHTML=h;dd.style.display='block'})},30)});
    inp.addEventListener('keydown',e=>{
      if(e.key==='Enter'&&inp.value.trim()){e.stopPropagation();_gridAddPill(field,ri,table,inp.value.trim());inp.value='';dd.style.display='none'}
      if(e.key==='Escape'){e.stopPropagation();const c=cacheGet(ri);if(c)td.innerHTML=renderCell(field,c[field]||'',ri,table)}
    });
  }
  const handler=e=>{if(!td.contains(e.target)){document.removeEventListener('click',handler);
    const c=cacheGet(ri);if(c)td.innerHTML=renderCell(field,c[field]||'',ri,table);
    else fetch((table==='songs'?'/api/songs/':'/api/directory/')+ri).then(r=>r.json()).then(rec=>{td.innerHTML=renderCell(field,rec[field]||'',ri,table)})}};
  setTimeout(()=>document.addEventListener('click',handler),10);
}
function _gridRemPill(xEl,field,ri,table,valToRemove){
  const c=cacheGet(ri);const cur=c?c[field]||'':'';
  const td=xEl.closest('td');if(td)_gridSave(td,field,ri,table,splitP(cur).filter(t=>t!==valToRemove).join(' | '));
}
function _gridShowTA(container,field,ri,table,mode){
  if(container.querySelector('.typeahead-wrap'))return;
  const wrap=document.createElement('div');wrap.className='typeahead-wrap';
  wrap.innerHTML='<input class="typeahead-input grid-ta-input" placeholder="Search..."><div class="typeahead-dropdown" style="display:none"></div>';
  container.appendChild(wrap);const inp=wrap.querySelector('.typeahead-input'),dd=wrap.querySelector('.typeahead-dropdown');inp.focus();
  inp.addEventListener('click',e=>e.stopPropagation());let deb;
  inp.addEventListener('input',()=>{clearTimeout(deb);deb=setTimeout(()=>{
    const q=inp.value.trim();if(q.length<1){dd.style.display='none';return}
    const ep=mode==='link'?`/api/search-record?q=${encodeURIComponent(q)}&table=${encodeURIComponent(getLinkTable(field))}`:`/api/autocomplete/${table==='songs'?'songs':'directory'}/${encodeURIComponent(cleanH(field))}?q=${encodeURIComponent(q)}&limit=15`;
    fetch(ep).then(r=>r.json()).then(d=>{
      const items=mode==='link'?(d.results||[]).map(r=>r.name):(d.values||[]);
      let h=items.map(v=>`<div class="typeahead-item" onclick="event.stopPropagation();_gridAddPill('${escA(field)}',${ri},'${table}','${escA(v)}')">${esc(v)}</div>`).join('');
      h+=`<div class="typeahead-item create" onclick="event.stopPropagation();_gridAddPill('${escA(field)}',${ri},'${table}','${escA(inp.value)}')">+ Add "${esc(inp.value)}"</div>`;
      dd.innerHTML=h;dd.style.display='block'})},30)});
  inp.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();wrap.remove()}});
}
function _gridAddPill(field,ri,table,val){
  const c=cacheGet(ri);const existing=splitP(c?c[field]||'':'');
  if(!existing.includes(val))existing.push(val);
  const td=document.querySelector(`td[data-field="${field}"][data-ri="${ri}"]`)||document.querySelector('.tag-editor')?.closest('td');
  if(td)_gridSave(td,field,ri,table,existing.join(' | '));
}

// Single-value autocomplete (Audio Status, Genre, Format, etc.)
function _gridAutoEdit(td,field,ri,table,val){
  td.dataset.origHtml=td.innerHTML;
  td.innerHTML='<div class="typeahead-wrap" onclick="event.stopPropagation()"><input class="inline-edit grid-inline" placeholder="Type to search..."><div class="typeahead-dropdown" style="display:none"></div></div>';
  const inp=td.querySelector('.inline-edit'),dd=td.querySelector('.typeahead-dropdown');
  inp.value=val;inp.focus();inp.select();
  let deb;
  inp.addEventListener('input',()=>{clearTimeout(deb);deb=setTimeout(()=>{
    const q=inp.value.trim();if(q.length<1){dd.style.display='none';return}
    fetch(`/api/autocomplete/${table==='songs'?'songs':'directory'}/${encodeURIComponent(cleanH(field))}?q=${encodeURIComponent(q)}&limit=10`).then(r=>r.json()).then(d=>{
      const vals=d.values||[];if(!vals.length){dd.style.display='none';return}
      dd.innerHTML=vals.map(v=>`<div class="typeahead-item" onclick="event.stopPropagation();this.closest('td').querySelector('.inline-edit').value='${escA(v)}';this.closest('td').querySelector('.inline-edit').blur()">${esc(v)}</div>`).join('');
      dd.style.display='block';
    })},30)});
  inp.addEventListener('blur',()=>{setTimeout(()=>{_gridSave(td,field,ri,table,inp.value)},30)});
  inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();inp.blur()}
    if(e.key==='Escape'){e.stopPropagation();td.innerHTML=td.dataset.origHtml||'';delete td.dataset.origHtml}
    if(e.key==='Tab'){e.preventDefault();inp.blur();setTimeout(()=>_gridNav(td,e.shiftKey?'left':'right'),60)}
  });
}

// ==================== HEADER DROPDOWN MENU ====================
function showHeaderMenu(e,rawHeader,table){
  e.preventDefault();e.stopPropagation();document.querySelectorAll('.col-menu,.airtable-menu').forEach(m=>m.remove());
  const ch=cleanH(rawHeader),labels=getSortLabels(rawHeader),isProt=['name','title','airtable id','system id'].includes(ch.toLowerCase());
  const menu=document.createElement('div');menu.className='col-menu airtable-menu';
  menu.innerHTML=`<div class="col-menu-item" onclick="colAction('rename','${escA(rawHeader)}')"><span class="cm-icon">✏</span> Edit field</div>
    <div class="col-menu-sep"></div>
    <div class="col-menu-item" onclick="colAction('move_left','${escA(ch)}')"><span class="cm-icon">⇐</span> Move left</div>
    <div class="col-menu-item" onclick="colAction('move_right','${escA(ch)}')"><span class="cm-icon">⇒</span> Move right</div>
    <div class="col-menu-sep"></div>
    <div class="col-menu-item" onclick="colAction('insert_left','${escA(ch)}')"><span class="cm-icon">←</span> Insert left</div>
    <div class="col-menu-item" onclick="colAction('insert_right','${escA(ch)}')"><span class="cm-icon">→</span> Insert right</div>
    <div class="col-menu-sep"></div>
    <div class="col-menu-item" onclick="colAction('sort_asc','${escA(rawHeader)}')"><span class="cm-icon">↑</span> Sort ${labels[0]}</div>
    <div class="col-menu-item" onclick="colAction('sort_desc','${escA(rawHeader)}')"><span class="cm-icon">↓</span> Sort ${labels[1]}</div>
    <div class="col-menu-sep"></div>
    <div class="col-menu-item" onclick="colAction('filter','${escA(ch)}')"><span class="cm-icon">⊞</span> Filter by this field</div>
    <div class="col-menu-item" onclick="colAction('group','${escA(ch)}')"><span class="cm-icon">▦</span> Group by this field</div>
    <div class="col-menu-sep"></div>
    <div class="col-menu-item" onclick="colAction('freeze','${escA(ch)}')"><span class="cm-icon">❄</span> Freeze up to this column</div>
    <div class="col-menu-item" onclick="colAction('unfreeze','${escA(ch)}')"><span class="cm-icon">☀</span> Unfreeze all columns</div>
    <div class="col-menu-sep"></div>
    <div class="col-menu-item" onclick="colAction('hide','${escA(ch)}')"><span class="cm-icon">⊘</span> Hide field</div>
    ${isProt?'':`<div class="col-menu-item col-menu-danger" onclick="colAction('delete_field','${escA(rawHeader)}')"><span class="cm-icon">🗑</span> Delete field</div>`}`;
  const rect=e.target.closest('th').getBoundingClientRect();
  menu.style.left=Math.min(rect.left,window.innerWidth-260)+'px';menu.style.top=(rect.bottom+2)+'px';
  document.body.appendChild(menu);
  setTimeout(()=>{const h2=e2=>{if(!menu.contains(e2.target)){menu.remove();document.removeEventListener('click',h2)}};document.addEventListener('click',h2)},10);
}

// ==================== COLUMN DRAG ====================
let _dragColName=null;
let _dragHappened=false;
function colDragStart(e){
  const th=e.target.closest('th');if(!th)return;
  _dragColName=th.dataset.colName;_dragHappened=true;
  e.dataTransfer.effectAllowed='move';
  e.dataTransfer.setData('text/plain',_dragColName);
  th.classList.add('dragging');
  th.style.opacity='.5';
}
function colDragOver(e){
  e.preventDefault();e.dataTransfer.dropEffect='move';
  const th=e.target.closest('th');if(!th||!th.dataset.colName)return;
  document.querySelectorAll('th.drag-over-left,th.drag-over-right').forEach(t=>{t.classList.remove('drag-over-left','drag-over-right')});
  if(e.clientX<th.getBoundingClientRect().left+th.offsetWidth/2)th.classList.add('drag-over-left');
  else th.classList.add('drag-over-right');
}
function colDrop(e){
  e.preventDefault();
  document.querySelectorAll('th.drag-over-left,th.drag-over-right,th.dragging').forEach(t=>{t.classList.remove('drag-over-left','drag-over-right','dragging');t.style.opacity=''});
  const th=e.target.closest('th');if(!th){_dragColName=null;return}
  const tc=th.dataset.colName;
  if(!tc||!_dragColName||tc===_dragColName){_dragColName=null;return}
  const vc=typeof S!=='undefined'&&S.visibleCols?S.visibleCols:(typeof D!=='undefined'?D.visibleCols:[]);
  const fi=vc.indexOf(_dragColName),ti=vc.indexOf(tc);
  if(fi>=0&&ti>=0){
    vc.splice(fi,1);vc.splice(ti,0,_dragColName);
    toast('Column moved');
    if(typeof reload==='function')reload();
  }
  _dragColName=null;
}
function colDragEnd(e){
  document.querySelectorAll('th.drag-over-left,th.drag-over-right,th.dragging').forEach(t=>{t.classList.remove('drag-over-left','drag-over-right','dragging');t.style.opacity=''});
  _dragColName=null;
  setTimeout(()=>{_dragHappened=false},100);
}

// ==================== KEYBOARD GRID NAV ====================
function _gridNav(td,dir){const tr=td.closest('tr');if(!tr)return;const all=Array.from(tr.querySelectorAll('td[data-field]'));const eds=all.filter(t=>t.classList.contains('cell-editable'));const idx=eds.indexOf(td);const aIdx=all.indexOf(td);
  if(dir==='right'){if(idx<eds.length-1)eds[idx+1].click();else{const nr=tr.nextElementSibling;if(nr){const f=nr.querySelector('td.cell-editable');if(f)f.click()}}}
  else if(dir==='left'){if(idx>0)eds[idx-1].click();else{const pr=tr.previousElementSibling;if(pr){const e2=pr.querySelectorAll('td.cell-editable');if(e2.length)e2[e2.length-1].click()}}}
  else if(dir==='down'){const nr=tr.nextElementSibling;if(nr){const s=nr.querySelectorAll('td[data-field]')[aIdx];if(s&&s.classList.contains('cell-editable'))s.click()}}
  else if(dir==='up'){const pr=tr.previousElementSibling;if(pr){const s=pr.querySelectorAll('td[data-field]')[aIdx];if(s&&s.classList.contains('cell-editable'))s.click()}}}

// ==================== CMD+K COMMAND PALETTE ====================
function showCommandPalette(){document.querySelectorAll('.cmd-palette').forEach(p=>p.remove());
  const pal=document.createElement('div');pal.className='cmd-palette';
  pal.innerHTML='<div class="cmd-overlay" onclick="this.parentElement.remove()"></div><div class="cmd-box"><input class="cmd-input" placeholder="Type a command..." autofocus><div class="cmd-results"></div></div>';
  document.body.appendChild(pal);const input=pal.querySelector('.cmd-input'),results=pal.querySelector('.cmd-results');
  const cmds=[{l:'Go to Songs',a:()=>location.href='/songs',i:'🎵'},{l:'Go to Directory',a:()=>location.href='/directory',i:'📇'},{l:'Go to Pitch Builder',a:()=>location.href='/pitch',i:'🚀'},{l:'Go to Calendar',a:()=>location.href='/calendar',i:'📅'},{l:'Go to Dashboard',a:()=>location.href='/dashboard',i:'📊'},{l:'Go to Search',a:()=>location.href='/search',i:'🔍'},{l:'Go to Invoices',a:()=>location.href='/invoices',i:'💰'},{l:'Go to Settings',a:()=>location.href='/settings',i:'⚙'},{l:'New Record',a:()=>{const p=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);if(p)p.newRecord()},i:'➕'},{l:'Toggle Filter',a:()=>{const p=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);if(p)p.toggleFilter()},i:'⊞'},{l:'Export CSV',a:()=>exportViewCSV(window._currentTable||'songs'),i:'📤'},{l:'Undo',a:()=>fetch('/api/undo',{method:'POST'}).then(r=>r.json()).then(d=>{if(d.success){toast('Undone');if(typeof reload==='function')reload()}else toast(d.error||'Nothing to undo','error')}),i:'↩'},{l:'Toggle Pill Colors',a:()=>togglePillColors(),i:'🎨'},{l:'Keyboard Shortcuts',a:()=>showShortcutsHelp(),i:'⌨'},{l:'Check Duplicates',a:()=>location.href='/settings',i:'👥'}];
  function render(q){const f=q?cmds.filter(c=>c.l.toLowerCase().includes(q.toLowerCase())):cmds;
    results.innerHTML=f.map((c,i)=>`<div class="cmd-item${i===0?' cmd-active':''}" data-i="${i}"><span class="cmd-icon">${c.i}</span>${c.l}</div>`).join('');
    results.querySelectorAll('.cmd-item').forEach((el,i)=>{el.addEventListener('click',()=>{pal.remove();f[i].a()})})}
  render('');let ai=0;input.addEventListener('input',()=>{render(input.value);ai=0});
  input.addEventListener('keydown',e=>{const items=results.querySelectorAll('.cmd-item');
    if(e.key==='ArrowDown'){e.preventDefault();ai=Math.min(ai+1,items.length-1)}
    else if(e.key==='ArrowUp'){e.preventDefault();ai=Math.max(ai-1,0)}
    else if(e.key==='Enter'){e.preventDefault();items[ai]?.click();return}
    else if(e.key==='Escape'){pal.remove();return}
    items.forEach((it,i)=>{it.classList.toggle('cmd-active',i===ai)});items[ai]?.scrollIntoView({block:'nearest'})});input.focus()}
// Cmd+K handled in main keyboard handler below

// ==================== EXPORT ====================
function exportViewCSV(table){const page=table==='songs'?(typeof S!=='undefined'?S:null):(typeof D!=='undefined'?D:null);
  if(!page||!page.headers?.length){toast('No data','error');return}
  let url=(table==='songs'?'/api/songs':'/api/directory')+'?per_page=9999';
  if(page.search)url+=`&search=${encodeURIComponent(page.search)}`;if(page.sortField)url+=`&sort=${encodeURIComponent(page.sortField)}&dir=${page.sortDir}`;
  page.filters.forEach((f,i)=>{if(f.col)url+=`&f${i}_col=${encodeURIComponent(f.col)}&f${i}_op=${f.op}&f${i}_val=${encodeURIComponent(f.val||'')}`});
  toast('Preparing export...');fetch(url).then(r=>r.json()).then(d=>{if(!d.records?.length){toast('No records','error');return}
    // Use original sheet column order (like Airtable), only include visible columns
    const vc=page.visibleCols.length?page.visibleCols:d.headers.map(h=>cleanH(h));
    const oh=[];d.headers.forEach(h=>{if(vc.includes(cleanH(h)))oh.push(h)});
    let csv='\uFEFF'+oh.map(h=>'"'+cleanH(h).replace(/"/g,'""')+'"').join(',')+'\n';
    d.records.forEach(rec=>{csv+=oh.map(h=>'"'+(rec[h]||'').replace(/"/g,'""')+'"').join(',')+'\n'});
    const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
    a.download=`rollon_${table}${page.filters.length?'_filtered':''}_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);toast(`Exported ${d.records.length} records`)})}

// ==================== ONBOARDING ====================
function showOnboarding(){if(localStorage.getItem('rollon_onboarded'))return;
  document.body.insertAdjacentHTML('beforeend',`<div class="onboard-overlay" onclick="dismissOnboarding()"><div class="onboard-box" onclick="event.stopPropagation()">
    <h2 style="font-family:var(--font-d);color:var(--accent);margin-bottom:16px">Welcome to ROLLON AR</h2>
    <div class="onboard-tip"><span class="onboard-icon">✏️</span><div><strong>Click any cell to edit</strong><p>Click directly on tags, names, or text in the grid to edit inline.</p></div></div>
    <div class="onboard-tip"><span class="onboard-icon">▾</span><div><strong>Header menus</strong><p>Click the ▾ on any column for sort, filter, group, hide, and more.</p></div></div>
    <div class="onboard-tip"><span class="onboard-icon">⌘K</span><div><strong>Command palette</strong><p>Press Cmd+K anywhere for quick navigation and actions.</p></div></div>
    <div class="onboard-tip"><span class="onboard-icon">⇥</span><div><strong>Keyboard navigation</strong><p>Tab moves right. Enter saves and moves down. Escape cancels.</p></div></div>
    <button class="btn btn-accent" onclick="dismissOnboarding()" style="margin-top:16px;width:100%">Got it</button></div></div>`)}
function dismissOnboarding(){document.querySelector('.onboard-overlay')?.remove();localStorage.setItem('rollon_onboarded','1')}
setTimeout(()=>{if(document.querySelector('.data-grid'))showOnboarding()},1500);

// ---- COLUMN CONTEXT MENU ----
// Add new field with Airtable-style type picker
const FIELD_TYPES=[
  {cat:'Text',items:[
    {id:'text',label:'Single line text',icon:'A',desc:'Names, titles, short text'},
    {id:'long',label:'Long text',icon:'≡',desc:'Notes, descriptions, lyrics'},
  ]},
  {cat:'Select',items:[
    {id:'multi_select',label:'Multiple select',icon:'≡·',desc:'Tags, genres, multiple values'},
    {id:'single_select',label:'Single select',icon:'⊙',desc:'Status, category, one value'},
  ]},
  {cat:'Link',items:[
    {id:'link_personnel',label:'Link to Personnel',icon:'⇄',desc:'Artists, producers, songwriters'},
    {id:'link_labels',label:'Link to Record Labels',icon:'⇄',desc:'Record labels'},
    {id:'link_companies',label:'Link to Companies',icon:'⇄',desc:'MGMT, publishing, agencies'},
    {id:'link_cities',label:'Link to Cities',icon:'⇄',desc:'Cities with auto country fill'},
  ]},
  {cat:'Data',items:[
    {id:'date',label:'Date',icon:'📅',desc:'Release date, created date'},
    {id:'duration',label:'Duration',icon:'⏱',desc:'Song length (00:00:00)'},
    {id:'number',label:'Number',icon:'#',desc:'BPM, track number'},
    {id:'currency',label:'Currency',icon:'$',desc:'Amounts, fees, advances'},
    {id:'percent',label:'Percent',icon:'%',desc:'Splits, royalty rates'},
  ]},
  {cat:'Media',items:[
    {id:'url',label:'URL',icon:'🔗',desc:'Web links, Spotify, social media'},
    {id:'attachment',label:'Attachment',icon:'📎',desc:'Files, docs, audio (paste link)'},
    {id:'email',label:'Email',icon:'✉',desc:'Email addresses'},
    {id:'phone',label:'Phone number',icon:'📞',desc:'Phone numbers'},
  ]},
  {cat:'Other',items:[
    {id:'checkbox',label:'Checklist',icon:'☑',desc:'Task lists, to-do items'},
    {id:'user',label:'User',icon:'👤',desc:'Modified by, assigned to'},
    {id:'rating',label:'Rating',icon:'★',desc:'Star rating (1 to 5)'},
  ]},
];

// Field type overrides stored in localStorage
function getFieldTypeOverrides(){try{return JSON.parse(localStorage.getItem('rollon_field_types')||'{}')}catch(e){return {}}}
function setFieldTypeOverride(fieldName,typeId){
  const o=getFieldTypeOverrides();o[fieldName.toLowerCase()]=typeId;
  localStorage.setItem('rollon_field_types',JSON.stringify(o));
}

function addNewField(table){
  let selectedType='text';
  const overlay=document.createElement('div');overlay.className='prompt-overlay';overlay.id='field-type-picker';
  let html=`<div class="prompt-box" style="width:480px;max-height:80vh;overflow-y:auto" onclick="event.stopPropagation()">`;
  html+=`<h3 style="margin-bottom:4px">Add New Field</h3>`;
  html+=`<input id="new-field-name" class="prompt-input" placeholder="Field name..." style="margin-bottom:12px" autofocus>`;
  html+=`<div style="font-size:11px;color:var(--text-ghost);font-weight:600;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Choose field type</div>`;
  html+=`<input class="prompt-input" placeholder="Search field types..." style="margin-bottom:8px;font-size:12px" oninput="filterFieldTypes(this.value)">`;
  html+=`<div id="field-type-list">`;
  FIELD_TYPES.forEach(cat=>{
    html+=`<div style="font-size:10px;color:var(--text-ghost);font-weight:600;text-transform:uppercase;letter-spacing:1px;margin:10px 0 4px;padding-top:6px;border-top:1px solid var(--border)">${cat.cat}</div>`;
    cat.items.forEach(ft=>{
      html+=`<div class="ft-option${ft.id==='text'?' ft-selected':''}" data-type="${ft.id}" onclick="selectFieldType(this,'${ft.id}')">`;
      html+=`<span class="ft-icon">${ft.icon}</span>`;
      html+=`<div class="ft-info"><span class="ft-label">${ft.label}</span><span class="ft-desc">${ft.desc}</span></div>`;
      html+=`</div>`;
    });
  });
  html+=`</div>`;
  html+=`<div class="prompt-actions" style="margin-top:12px"><button class="btn" onclick="document.getElementById('field-type-picker')?.remove()">Cancel</button><button class="btn btn-accent" onclick="createFieldWithType('${table}')">Create Field</button></div>`;
  html+=`</div>`;
  overlay.innerHTML=html;
  overlay.addEventListener('click',()=>overlay.remove());
  document.body.appendChild(overlay);
  document.getElementById('new-field-name')?.focus();
  window._selectedFieldType='text';
}

function selectFieldType(el,typeId){
  document.querySelectorAll('.ft-option').forEach(o=>o.classList.remove('ft-selected'));
  el.classList.add('ft-selected');
  window._selectedFieldType=typeId;
}

function filterFieldTypes(query){
  const q=query.toLowerCase();
  document.querySelectorAll('#field-type-list .ft-option').forEach(el=>{
    const label=el.querySelector('.ft-label')?.textContent.toLowerCase()||'';
    const desc=el.querySelector('.ft-desc')?.textContent.toLowerCase()||'';
    el.style.display=(label.includes(q)||desc.includes(q))?'':'none';
  });
}

// ==================== CELL SELECTION + KEYBOARD NAVIGATION ====================
let _selectedCell=null;

function cellSelect(td){
  if(!td)return;
  // If already selected, second click edits
  if(_selectedCell===td){
    const field=td.dataset.field;const ri=parseInt(td.dataset.ri||td.closest('tr')?.dataset.ri);
    const table=window._currentTable||'songs';
    gridEdit(td,field,ri,table);
    return;
  }
  // Deselect previous
  document.querySelectorAll('td.cell-selected').forEach(c=>c.classList.remove('cell-selected'));
  td.classList.add('cell-selected');
  _selectedCell=td;
  td.focus();
}

function cellDeselect(){
  document.querySelectorAll('td.cell-selected').forEach(c=>c.classList.remove('cell-selected'));
  _selectedCell=null;
}

function cellMove(dir){
  if(!_selectedCell)return;
  const tr=_selectedCell.closest('tr');if(!tr)return;
  const allCells=Array.from(tr.querySelectorAll('td[data-field]'));
  const idx=allCells.indexOf(_selectedCell);

  let target=null;
  if(dir==='right'){
    target=allCells[idx+1]||null;
    if(!target){const nr=tr.nextElementSibling;if(nr)target=nr.querySelector('td[data-field]')}
  } else if(dir==='left'){
    target=allCells[idx-1]||null;
    if(!target){const pr=tr.previousElementSibling;if(pr){const cells=pr.querySelectorAll('td[data-field]');target=cells[cells.length-1]||null}}
  } else if(dir==='down'){
    const nr=tr.nextElementSibling;
    if(nr){const cells=nr.querySelectorAll('td[data-field]');target=cells[idx]||cells[cells.length-1]||null}
  } else if(dir==='up'){
    const pr=tr.previousElementSibling;
    if(pr){const cells=pr.querySelectorAll('td[data-field]');target=cells[idx]||cells[cells.length-1]||null}
  }
  if(target){
    cellSelect(target);
    target.scrollIntoView({block:'nearest',inline:'nearest'});
  }
}

// Global keyboard handler for grid navigation
document.addEventListener('keydown',e=>{
  // Skip if inside an input/textarea/select
  const tag=document.activeElement?.tagName;
  if(tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT')return;
  // Skip if modal prompt is open
  if(document.getElementById('prompt-modal')||document.getElementById('field-type-picker'))return;

  // Cmd+K command palette (already handled elsewhere but kept for safety)
  if((e.metaKey||e.ctrlKey)&&e.key==='k'){e.preventDefault();showCommandPalette();return}

  if(_selectedCell){
    // Arrow keys
    if(e.key==='ArrowRight'){e.preventDefault();cellMove('right')}
    else if(e.key==='ArrowLeft'){e.preventDefault();cellMove('left')}
    else if(e.key==='ArrowDown'){e.preventDefault();cellMove('down')}
    else if(e.key==='ArrowUp'){e.preventDefault();cellMove('up')}
    // Tab = move right, Shift+Tab = move left
    else if(e.key==='Tab'){e.preventDefault();cellMove(e.shiftKey?'left':'right')}
    // Enter = edit selected cell
    else if(e.key==='Enter'){
      e.preventDefault();
      const field=_selectedCell.dataset.field;
      const ri=parseInt(_selectedCell.dataset.ri||_selectedCell.closest('tr')?.dataset.ri);
      const table=window._currentTable||'songs';
      gridEdit(_selectedCell,field,ri,table);
    }
    // Escape = deselect
    else if(e.key==='Escape'){cellDeselect()}
    // Cmd+C = copy
    else if((e.metaKey||e.ctrlKey)&&e.key==='c'){
      const field=_selectedCell.dataset.field;
      const ri=parseInt(_selectedCell.dataset.ri||_selectedCell.closest('tr')?.dataset.ri);
      const cached=cacheGet(ri);
      let val=cached?cached[field]||'':_selectedCell.textContent.trim();
      if(val){
        // Convert pipe-separated pill values to comma-separated for clipboard
        const copyVal=val.includes(' | ')?val.split(' | ').join(', '):val;
        navigator.clipboard.writeText(copyVal).then(()=>{
          _selectedCell.classList.add('cell-copied');
          setTimeout(()=>_selectedCell?.classList.remove('cell-copied'),600);
          toast('Copied: '+copyVal.substring(0,50)+(copyVal.length>50?'...':''));
        });
        e.preventDefault();
      }
    }
    // Cmd+V = paste into selected cell
    else if((e.metaKey||e.ctrlKey)&&e.key==='v'){
      if(_selectedCell.classList.contains('cell-editable')){
        const field=_selectedCell.dataset.field;
        const ri=parseInt(_selectedCell.dataset.ri||_selectedCell.closest('tr')?.dataset.ri);
        const table=window._currentTable||'songs';
        const type=fieldType(field);
        const isPill=['tag','link','autocomplete','field_type','multi_select'].includes(type);
        navigator.clipboard.readText().then(text=>{
          if(text){
            // Convert comma-separated to pipe-separated for pill fields
            const val=isPill?text.split(/\s*,\s*/).join(' | '):text;
            _gridSave(_selectedCell,field,ri,table,val);toast('Pasted');
          }
        }).catch(()=>{});
        e.preventDefault();
      }
    }
    // Delete/Backspace = clear cell
    else if(e.key==='Delete'||e.key==='Backspace'){
      if(_selectedCell.classList.contains('cell-editable')&&!e.metaKey){
        e.preventDefault();
        const field=_selectedCell.dataset.field;
        const ri=parseInt(_selectedCell.dataset.ri||_selectedCell.closest('tr')?.dataset.ri);
        const table=window._currentTable||'songs';
        _gridSave(_selectedCell,field,ri,table,'');
        toast('Cleared');
      }
    }
    // Any printable character = start editing with that character
    else if(e.key.length===1&&!e.metaKey&&!e.ctrlKey&&!e.altKey){
      if(_selectedCell.classList.contains('cell-editable')){
        const field=_selectedCell.dataset.field;
        const ri=parseInt(_selectedCell.dataset.ri||_selectedCell.closest('tr')?.dataset.ri);
        const table=window._currentTable||'songs';
        gridEdit(_selectedCell,field,ri,table);
        // After editor opens, type the character
        setTimeout(()=>{
          const inp=_selectedCell.querySelector('.inline-edit');
          if(inp){inp.value=e.key;inp.setSelectionRange(1,1)}
        },50);
        e.preventDefault();
      }
    }
  }
});

// ==================== V36.1 LIVE CELL HIGHLIGHTER ====================
// Airtable-style Cmd+F highlighter wired on top of each grid's existing
// search bar. Wraps every match in a <mark class="live-hl"> so visible
// cells show gold overlays while the per-grid search still filters rows.
(function(){
  const HL_CLASS='live-hl';
  const HL_ACTIVE='live-hl-active';
  let _hlQuery='';
  let _hlIdx=-1;
  let _hlCounterEl=null;

  function ensureCounter(inputEl){
    if(!inputEl)return null;
    if(_hlCounterEl&&_hlCounterEl.isConnected)return _hlCounterEl;
    _hlCounterEl=document.createElement('span');
    _hlCounterEl.className='live-hl-counter';
    _hlCounterEl.style.cssText='position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:10px;color:var(--text-ghost);pointer-events:none;font-family:var(--font-m)';
    const p=inputEl.parentElement;
    if(p){p.style.position=p.style.position||'relative';p.appendChild(_hlCounterEl)}
    return _hlCounterEl;
  }

  function clearHighlights(root){
    root=root||document.querySelector('.data-grid tbody');
    if(!root)return;
    root.querySelectorAll('mark.'+HL_CLASS).forEach(m=>{
      const parent=m.parentNode;
      while(m.firstChild)parent.insertBefore(m.firstChild,m);
      parent.removeChild(m);
      parent.normalize();
    });
  }

  function highlightTextNode(node,q){
    const txt=node.nodeValue;
    const ql=q.toLowerCase();
    const tl=txt.toLowerCase();
    let idx=tl.indexOf(ql);
    if(idx<0)return 0;
    const frag=document.createDocumentFragment();
    let cursor=0,count=0;
    while(idx>=0){
      if(idx>cursor)frag.appendChild(document.createTextNode(txt.slice(cursor,idx)));
      const m=document.createElement('mark');
      m.className=HL_CLASS;
      m.textContent=txt.slice(idx,idx+q.length);
      frag.appendChild(m);
      count++;
      cursor=idx+q.length;
      idx=tl.indexOf(ql,cursor);
    }
    if(cursor<txt.length)frag.appendChild(document.createTextNode(txt.slice(cursor)));
    node.parentNode.replaceChild(frag,node);
    return count;
  }

  function walkAndHighlight(root,q){
    if(!q||q.length<1)return 0;
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{
      acceptNode(n){
        if(!n.nodeValue||!n.nodeValue.trim())return NodeFilter.FILTER_REJECT;
        const p=n.parentElement;
        if(!p)return NodeFilter.FILTER_REJECT;
        const tag=p.tagName;
        if(tag==='MARK'||tag==='INPUT'||tag==='TEXTAREA'||tag==='SCRIPT'||tag==='STYLE')return NodeFilter.FILTER_REJECT;
        if(p.closest('.pill-x')||p.closest('.typeahead-item')||p.closest('.search-dropdown')||p.closest('.global-search-dropdown'))return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const targets=[];let n;while((n=walker.nextNode()))targets.push(n);
    let total=0;
    targets.forEach(tn=>{total+=highlightTextNode(tn,q)});
    return total;
  }

  function applyHighlight(q){
    _hlQuery=q||'';
    _hlIdx=-1;
    const body=document.querySelector('.data-grid tbody');
    if(!body){if(_hlCounterEl)_hlCounterEl.textContent='';return 0}
    clearHighlights(body);
    const total=walkAndHighlight(body,_hlQuery);
    if(_hlCounterEl)_hlCounterEl.textContent=total?'0 of '+total:'';
    if(total>0)focusMatch(0);
    return total;
  }

  function focusMatch(i){
    const marks=document.querySelectorAll('.data-grid tbody mark.'+HL_CLASS);
    if(!marks.length)return;
    marks.forEach(m=>m.classList.remove(HL_ACTIVE));
    const clamped=((i%marks.length)+marks.length)%marks.length;
    const m=marks[clamped];
    m.classList.add(HL_ACTIVE);
    m.scrollIntoView({block:'center',inline:'nearest',behavior:'smooth'});
    _hlIdx=clamped;
    if(_hlCounterEl)_hlCounterEl.textContent=(clamped+1)+' of '+marks.length;
  }

  function step(delta){
    const marks=document.querySelectorAll('.data-grid tbody mark.'+HL_CLASS);
    if(!marks.length)return;
    focusMatch((_hlIdx<0?0:_hlIdx+delta));
  }

  function wireInput(){
    const inp=document.getElementById('search-input');
    if(!inp)return;
    if(inp.dataset.liveHlWired)return;
    inp.dataset.liveHlWired='1';
    ensureCounter(inp);
    inp.addEventListener('input',()=>{
      // Re-apply highlights slightly after the grid re-renders from the page filter.
      clearTimeout(inp._hlDeb);
      inp._hlDeb=setTimeout(()=>applyHighlight(inp.value.trim()),260);
    });
    inp.addEventListener('keydown',e=>{
      if(e.key==='Enter'){e.preventDefault();step(e.shiftKey?-1:1)}
      else if(e.key==='Escape'){e.preventDefault();inp.value='';applyHighlight('');inp.dispatchEvent(new Event('input'));inp.blur()}
      else if(e.key==='ArrowDown'&&!e.metaKey&&!e.ctrlKey){e.preventDefault();step(1)}
      else if(e.key==='ArrowUp'&&!e.metaKey&&!e.ctrlKey){e.preventDefault();step(-1)}
    });
  }

  // Watch the grid for re-renders and re-apply highlight automatically.
  const wrap=document.getElementById('grid-wrap');
  if(wrap){
    const obs=new MutationObserver(()=>{
      wireInput();
      if(_hlQuery)setTimeout(()=>applyHighlight(_hlQuery),50);
    });
    obs.observe(wrap,{childList:true,subtree:true});
  }
  document.addEventListener('DOMContentLoaded',wireInput);
  // Also wire on load for pages that finish after DOMContentLoaded.
  setTimeout(wireInput,500);

  // Cmd+F / Ctrl+F on grid pages focuses the per-grid search bar.
  document.addEventListener('keydown',e=>{
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='f'){
      const inp=document.getElementById('search-input');
      if(inp){e.preventDefault();inp.focus();inp.select()}
    }
  });

  window._liveHl={apply:applyHighlight,step,clear:()=>applyHighlight('')};
})();

// ==================== V36.1 ROW CONTEXT MENU: COPY ROW AS TSV ====================
(function(){
  function closeMenu(){document.getElementById('row-ctx-menu')?.remove()}
  function onContextmenu(e){
    const tr=e.target.closest('.data-grid tbody tr');
    if(!tr)return;
    // Ignore right-click on pill internals (keeps default browser menu accessible there)
    if(e.target.closest('.pill-x')||e.target.closest('a'))return;
    e.preventDefault();
    closeMenu();
    const ri=tr.dataset.ri;
    const m=document.createElement('div');
    m.id='row-ctx-menu';
    m.style.cssText='position:fixed;left:'+e.clientX+'px;top:'+e.clientY+'px;z-index:2000;background:var(--bg-elev,#1b1b1f);border:1px solid var(--border,#2a2a30);border-radius:6px;padding:4px;min-width:180px;box-shadow:0 6px 24px rgba(0,0,0,.45);font-size:12px';
    m.innerHTML=`
      <div class="row-ctx-item" data-action="tsv" style="padding:6px 10px;border-radius:4px;cursor:pointer">Copy Row as TSV</div>
      <div class="row-ctx-item" data-action="names" style="padding:6px 10px;border-radius:4px;cursor:pointer">Copy Row as comma-separated</div>
      <div class="row-ctx-item" data-action="json" style="padding:6px 10px;border-radius:4px;cursor:pointer">Copy Row as JSON</div>
    `;
    document.body.appendChild(m);
    m.querySelectorAll('.row-ctx-item').forEach(it=>{
      it.addEventListener('mouseenter',()=>it.style.background='var(--accent-dim,#d4a85322)');
      it.addEventListener('mouseleave',()=>it.style.background='');
      it.addEventListener('click',()=>{
        const action=it.dataset.action;
        const cached=cacheGet(parseInt(ri,10));
        const cells=Array.from(tr.querySelectorAll('td[data-field]'));
        const pairs=cells.map(c=>{
          const field=c.dataset.field||'';
          let v=cached?(cached[field]||''):(c.textContent||'').trim();
          v=String(v).replace(/\t/g,' ').replace(/\r?\n/g,' ');
          return [cleanH(field)||field,v];
        });
        let payload='';
        if(action==='tsv'){
          const headers=pairs.map(p=>p[0]).join('\t');
          const row=pairs.map(p=>p[1]).join('\t');
          payload=headers+'\n'+row;
        } else if(action==='names'){
          payload=pairs.map(p=>(p[1]||'').split(/\s*\|\s*/).join(', ')).filter(Boolean).join(', ');
        } else {
          const obj={};pairs.forEach(p=>obj[p[0]]=p[1]);
          payload=JSON.stringify(obj,null,2);
        }
        navigator.clipboard.writeText(payload).then(()=>toast('Row copied'));
        closeMenu();
      });
    });
  }
  document.addEventListener('contextmenu',onContextmenu);
  document.addEventListener('click',closeMenu);
  document.addEventListener('scroll',closeMenu,true);
})();

function createFieldWithType(table){
  const name=document.getElementById('new-field-name')?.value.trim();
  if(!name){toast('Field name is required','error');return}
  const typeId=window._selectedFieldType||'text';
  document.getElementById('field-type-picker')?.remove();

  fetch('/api/insert-column',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({table:table,name:name})
  }).then(r=>r.json()).then(d=>{
    if(d.success){
      setFieldTypeOverride(name,typeId);
      const page=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);
      if(page){
        // Handle insert position (from Insert left/right)
        const pos=window._insertPosition;
        if(pos){
          const idx=page.visibleCols.indexOf(pos.relativeTo);
          if(idx>=0){
            const insertAt=pos.action==='insert_left'?idx:idx+1;
            page.visibleCols.splice(insertAt,0,name);
          } else page.visibleCols.push(name);
          window._insertPosition=null;
        } else {
          page.visibleCols.push(name);
        }
        if(page.allCols)page.allCols.push(name);
        page.load();
      }
      toast('Field created: '+name);
    } else toast(d.error||'Failed','error');
  });
}

// Column actions (called from header dropdown menu)
function colAction(action,val){
  document.querySelectorAll('.col-menu').forEach(m=>m.remove());
  const page=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);if(!page)return;
  if(action==='sort_asc'){page.sortField=val;page.sortDir='asc';page.load()}
  else if(action==='sort_desc'){page.sortField=val;page.sortDir='desc';page.load()}
  else if(action==='move_left'){
    const vc=page.visibleCols;const cn=cleanH(val);const idx=vc.indexOf(cn);
    if(idx>0){vc.splice(idx,1);vc.splice(idx-1,0,cn);page.load();toast(cn+' moved left')}
    else if(idx===0)toast('Already first column')
    else toast('Column not found in visible columns')
  }
  else if(action==='move_right'){
    const vc=page.visibleCols;const cn=cleanH(val);const idx=vc.indexOf(cn);
    if(idx>=0&&idx<vc.length-1){vc.splice(idx,1);vc.splice(idx+1,0,cn);page.load();toast(cn+' moved right')}
    else if(idx===vc.length-1)toast('Already last column')
    else toast('Column not found in visible columns')
  }
  else if(action==='filter'){page.filters=[{col:cleanH(val),op:'is_not_empty',val:''}];page.page=1;document.getElementById('filter-panel')?.classList.add('open');page.load()}
  else if(action==='freeze'){
    const vc=page.visibleCols;const idx=vc.indexOf(cleanH(val));
    if(idx>=0){window._freezeCount=idx+1;applyFreezePanes();toast('Froze '+(idx+1)+' column'+(idx>0?'s':''))}
  }
  else if(action==='unfreeze'){
    window._freezeCount=0;applyFreezePanes();toast('Columns unfrozen');
  }
  else if(action==='group'&&page.groupBy){page.groupBy(cleanH(val))}
  else if(action==='hide'){const i=page.visibleCols.indexOf(cleanH(val));if(i>=0){page.visibleCols.splice(i,1);page.load()}}
  else if(action==='rename'){
    const table=window._currentTable||'directory';
    // Headers with automations tied to them
    const autoHeaders=['email','city','tags','tag','songwriter credits','producer','artist',
      'works with','emails combined','combined first names','last outreach','countries','country'];
    const isAuto=autoHeaders.some(a=>cleanH(val).toLowerCase().includes(a));
    const warning=isAuto?'\n\n⚠ This field has automations tied to it. Renaming may break: auto-tagging, city/country fill, or email detection.':'';
    showPromptModal('Rename Column',[{label:'New name for "'+cleanH(val)+'"'+warning,placeholder:cleanH(val),value:cleanH(val)}],(v)=>{
      if(!v[0]||v[0]===cleanH(val))return;
      fetch('/api/rename-header',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({table,old_name:val,new_name:v[0]})
      }).then(r=>r.json()).then(d=>{
        if(d.success){toast('Renamed: '+cleanH(val)+' → '+v[0]);
          // Update local cols
          const idx=page.visibleCols.indexOf(cleanH(val));
          if(idx>=0)page.visibleCols[idx]=v[0];
          const aidx=page.allCols.indexOf(cleanH(val));
          if(aidx>=0)page.allCols[aidx]=v[0];
          page.load()}
        else toast(d.error||'Rename failed','error');
      });
    });
  }
  else if(action==='insert_left'||action==='insert_right'){
    window._insertPosition={action:action,relativeTo:cleanH(val)};
    addNewField(window._currentTable||'directory');
  }
  else if(action==='delete_field'){
    const table=window._currentTable||'directory';
    showPromptModal('Delete Field: '+cleanH(val),[{label:'Type DELETE to confirm. This permanently removes the column and all its data.',placeholder:''}],(v)=>{
      if(v[0]!=='DELETE'){toast('Cancelled','error');return}
      fetch('/api/delete-column',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({table:table,column_name:val})
      }).then(r=>r.json()).then(d=>{
        if(d.success){
          const cn=cleanH(val);
          const idx=page.visibleCols.indexOf(cn);
          if(idx>=0)page.visibleCols.splice(idx,1);
          const aidx=page.allCols.indexOf(cn);
          if(aidx>=0)page.allCols.splice(aidx,1);
          toast('Field deleted: '+cn);page.load();
        } else toast(d.error||'Failed','error');
      });
    });
  }
}

// ---- ROW SELECTION ----
window._selectedRows=new Set();
function toggleRow(ri,checked){if(checked)window._selectedRows.add(ri);else window._selectedRows.delete(ri);updateBulkBar()}
function toggleAllRows(cb){document.querySelectorAll('tbody .row-check').forEach(c=>{c.checked=cb.checked;const ri=parseInt(c.closest('tr').dataset.ri);if(cb.checked)window._selectedRows.add(ri);else window._selectedRows.delete(ri)});updateBulkBar()}
function updateBulkBar(){
  const bar=document.getElementById('bulk-bar');if(!bar)return;
  const selAll=document.getElementById('select-all-filtered');
  if(window._selectedRows.size>0){
    bar.classList.add('active');
    bar.querySelector('.bulk-count').textContent=window._selectedRows.size+' selected';
    // Show "select all filtered" if we only selected current page
    const page=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);
    if(selAll&&page){
      const total=parseInt(document.getElementById('record-count')?.textContent)||0;
      if(total>window._selectedRows.size)selAll.style.display='';
      else selAll.style.display='none';
    }
  }
  else{bar.classList.remove('active');if(selAll)selAll.style.display='none'}
}

// Select ALL filtered records across all pages
function selectAllFiltered(table){
  const page=table==='songs'?(typeof S!=='undefined'?S:null):(typeof D!=='undefined'?D:null);
  if(!page)return;
  let url=table==='songs'?'/api/songs?per_page=9999':'/api/directory?per_page=9999';
  if(page.search)url+=`&search=${encodeURIComponent(page.search)}`;
  if(page.sortField)url+=`&sort=${encodeURIComponent(page.sortField)}&dir=${page.sortDir}`;
  page.filters.forEach((f,i)=>{if(f.col)url+=`&f${i}_col=${encodeURIComponent(f.col)}&f${i}_op=${f.op}&f${i}_val=${encodeURIComponent(f.val||'')}`});
  toast('Selecting all filtered records...');
  fetch(url).then(r=>r.json()).then(d=>{
    window._selectedRows.clear();
    (d.records||[]).forEach(rec=>window._selectedRows.add(rec._row_index));
    updateBulkBar();
    toast(`Selected ${window._selectedRows.size} records`);
    // Check all visible checkboxes
    document.querySelectorAll('tbody .row-check').forEach(cb=>{
      const ri=parseInt(cb.closest('tr')?.dataset.ri);
      cb.checked=window._selectedRows.has(ri);
    });
  });
}

// ---- BULK ACTIONS ----
function bulkAction(action,table){
  const rows=Array.from(window._selectedRows);if(!rows.length){toast('Select rows first','error');return}
  if(action==='add_tag'){
    showPromptModal('Add Tag to '+rows.length+' rows',[{label:'Tag',placeholder:'e.g. BW Collab'}],(v)=>{
      if(!v[0])return;doBulk(table,rows,'add_tag','',v[0])});
  } else if(action==='remove_tag'){
    showPromptModal('Remove Tag from '+rows.length+' rows',[{label:'Tag',placeholder:'e.g. Dont Pitch'}],(v)=>{
      if(!v[0])return;doBulk(table,rows,'remove_tag','',v[0])});
  } else if(action==='add_field'){
    showPromptModal('Add to Field for '+rows.length+' rows',[
      {label:'Field',placeholder:'e.g. Genre, Producer, Songwriter Credits'},
      {label:'Value to ADD (appends, never replaces)',placeholder:'e.g. Pop, Ben Wylen'}
    ],(v)=>{if(!v[0]||!v[1])return;doBulk(table,rows,'add_to_field',v[0],v[1])});
  } else if(action==='remove_field'){
    showPromptModal('Remove from Field for '+rows.length+' rows',[
      {label:'Field',placeholder:'e.g. Genre, Producer'},
      {label:'Value to REMOVE',placeholder:'e.g. Pop'}
    ],(v)=>{if(!v[0]||!v[1])return;doBulk(table,rows,'remove_from_field',v[0],v[1])});
  } else if(action==='set_field'){
    const page=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);
    const cols=page?.allCols||[];
    showPromptModal('Set Field Value for '+rows.length+' rows',[
      {label:'Field',type:'select',options:cols},
      {label:'Value (OVERWRITES existing)',placeholder:'e.g. Pop'}
    ],(v)=>{if(!v[0])return;doBulk(table,rows,'set_field',v[0],v[1]||'')});
  } else if(action==='delete'){
    showPromptModal('Archive '+rows.length+' records?',[
      {label:'These records will be moved to Archive and can be restored from Settings.',placeholder:''},
      {label:'Type ARCHIVE to confirm (or DELETE for permanent removal)',placeholder:''}
    ],(v)=>{
      const confirm=v[1]||'';
      if(confirm!=='ARCHIVE'&&confirm!=='DELETE'){toast('Type ARCHIVE or DELETE to confirm','error');return}
      const hardDelete=confirm==='DELETE';
      fetch('/api/bulk-delete',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({table,row_indices:rows,hard_delete:hardDelete})
      }).then(r=>r.json()).then(d=>{if(d.success){toast(d.deleted+' records '+(d.method==='archived'?'archived (recoverable)':'permanently deleted'));window._selectedRows.clear();updateBulkBar();reload()}else toast(d.error,'error')});
    });
  }
}
function doBulk(table,rows,action,field,value){
  fetch('/api/bulk-update',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({table,row_indices:rows,action,field,value})
  }).then(r=>r.json()).then(d=>{if(d.success){toast(d.updated+' rows updated');window._selectedRows.clear();updateBulkBar();reload()}else toast(d.error,'error')});
}

// ---- PAGINATION ----
function buildPagination(containerId,page,totalPages,total,onChange){
  const el=document.getElementById(containerId);if(!el)return;
  if(totalPages<=1){el.innerHTML=`<span class="page-info">${total} records</span>`;return}
  let html=`<button class="btn btn-sm" ${page<=1?'disabled':''} onclick="window._pageChange(${page-1})">◀</button>`;
  for(let p=Math.max(1,page-2);p<=Math.min(totalPages,page+2);p++)
    html+=`<button class="btn btn-sm ${p===page?'btn-accent':''}" onclick="window._pageChange(${p})">${p}</button>`;
  html+=`<button class="btn btn-sm" ${page>=totalPages?'disabled':''} onclick="window._pageChange(${page+1})">▶</button>`;
  html+=`<span class="page-info">${total} records</span>`;
  el.innerHTML=html;window._pageChange=onChange||function(){};
}

// ---- FILTER BUILDER ----
function buildFilterPanel(containerId,columns,filters,onChange){
  const el=document.getElementById(containerId);if(!el)return;
  const ops=['contains','does_not_contain','is','is_not','is_empty','is_not_empty','starts_with','ends_with'];
  let html='';
  filters.forEach((f,i)=>{
    html+='<div class="filter-row">';
    html+=`<span class="filter-conjunction">${i===0?'Where':'and'}</span>`;
    html+=`<select onchange="window._fu(${i},'col',this.value)"><option value="">Select field...</option>`;
    columns.forEach(c=>{html+=`<option value="${escA(c)}" ${f.col===c?'selected':''}>${esc(c)}</option>`});
    html+=`</select><select onchange="window._fu(${i},'op',this.value)">`;
    ops.forEach(o=>{html+=`<option value="${o}" ${f.op===o?'selected':''}>${o.replace(/_/g,' ')}</option>`});
    html+='</select>';
    if(!['is_empty','is_not_empty'].includes(f.op))html+=`<input value="${esc(f.val||'').replace(/"/g,'&quot;')}" placeholder="Value..." oninput="window._fu(${i},'val',this.value)">`;
    html+=`<span class="filter-remove" onclick="window._fr(${i})">&times;</span></div>`;
  });
  html+=`<button class="btn btn-sm" onclick="window._fa()" style="margin-top:4px">+ Add condition</button>`;
  el.innerHTML=html;
  window._fu=(idx,key,val)=>{filters[idx][key]=val;onChange(filters)};
  window._fr=idx=>{filters.splice(idx,1);onChange(filters)};
  window._fa=()=>{filters.push({col:'',op:'contains',val:''});buildFilterPanel(containerId,columns,filters,onChange)};
}

// ---- FIELD VISIBILITY ----
function buildFieldsPanel(containerId,allCols,visCols,onChange){
  const el=document.getElementById(containerId);if(!el)return;
  window._fpConfig={containerId,allCols,visCols,onChange};
  let html='<input class="prompt-input" id="field-search" placeholder="Search fields..." style="margin-bottom:8px;font-size:12px" oninput="filterFieldsList(this.value)">';
  html+='<div style="margin-bottom:6px;display:flex;gap:4px"><button class="btn btn-sm" onclick="window._taf(true)">Show all</button><button class="btn btn-sm" onclick="window._taf(false)">Hide all</button></div>';
  html+='<div id="field-list-items">';
  html+=renderFieldListItems(allCols,visCols,'');
  html+='</div>';
  el.innerHTML=html;
  window._tf=(col,on)=>{if(on&&!visCols.includes(col))visCols.push(col);if(!on){const i=visCols.indexOf(col);if(i>=0)visCols.splice(i,1)}onChange(visCols);buildFieldsPanel(containerId,allCols,visCols,onChange)};
  window._taf=on=>{visCols.length=0;if(on)allCols.forEach(c=>visCols.push(c));else{const t=allCols.find(c=>c.toLowerCase()==='title'||c.toLowerCase()==='name');if(t)visCols.push(t)}onChange(visCols);buildFieldsPanel(containerId,allCols,visCols,onChange)};
  window._fmove=(col,dir)=>{
    const idx=visCols.indexOf(col);if(idx<0)return;
    const ni=idx+dir;if(ni<0||ni>=visCols.length)return;
    visCols.splice(idx,1);visCols.splice(ni,0,col);
    onChange(visCols);buildFieldsPanel(containerId,allCols,visCols,onChange);
  };
}

// Field drag in panel
let _dragField=null;
function renderFieldListItems(allCols,visCols,query){
  const q=query.toLowerCase();
  const ordered=[...visCols,...allCols.filter(c=>!visCols.includes(c))];
  let html='';
  ordered.forEach(c=>{
    if(!allCols.includes(c))return;
    if(q&&!c.toLowerCase().includes(q))return;
    const chk=visCols.includes(c)?'checked':'';
    const arrows=chk?`<span class="field-arrows"><span onclick="event.preventDefault();event.stopPropagation();window._fmove('${escA(c)}',-1)" title="Move up" class="field-arrow">▲</span><span onclick="event.preventDefault();event.stopPropagation();window._fmove('${escA(c)}',1)" title="Move down" class="field-arrow">▼</span></span>`:'';
    html+=`<label class="field-toggle" draggable="true" data-field="${escA(c)}" ondragstart="fieldDragStart(event)" ondragover="event.preventDefault()" ondrop="fieldDrop(event)" ondragend="fieldDragEnd(event)"><input type="checkbox" ${chk} onchange="window._tf('${escA(c)}',this.checked)"><span>${esc(c)}</span>${arrows}</label>`;
  });
  return html;
}
function filterFieldsList(query){
  const el=document.getElementById('field-list-items');if(!el||!window._fpConfig)return;
  el.innerHTML=renderFieldListItems(window._fpConfig.allCols,window._fpConfig.visCols,query);
}

function fieldDragStart(e){
  _dragField=e.target.closest('.field-toggle')?.dataset.field;
  e.dataTransfer.effectAllowed='move';
  e.dataTransfer.setData('text/plain',_dragField||'');
  if(e.target.closest('.field-toggle'))e.target.closest('.field-toggle').style.opacity='.5';
}
function fieldDrop(e){
  e.preventDefault();
  document.querySelectorAll('.field-toggle').forEach(f=>f.style.opacity='');
  const target=e.target.closest('.field-toggle')?.dataset.field;
  if(!target||!_dragField||target===_dragField){_dragField=null;return}
  const page=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);if(!page){_dragField=null;return}
  const vc=page.visibleCols;
  const fi=vc.indexOf(_dragField),ti=vc.indexOf(target);
  if(fi>=0&&ti>=0){
    vc.splice(fi,1);vc.splice(ti,0,_dragField);toast('Field reordered');page.load();
    // Re-render fields panel
    if(window._fpConfig)buildFieldsPanel(window._fpConfig.containerId,window._fpConfig.allCols,vc,window._fpConfig.onChange);
  }
  _dragField=null;
}
function fieldDragEnd(e){
  document.querySelectorAll('.field-toggle').forEach(f=>f.style.opacity='');
  _dragField=null;
}

// ---- GROUP RENDERING ----
function buildGroupedGrid(containerId,headers,allRecords,table,visCols,groupField,sortField,sortDir,onSort,groupDir){
  const c=document.getElementById(containerId);if(!c)return;
  const gi=headers.findIndex(h=>cleanH(h).toLowerCase()===groupField.toLowerCase());
  if(gi<0){buildGridV2(containerId,headers,allRecords,table,visCols,sortField,sortDir,onSort);return}
  const groups={};
  allRecords.forEach(rec=>{
    const gval=rec[headers[gi]]||'(empty)';
    const key=splitP(gval)[0]||gval;
    if(!groups[key])groups[key]=[];
    groups[key].push(rec);
  });
  const shown=visCols||headers.map(h=>cleanH(h));
  const indices=[];shown.forEach(vc=>{const idx=headers.findIndex(h=>cleanH(h)===vc);if(idx>=0)indices.push(idx)});

  let html='';
  const gkeys=Object.keys(groups).sort();
  if(groupDir==='desc')gkeys.reverse();
  gkeys.forEach(gname=>{
    const recs=groups[gname];
    html+=`<div class="group-header"><span class="group-name">${esc(gname)}</span><span class="group-count">${recs.length}</span></div>`;
    html+='<table class="data-grid"><thead><tr>';
    html+='<th class="check-col" style="width:36px"><input type="checkbox" class="row-check" onchange="toggleAllRows(this)"></th><th class="expand-col"></th>';
    indices.forEach(i=>{
      const ch=cleanH(headers[i]);
      const arrow=sortField===headers[i]?(sortDir==='asc'?' ▲':' ▼'):'';
      html+=`<th draggable="true" data-col-idx="${i}" data-col-name="${esc(ch).replace(/"/g,'&quot;')}"
        onclick="if(typeof _dragHappened!=='undefined'&&_dragHappened)return;window._gridSort&&window._gridSort('${escA(headers[i])}')"
        oncontextmenu="showHeaderMenu(event,'${escA(headers[i])}','${table}')"
        ondragstart="colDragStart(event)" ondragover="colDragOver(event)" ondrop="colDrop(event)" ondragend="colDragEnd(event)">
        <span class="th-label">${esc(ch)}</span><span class="sort-arrow">${arrow}</span>
        <span class="th-dropdown" onclick="event.stopPropagation();showHeaderMenu(event,'${escA(headers[i])}','${table}')">▾</span>
      </th>`;
    });
    html+='</tr></thead><tbody>';
    recs.forEach(rec=>{
      const ri=rec._row_index;
      html+=`<tr data-ri="${ri}"><td class="check-col"><input type="checkbox" class="row-check" onchange="toggleRow(${ri},this.checked)" onclick="event.stopPropagation()"></td><td class="expand-col" onclick="openRecord(${ri},'${table}')" title="Open full record"><span class="expand-icon">↗</span></td>`;
      indices.forEach(i=>{
        const rawH=headers[i];const type=fieldType(rawH);
        const isEditable=_ED_TYPES.includes(type);
        html+=`<td data-field="${esc(rawH).replace(/"/g,'&quot;')}" data-ri="${ri}" class="${isEditable?'cell-editable':''}"
          onclick="${isEditable?`if(event.target.closest('.pill-link,.pill-x,.pill'))return;event.stopPropagation();cellSelect(this)`:`if(event.target.closest('.pill-link'))return;openRecord(${ri},'${table}')`}"
          ondblclick="${isEditable?`event.stopPropagation();gridEdit(this,'${escA(rawH)}',${ri},'${table}')`:''}">${renderCell(rawH,rec[rawH],ri,table)}</td>`;
      });
      html+='</tr>';
    });
    html+='</tbody></table>';
  });
  c.innerHTML=html||'<div class="loading">No groups found</div>';
  window._gridSort=onSort||function(){};
  window._currentTable=table;
}

// ==================== FEATURE: EXPORT CURRENT VIEW ====================
function exportCurrentView(table){
  const page=table==='songs'?S:D;
  if(!page||!page.headers?.length){toast('No data to export','error');return}
  // Fetch all records with current filters (no pagination)
  let url=table==='songs'?'/api/songs?per_page=9999':'/api/directory?per_page=9999';
  if(page.search)url+=`&search=${encodeURIComponent(page.search)}`;
  if(page.sortField)url+=`&sort=${encodeURIComponent(page.sortField)}&dir=${page.sortDir}`;
  page.filters.forEach((f,i)=>{if(f.col)url+=`&f${i}_col=${encodeURIComponent(f.col)}&f${i}_op=${f.op}&f${i}_val=${encodeURIComponent(f.val||'')}`});
  toast('Preparing export...');
  fetch(url).then(r=>r.json()).then(d=>{
    if(!d.records?.length){toast('No records to export','error');return}
    const visCols=page.visibleCols.length?page.visibleCols:d.headers.map(h=>cleanH(h));
    const visHeaders=d.headers.filter(h=>visCols.includes(cleanH(h)));
    // Build CSV
    let csv=visHeaders.map(h=>'"'+cleanH(h).replace(/"/g,'""')+'"').join(',')+'\n';
    d.records.forEach(rec=>{
      csv+=visHeaders.map(h=>{
        let v=(rec[h]||'').replace(/"/g,'""');
        return '"'+v+'"';
      }).join(',')+'\n';
    });
    // Add branding row
    csv+='\n"Generated by ROLLON AR | rollonent.com"\n';
    // Download
    const blob=new Blob([csv],{type:'text/csv;charset=utf-8;'});
    const link=document.createElement('a');
    link.href=URL.createObjectURL(blob);
    link.download=`rollon_${table}_export_${new Date().toISOString().split('T')[0]}.csv`;
    link.click();setTimeout(()=>URL.revokeObjectURL(link.href),5000);
    toast(`Exported ${d.records.length} records`);
  });
}

// ==================== EMPTY STATE ====================
function showEmptyState(containerId,message,icon){
  const c=document.getElementById(containerId);if(!c)return;
  c.innerHTML=`<div class="empty-state"><div class="empty-icon">${icon||''}</div><div class="empty-msg">${message||'No records found'}</div></div>`;
}

// ==================== FEATURE: CSV BULK IMPORT ====================
function showImportDialog(table){
  let html=`<div class="prompt-overlay" id="prompt-modal"><div class="prompt-box" style="max-width:600px">`;
  html+=`<h3>Import CSV to ${table==='songs'?'Songs':'Directory'}</h3>`;
  html+=`<p style="color:var(--text-dim);font-size:12px;margin-bottom:12px">Upload a CSV file. First row must be column headers. Values will be matched to existing fields by name.</p>`;
  html+=`<input type="file" id="import-file" accept=".csv,.tsv,.txt" style="margin-bottom:12px">`;
  html+=`<div id="import-preview" style="max-height:300px;overflow:auto;font-size:11px;margin-bottom:12px"></div>`;
  html+=`<div class="prompt-actions"><button class="btn" onclick="document.getElementById('prompt-modal')?.remove()">Cancel</button><button class="btn btn-accent" id="import-go" style="display:none" onclick="executeImport('${table}')">Import</button></div>`;
  html+=`</div></div>`;
  document.body.insertAdjacentHTML('beforeend',html);
  document.getElementById('import-file').addEventListener('change',e=>previewImport(e,table));
}

let _importData=null;
function previewImport(e,table){
  const file=e.target.files[0];if(!file)return;
  const reader=new FileReader();
  reader.onload=function(ev){
    const text=ev.target.result;
    const sep=text.includes('\t')?'\t':',';
    const lines=text.split('\n').filter(l=>l.trim());
    if(lines.length<2){toast('File needs a header row and at least one data row','error');return}
    // Parse CSV (simple parser handles quoted fields)
    function parseLine(line){
      const fields=[];let field='',inQuote=false;
      for(let i=0;i<line.length;i++){
        const c=line[i];
        if(c==='"'){if(inQuote&&line[i+1]==='"'){field+='"';i++}else inQuote=!inQuote}
        else if(c===sep&&!inQuote){fields.push(field.trim());field=''}
        else field+=c;
      }
      fields.push(field.trim());return fields;
    }
    const headers=parseLine(lines[0]);
    const rows=lines.slice(1).map(l=>parseLine(l)).filter(r=>r.some(c=>c));
    _importData={headers,rows,table};
    // Fetch sheet headers to show column matching
    const metaEp=table==='songs'?'/api/songs/tags':'/api/directory/tags';
    fetch(metaEp).then(r=>r.json()).then(meta=>{
      const sheetCols=(meta.columns||[]).map(c=>c.toLowerCase());
      let preview=`<div style="color:var(--accent);margin-bottom:6px">${rows.length} rows, ${headers.length} columns</div>`;
      // Column matching report
      preview+=`<div style="margin-bottom:10px;font-size:11px">`;
      let matched=0,skipped=0;
      headers.forEach(h=>{
        const hl=h.trim().toLowerCase();
        const found=sheetCols.some(sc=>sc===hl||sc.includes(hl)||hl.includes(sc));
        if(found){matched++;preview+=`<span class="pill" style="background:#059669;color:white;margin:2px">✓ ${esc(h)}</span> `}
        else{skipped++;preview+=`<span class="pill" style="background:#dc2626;color:white;margin:2px;opacity:.7">✗ ${esc(h)}</span> `}
      });
      preview+=`</div><div style="font-size:11px;color:var(--text-dim);margin-bottom:8px">${matched} columns matched, ${skipped} will be skipped</div>`;
      // Data preview
      preview+=`<table class="data-grid" style="font-size:11px"><thead><tr>`;
      headers.forEach(h=>{preview+=`<th style="padding:4px 8px">${esc(h)}</th>`});
      preview+=`</tr></thead><tbody>`;
      rows.slice(0,5).forEach(r=>{
        preview+=`<tr>`;
        r.forEach(c=>{preview+=`<td style="padding:4px 8px">${esc((c||'').substring(0,40))}</td>`});
        preview+=`</tr>`;
      });
      if(rows.length>5)preview+=`<tr><td colspan="${headers.length}" style="padding:4px 8px;color:var(--text-ghost)">... and ${rows.length-5} more rows</td></tr>`;
      preview+=`</tbody></table>`;
      document.getElementById('import-preview').innerHTML=preview;
      document.getElementById('import-go').style.display=matched>0?'':'none';
      if(!matched)toast('No columns matched. Check your CSV headers.','error');
    });
  };
  reader.readAsText(file);
}

function executeImport(table){
  if(!_importData||!_importData.rows.length){toast('No data to import','error');return}
  const ep=table==='songs'?'/api/songs/import':'/api/directory/import';
  toast(`Importing ${_importData.rows.length} records...`);
  document.getElementById('prompt-modal')?.remove();
  fetch(ep,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({headers:_importData.headers,rows:_importData.rows})
  }).then(r=>r.json()).then(d=>{
    if(d.success){toast(`Imported ${d.imported} records`);_importData=null;if(typeof reload==='function')reload()}
    else toast(d.error||'Import failed','error');
  });
}

// ==================== FEATURE: EMAIL TEMPLATE LIBRARY ====================
const DEFAULT_TEMPLATES={
  'Cold Outreach':{
    subject:'New Music from {{artist}} — ROLLON Toplines',
    body:`I wanted to share a new record that I think could be a great fit for what you're working on.`
  },
  'Follow Up':{
    subject:'Following up — ROLLON Toplines',
    body:`Just circling back on the tracks I sent over recently. Would love to know if anything landed well or if there's a different direction I can send through.`
  },
  'Sync Pitch':{
    subject:'Sync opportunity — ROLLON Catalog',
    body:`I have some tracks that I think could work well for sync placement. The masters and publishing are fully cleared and available for licensing.`
  },
  'Writing Trip':{
    subject:'Writing trip — {{city}} {{date}}',
    body:`I'm putting together a writing trip and wanted to reach out about potential sessions. Would any of your writers be available? Happy to share recent work.`
  },
  'EMMMA Singles 2026':{
    subject:'New EMMMA single — Honey',
    body:`EMMMA just dropped her new single "Honey" and I think she'd be a brilliant fit for your roster. She's got a UK headline tour coming up across four cities in late April / early May.`
  }
};

function getTemplates(){
  // Synchronous fallback to localStorage (async API fetch happens in showTemplateLibrary)
  try{const saved=localStorage.getItem('rollon_email_templates');
    if(saved)return JSON.parse(saved)}catch(e){}
  return {...DEFAULT_TEMPLATES};
}
function saveTemplates(templates){
  localStorage.setItem('rollon_email_templates',JSON.stringify(templates));
  // Also save to Google Sheets API
  Object.entries(templates).forEach(([name,t])=>{
    fetch('/api/templates/save',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:name,subject:t.subject||'',body:t.body||'',type:t.type||''})
    }).catch(()=>{});
  });
}

function showTemplateLibrary(onSelect){
  // Try API first, fall back to localStorage
  fetch('/api/templates').then(r=>r.json()).then(d=>{
    const apiTemplates=d.templates||{};
    const local=getTemplates();
    // Merge: API wins, then local, then defaults
    const templates={...DEFAULT_TEMPLATES,...local,...apiTemplates};
    // Sync to localStorage for offline
    localStorage.setItem('rollon_email_templates',JSON.stringify(templates));
    _renderTemplateLibrary(templates,onSelect);
  }).catch(()=>{
    _renderTemplateLibrary(getTemplates(),onSelect);
  });
}

function _renderTemplateLibrary(templates,onSelect){
  let html=`<div class="prompt-overlay" id="prompt-modal"><div class="prompt-box" style="max-width:650px">`;
  html+=`<h3>Email Templates</h3>`;
  html+=`<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">`;
  Object.keys(templates).forEach(name=>{
    html+=`<button class="btn btn-sm" onclick="selectTemplate('${escA(name)}')">${esc(name)}</button>`;
  });
  html+=`<button class="btn btn-sm" onclick="newTemplate()" style="color:var(--accent)">+ New</button>`;
  html+=`</div>`;
  html+=`<div id="tpl-edit" style="display:none">`;
  html+=`<input id="tpl-name" class="prompt-input" placeholder="Template name" style="margin-bottom:6px">`;
  html+=`<input id="tpl-subject" class="prompt-input" placeholder="Subject line" style="margin-bottom:6px">`;
  html+=`<textarea id="tpl-body" class="prompt-input" rows="10" style="font-size:12px;line-height:1.6" placeholder="Email body..."></textarea>`;
  html+=`<p style="font-size:10px;color:var(--text-ghost);margin-top:4px">This text becomes the bespoke paragraph in your pitch email. The greeting, playlist link, and sign-off are added automatically.</p>`;
  html+=`</div>`;
  html+=`<div id="tpl-preview" style="display:none;background:var(--bg-deep);padding:12px;border-radius:var(--r-md);font-size:12px;line-height:1.6;white-space:pre-wrap;max-height:250px;overflow:auto"></div>`;
  html+=`<div class="prompt-actions">`;
  html+=`<button class="btn" onclick="document.getElementById('prompt-modal')?.remove()">Close</button>`;
  html+=`<button class="btn" id="tpl-save-btn" style="display:none" onclick="saveCurrentTemplate()">Save Template</button>`;
  html+=`<button class="btn" id="tpl-delete-btn" style="display:none;color:var(--danger)" onclick="deleteCurrentTemplate()">Delete</button>`;
  html+=`<button class="btn btn-accent" id="tpl-use-btn" style="display:none" onclick="useCurrentTemplate()">Use This Template</button>`;
  html+=`</div></div></div>`;
  document.body.insertAdjacentHTML('beforeend',html);
  window._tplOnSelect=onSelect;
  window._tplCurrent=null;
}

function selectTemplate(name){
  const templates=getTemplates();const t=templates[name];if(!t)return;
  window._tplCurrent=name;
  document.getElementById('tpl-edit').style.display='block';
  document.getElementById('tpl-name').value=name;
  document.getElementById('tpl-subject').value=t.subject||'';
  document.getElementById('tpl-body').value=t.body||'';
  document.getElementById('tpl-save-btn').style.display='';
  document.getElementById('tpl-delete-btn').style.display=DEFAULT_TEMPLATES[name]?'none':'';
  document.getElementById('tpl-use-btn').style.display='';
  // Preview
  const preview=document.getElementById('tpl-preview');
  preview.style.display='block';
  preview.innerHTML=`<strong>Subject:</strong> ${esc(t.subject)}\n\n${esc(t.body)}`;
}

function newTemplate(){
  window._tplCurrent=null;
  document.getElementById('tpl-edit').style.display='block';
  document.getElementById('tpl-name').value='';
  document.getElementById('tpl-subject').value='';
  document.getElementById('tpl-body').value='';
  document.getElementById('tpl-save-btn').style.display='';
  document.getElementById('tpl-delete-btn').style.display='none';
  document.getElementById('tpl-use-btn').style.display='none';
  document.getElementById('tpl-preview').style.display='none';
  document.getElementById('tpl-name').focus();
}

function saveCurrentTemplate(){
  const name=document.getElementById('tpl-name').value.trim();
  if(!name){toast('Template needs a name','error');return}
  fetch('/api/templates/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name,subject:document.getElementById('tpl-subject').value,body:document.getElementById('tpl-body').value})
  }).then(r=>r.json()).then(d=>{
    if(d.success){toast('Template saved: '+name);document.getElementById('prompt-modal')?.remove();showTemplateLibrary(window._tplOnSelect)}
    else toast(d.error||'Save failed','error');
  }).catch(()=>{
    // Fallback to localStorage
    const templates=getTemplates();
    templates[name]={subject:document.getElementById('tpl-subject').value,body:document.getElementById('tpl-body').value};
    saveTemplates(templates);toast('Template saved locally: '+name);
    document.getElementById('prompt-modal')?.remove();showTemplateLibrary(window._tplOnSelect);
  });
}

function deleteCurrentTemplate(){
  const name=document.getElementById('tpl-name').value.trim();
  fetch('/api/templates/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name})
  }).then(r=>r.json()).then(()=>{
    // Also remove from localStorage
    const templates=getTemplates();delete templates[name];
    localStorage.setItem('rollon_email_templates',JSON.stringify(templates));
    toast('Deleted: '+name);
    document.getElementById('prompt-modal')?.remove();
    showTemplateLibrary(window._tplOnSelect);
  }).catch(()=>{
    const templates=getTemplates();delete templates[name];saveTemplates(templates);
    toast('Deleted locally: '+name);
    document.getElementById('prompt-modal')?.remove();showTemplateLibrary(window._tplOnSelect);
  });
}

function useCurrentTemplate(){
  const subject=document.getElementById('tpl-subject').value;
  const body=document.getElementById('tpl-body').value;
  document.getElementById('prompt-modal')?.remove();
  if(typeof window._tplOnSelect==='function')window._tplOnSelect({subject,body});
}

// ==================== FEATURE: ACTIVITY TIMELINE ====================
function renderActivityTimeline(record,headers){
  const events=[];
  // Pull from date fields with context
  const outreachH=headers.find(h=>cleanH(h).toLowerCase().includes('last outreach'));
  const notesH=headers.find(h=>cleanH(h).toLowerCase().includes('outreach notes'));
  const createdH=headers.find(h=>cleanH(h).toLowerCase()==='created');
  const modifiedH=headers.find(h=>cleanH(h).toLowerCase()==='last modified');
  const tagsH=headers.find(h=>cleanH(h).toLowerCase()==='tags'||cleanH(h).toLowerCase()==='tag');

  if(createdH&&record[createdH])events.push({date:record[createdH],type:'created',text:'Record created'});
  if(outreachH&&record[outreachH])events.push({date:record[outreachH],type:'outreach',text:'Last outreach logged'});
  if(modifiedH&&record[modifiedH])events.push({date:record[modifiedH],type:'modified',text:'Record modified'});

  // Parse outreach notes for dated entries (common format: "MM/DD/YY text" or "**MM/DD/YY** text")
  if(notesH&&record[notesH]){
    const notes=record[notesH]||'';
    const datePattern=/(?:\*\*)?(\d{1,2}\/\d{1,2}\/\d{2,4})(?:\*\*)?\s*[-:]?\s*(.*)/g;
    let match;
    while((match=datePattern.exec(notes))!==null){
      events.push({date:match[1],type:'note',text:match[2].substring(0,120)||(match[2]||'Note')});
    }
  }

  // Sort newest first
  events.sort((a,b)=>{
    const da=new Date(a.date),db=new Date(b.date);
    return (isNaN(db)?0:db)-(isNaN(da)?0:da);
  });

  if(!events.length)return '<div style="color:var(--text-ghost);font-size:12px;padding:8px">No activity history yet.</div>';

  const icons={created:'🆕',outreach:'📧',modified:'✏️',note:'📝'};
  let html='<div class="activity-timeline">';
  events.forEach(ev=>{
    html+=`<div class="timeline-event"><span class="timeline-icon">${icons[ev.type]||'•'}</span><span class="timeline-date">${esc(ev.date)}</span><span class="timeline-text">${esc(ev.text)}</span></div>`;
  });
  html+='</div>';
  return html;
}

// Deselect cell when clicking outside the grid
document.addEventListener('click',e=>{
  if(_selectedCell&&!e.target.closest('.data-grid')&&!e.target.closest('.col-menu')&&!e.target.closest('.prompt-overlay')){
    cellDeselect();
  }
});

// Connection health check (every 60s)
setInterval(()=>{
  const dot=document.getElementById('conn-status');if(!dot)return;
  fetch('/api/config',{method:'GET'}).then(r=>{
    if(r.ok){dot.classList.remove('offline');dot.title='Connected'}
    else{dot.classList.add('offline');dot.title='Connection issue'}
  }).catch(()=>{dot.classList.add('offline');dot.title='Offline'});
},60000);

// ==================== KEYBOARD SHORTCUTS HELP ====================
function showShortcutsHelp(){
  const shortcuts=[
    {key:'↑ ↓ ← →',desc:'Navigate between cells'},
    {key:'Enter',desc:'Edit selected cell'},
    {key:'Escape',desc:'Deselect / cancel edit'},
    {key:'Tab / Shift+Tab',desc:'Move right / left'},
    {key:'Cmd+C',desc:'Copy cell value'},
    {key:'Cmd+V',desc:'Paste into cell'},
    {key:'Cmd+Z',desc:'Undo last edit'},
    {key:'Cmd+K',desc:'Command palette'},
    {key:'Delete',desc:'Clear selected cell'},
    {key:'Type any letter',desc:'Start editing with that character'},
    {key:'?',desc:'Show this help'},
    {key:'Cmd+N',desc:'New record'},
    {key:'Cmd+F',desc:'Focus search'},
    {key:'Cmd+S',desc:'Save current view'},
  ];
  let html='<div class="prompt-overlay" id="shortcuts-help" onclick="this.remove()"><div class="prompt-box" style="max-width:500px" onclick="event.stopPropagation()">';
  html+='<h3 style="margin-bottom:12px">Keyboard Shortcuts</h3>';
  shortcuts.forEach(s=>{
    html+=`<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)"><span style="font-family:var(--font-m);font-size:12px;color:var(--accent);min-width:140px">${s.key}</span><span style="font-size:12px;color:var(--text-dim)">${s.desc}</span></div>`;
  });
  html+='<div class="prompt-actions" style="margin-top:12px"><button class="btn" onclick="document.getElementById(\'shortcuts-help\')?.remove()">Close</button></div>';
  html+='</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
}

// Add ? key and Cmd+N, Cmd+F, Cmd+S shortcuts
document.addEventListener('keydown',e=>{
  const tag=document.activeElement?.tagName;
  if(tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT')return;
  if(e.key==='?'&&!e.metaKey&&!e.ctrlKey){e.preventDefault();showShortcutsHelp()}
  if((e.metaKey||e.ctrlKey)&&e.key==='n'){e.preventDefault();const p=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);if(p&&p.newRecord)p.newRecord()}
  if((e.metaKey||e.ctrlKey)&&e.key==='f'){e.preventDefault();const si=document.getElementById('search-input');if(si)si.focus()}
  if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();const p=typeof S!=='undefined'?S:(typeof D!=='undefined'?D:null);if(p&&p.saveView)p.saveView();else toast('View auto-saved')}
});

// ---- DUPLICATE FINDER ----
function openDuplicateFinder(){
  const table=window._currentTable==='songs'?'Songs':'Personnel';
  const defaultFields=table==='Songs'?['Title','Songwriter Credits']:['Name','Email'];
  const allCols=(table==='Songs'?(typeof S!=='undefined'?S.allCols:[]):(typeof D!=='undefined'?D.allCols:[]));

  let html='<div style="padding:16px">';
  html+='<div style="display:flex;gap:12px;margin-bottom:16px;align-items:center">';
  html+='<select id="dupe-table" onchange="dupeSwitchTable()" style="padding:6px 10px;border:1px solid var(--border);border-radius:var(--r-sm);background:var(--bg-raised);color:var(--text);font-size:12px">';
  html+='<option value="Songs"'+(table==='Songs'?' selected':'')+'>Songs</option>';
  html+='<option value="Personnel"'+(table==='Personnel'?' selected':'')+'>Personnel</option></select>';
  html+='<select id="dupe-mode" style="padding:6px 10px;border:1px solid var(--border);border-radius:var(--r-sm);background:var(--bg-raised);color:var(--text);font-size:12px">';
  html+='<option value="exact">Exact Match</option><option value="similar">Similar</option><option value="fuzzy">Fuzzy</option></select>';
  html+='<button class="btn btn-accent" onclick="runDupeScan()">Scan</button></div>';

  // Field checkboxes
  html+='<div id="dupe-fields" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">';
  const cols=allCols.length?allCols:defaultFields;
  cols.forEach(c=>{
    const checked=defaultFields.some(d=>d.toLowerCase()===c.toLowerCase());
    html+='<label style="font-size:11px;color:var(--text-muted);display:flex;align-items:center;gap:4px"><input type="checkbox" value="'+escA(c)+'"'+(checked?' checked':'')+'>'+esc(c)+'</label>';
  });
  html+='</div>';
  html+='<div id="dupe-results" style="color:var(--text-ghost);font-size:12px">Select fields and click Scan to find duplicates.</div>';
  html+='</div>';
  openModal('Duplicate Finder',html);
}

function dupeSwitchTable(){
  const t=document.getElementById('dupe-table').value;
  const defaults=t==='Songs'?['Title','Songwriter Credits']:['Name','Email'];
  document.querySelectorAll('#dupe-fields input').forEach(cb=>{
    cb.checked=defaults.some(d=>d.toLowerCase()===cb.value.toLowerCase());
  });
}

function runDupeScan(){
  const table=document.getElementById('dupe-table').value;
  const mode=document.getElementById('dupe-mode').value;
  const fields=[];
  document.querySelectorAll('#dupe-fields input:checked').forEach(cb=>fields.push(cb.value));
  if(!fields.length){toast('Select at least one field','error');return}
  const el=document.getElementById('dupe-results');
  el.innerHTML='<div class="spinner"></div> Scanning...';
  fetch('/api/duplicates',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({table,fields,mode})
  }).then(r=>r.json()).then(d=>{
    if(d.error){el.innerHTML='<span style="color:var(--danger)">'+esc(d.error)+'</span>';return}
    if(!d.groups?.length){el.innerHTML='<div style="color:var(--success);font-weight:600">No duplicates found!</div>';return}
    let html='<div style="font-weight:600;margin-bottom:12px;color:var(--accent)">'+d.total_groups+' duplicate groups ('+d.total_dupes+' records)</div>';
    d.groups.slice(0,50).forEach(g=>{
      html+='<div style="border:1px solid var(--border);border-radius:var(--r-md);margin-bottom:8px;overflow:hidden">';
      html+='<div style="padding:8px 12px;background:var(--bg-hover);font-weight:600;font-size:12px;display:flex;justify-content:space-between;cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\'">';
      html+='<span>'+g.count+' RECORDS: '+esc(g.label)+'</span><span style="color:var(--text-ghost)">\u25BC</span></div>';
      html+='<div style="display:none;padding:8px">';
      g.records.forEach((r,i)=>{
        const ri=r._row_index;
        html+='<div style="padding:6px;border-bottom:1px solid var(--border-subtle);font-size:11px;display:flex;justify-content:space-between;align-items:center">';
        html+='<span style="cursor:pointer;color:var(--accent)" onclick="closeModal();openRecord('+ri+',\''+(table==='Songs'?'songs':'directory')+'\')">Row '+ri+': ';
        // Show key fields
        const name=r.Title||r.Name||'';
        const email=r.Email||'';
        html+=esc(name);if(email)html+=' ('+esc(email)+')';
        html+='</span>';
        if(i>0)html+='<button class="btn btn-sm" style="color:var(--danger);font-size:10px" onclick="deleteDupeRow('+ri+',\''+table+'\')">Archive</button>';
        html+='</div>';
      });
      html+='</div></div>';
    });
    el.innerHTML=html;
  });
}

function deleteDupeRow(ri,table){
  if(!confirm('Archive row '+ri+'? It will be recoverable from Settings > Archive.'))return;
  fetch('/api/bulk-delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({table,row_indices:[ri]})
  }).then(r=>r.json()).then(d=>{
    if(d.success){toast('Row '+ri+' archived (recoverable)');runDupeScan()}
    else toast(d.error||'Failed','error');
  });
}

// Session timeout warning (6 hours)
const _sessionStart=Date.now();
setInterval(()=>{
  const hours=(Date.now()-_sessionStart)/3600000;
  if(hours>5.5&&hours<5.6){toast('Session expires in 30 minutes. Save your work.')}
  if(hours>6){toast('Session may have expired. Please refresh or log in again.','error')}
},60000);
