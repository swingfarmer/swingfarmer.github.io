/* =============================================
   스윙파머 슬롯 매니저 (sf-slots.js) v1
   
   사용법:
   1. 페이지에서 CALC_KEY 정의
   2. window.slGetState = function(){ return {...} }
   3. window.slSetState = function(data){ ... }
   4. <script src="/sf-slots.js?v=1"></script>
   
   자동 제공:
   - localStorage 자동저장/복원
   - Firebase 클라우드 멀티슬롯
   - 내보내기/가져오기 (JSON)
   - 드래그 순서변경
   - 이름수정, 덮어쓰기, 삭제
   ============================================= */
(function(){
'use strict';

// ── 필수 체크 ──
if(typeof window.CALC_KEY==='undefined'){
  console.warn('[sf-slots] CALC_KEY 미정의 — 슬롯 비활성');
  return;
}
const KEY = window.CALC_KEY;
const LS_KEY = 'sf_'+KEY+'_v2';
const ADMIN_UID = '1JrHgD2bpTRjrS2jw7MbpHciBph1';
const $ = id => document.getElementById(id);

// ── localStorage 자동저장 ──
function autoSave(){
  try{
    if(window.slGetState) localStorage.setItem(LS_KEY, JSON.stringify(window.slGetState()));
  }catch(e){}
}
function autoLoad(){
  try{
    const d = localStorage.getItem(LS_KEY);
    if(d && window.slSetState) window.slSetState(JSON.parse(d));
  }catch(e){}
}

// input/select 변경 시 자동저장
document.addEventListener('DOMContentLoaded', function(){
  autoLoad();
  document.querySelectorAll('input, select, textarea').forEach(function(el){
    el.addEventListener('input', autoSave);
    el.addEventListener('change', autoSave);
  });
});

// ── Firebase Firestore (lazy load) ──
let _db = null;
async function getDb(){
  if(_db) return _db;
  const [appMod, fsMod] = await Promise.all([
    import('https://www.gstatic.com/firebasejs/12.14.0/firebase-app.js'),
    import('https://www.gstatic.com/firebasejs/12.14.0/firebase-firestore.js')
  ]);
  const cfg = {apiKey:'AIzaSyB-Ynu-KdYL4sqPers2XnPt5dEEsKsXvMY',authDomain:'swingfarmer-board01.firebaseapp.com',projectId:'swingfarmer-board01',storageBucket:'swingfarmer-board01.firebasestorage.app',messagingSenderId:'312575044644',appId:'1:312575044644:web:81d754eb1d90f25454fcb1'};
  const apps = appMod.getApps();
  const app = apps.length ? apps[0] : appMod.initializeApp(cfg);
  _db = fsMod.getFirestore(app);
  _db._fsMod = fsMod;
  return _db;
}

function docRef(db){ return db._fsMod.doc(db, 'calc_data', ADMIN_UID); }

async function loadSlots(){
  try{
    const db = await getDb();
    const s = await db._fsMod.getDoc(docRef(db));
    if(s.exists() && s.data()[KEY] && Array.isArray(s.data()[KEY].slots))
      return s.data()[KEY].slots;
  }catch(e){ console.error('[sf-slots] load:', e); }
  return [];
}

async function saveSlots(slots){
  const db = await getDb();
  const ref = docRef(db);
  let ex = {};
  try{ const s = await db._fsMod.getDoc(ref); if(s.exists()) ex = s.data(); }catch(e){}
  ex[KEY] = { slots, updatedAt: new Date().toISOString() };
  await db._fsMod.setDoc(ref, ex, { merge: true });
}

// ── 슬롯 데이터 ──
let _slots = [];

// ── UI: 모달 주입 ──
function injectModal(){
  if($('sfSlotOverlay')) return;

  const overlay = document.createElement('div');
  overlay.id = 'sfSlotOverlay';
  overlay.innerHTML = `
<div id="sfSlotSheet">
  <div class="sfs-header">
    <div class="sfs-title">저장 관리</div>
    <button class="sfs-close" onclick="window._sfSlots.close()" aria-label="닫기">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
    </button>
  </div>

  <div class="sfs-save-new">
    <input type="text" id="sfsNewName" placeholder="이름 입력 (예: 시나리오 A)" maxlength="40">
    <button id="sfsSaveBtn" class="sfs-btn-save">저장</button>
  </div>

  <div class="sfs-toolbar">
    <button onclick="window._sfSlots.exportAll()" class="sfs-tool-btn" title="전체 내보내기">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2v8M4 6l4-4 4 4M3 12h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      전체 내보내기
    </button>
    <button onclick="window._sfSlots.importFile()" class="sfs-tool-btn" title="전체 가져오기">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 10V2M4 6l4 4 4-4M3 12h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      전체 가져오기
    </button>
    <input type="file" id="sfsImportInput" accept=".json" style="display:none">
  </div>

  <div id="sfsSlotList" class="sfs-slot-list"></div>

  <div class="sfs-footer">
    <span id="sfsCount">0개 저장됨</span>
  </div>
</div>`;

  document.body.appendChild(overlay);

  // 이벤트
  overlay.addEventListener('click', function(e){ if(e.target === overlay) window._sfSlots.close(); });
  $('sfsSaveBtn').addEventListener('click', doSave);
  $('sfsNewName').addEventListener('keydown', function(e){ if(e.key==='Enter') doSave(); });
  $('sfsImportInput').addEventListener('change', handleImport);
}

// ── CSS 주입 ──
function injectStyles(){
  if(document.getElementById('sfSlotsCSS')) return;
  const s = document.createElement('style');
  s.id = 'sfSlotsCSS';
  s.textContent = `
#sfSlotOverlay{position:fixed;inset:0;background:rgba(0,0,0,.4);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);z-index:10000;display:none;align-items:flex-end;justify-content:center;padding:0}
#sfSlotOverlay.open{display:flex}
#sfSlotSheet{background:#fff;width:100%;max-width:480px;max-height:85vh;border-radius:16px 16px 0 0;display:flex;flex-direction:column;animation:sfsSlideUp .3s ease;box-shadow:0 -4px 40px rgba(0,0,0,.15)}
@keyframes sfsSlideUp{from{transform:translateY(100%);opacity:0}to{transform:translateY(0);opacity:1}}
@media(min-width:600px){#sfSlotSheet{border-radius:16px;margin-bottom:40px;max-height:70vh}}

.sfs-header{display:flex;align-items:center;padding:20px 20px 12px;border-bottom:1px solid #f0f0f0}
.sfs-title{flex:1;font-size:18px;font-weight:700;color:#1a1a1a;letter-spacing:-.3px}
.sfs-close{background:none;border:none;padding:6px;cursor:pointer;color:#999;border-radius:50%;transition:background .15s}
.sfs-close:hover{background:#f0f0f0;color:#333}

.sfs-save-new{display:flex;gap:8px;padding:16px 20px 12px}
.sfs-save-new input{flex:1;padding:10px 14px;border:1.5px solid #e0e0e0;border-radius:10px;font-size:14px;font-family:inherit;background:#fafafa;transition:border-color .15s,background .15s;outline:none}
.sfs-save-new input:focus{border-color:#007AFF;background:#fff}
.sfs-btn-save{background:#007AFF;color:#fff;border:none;border-radius:10px;padding:10px 20px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;white-space:nowrap;transition:background .15s}
.sfs-btn-save:hover{background:#0066D6}
.sfs-btn-save:active{background:#004EA3;transform:scale(.97)}
.sfs-btn-save:disabled{background:#ccc;cursor:default;transform:none}

.sfs-toolbar{display:flex;gap:6px;padding:0 20px 12px;border-bottom:1px solid #f0f0f0}
.sfs-tool-btn{display:flex;align-items:center;gap:4px;background:none;border:1px solid #e0e0e0;border-radius:8px;padding:6px 12px;font-size:12px;font-weight:600;color:#666;cursor:pointer;font-family:inherit;transition:all .15s}
.sfs-tool-btn:hover{border-color:#007AFF;color:#007AFF}
.sfs-tool-btn svg{flex-shrink:0}

.sfs-slot-list{flex:1;overflow-y:auto;padding:8px 12px;min-height:120px}
.sfs-slot-list::after{content:'';display:block;height:350px}
.sfs-empty{text-align:center;padding:40px 20px;color:#999;font-size:14px}

.sfs-slot{display:flex;align-items:center;gap:8px;padding:12px;margin:4px 0;border-radius:12px;background:#fafafa;border:1px solid #f0f0f0;transition:all .15s;cursor:default}
.sfs-slot:hover{background:#f5f7fa;border-color:#e0e0e0}
.sfs-slot.sfs-focus{background:#eef4ff;border-color:#007AFF;box-shadow:0 0 0 2px rgba(0,122,255,.15)}

.sfs-order{display:flex;flex-direction:column;gap:1px;flex-shrink:0}
.sfs-order button{width:24px;height:16px;border:none;border-radius:3px;background:#f0f0f0;color:#999;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:9px;padding:0;transition:all .12s;line-height:1}
.sfs-order button:hover{background:#007AFF;color:#fff}
.sfs-order button:disabled{opacity:.15;cursor:default;background:#f0f0f0;color:#999}

.sfs-slot-info{flex:1;min-width:0}
.sfs-slot-name{font-size:14px;font-weight:600;color:#1a1a1a;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sfs-slot-time{font-size:11px;color:#999;margin-top:2px}

.sfs-slot-actions{display:flex;gap:4px;flex-shrink:0}
.sfs-act{width:32px;height:32px;border:none;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;transition:all .12s;background:transparent}
.sfs-act:hover{transform:scale(1.1)}
.sfs-act.load{background:#007AFF;color:#fff;width:auto;padding:0 12px;font-size:12px;font-weight:600;border-radius:8px}
.sfs-act.load:hover{background:#0066D6}
.sfs-act.overwrite{background:#f0fdf4;color:#16a34a}
.sfs-act.overwrite:hover{background:#dcfce7}
.sfs-act.export{background:#f0f4ff;color:#007AFF}
.sfs-act.export:hover{background:#dde8ff}
.sfs-act.rename{background:#f0f0f0;color:#666}
.sfs-act.rename:hover{background:#e5e5e5}
.sfs-act.delete{background:#fff;color:#dc2626}
.sfs-act.delete:hover{background:#fef2f2}

.sfs-footer{padding:12px 20px;border-top:1px solid #f0f0f0;text-align:center}
.sfs-footer span{font-size:12px;color:#999}

`;
  document.head.appendChild(s);
}

// ── 렌더링 ──
var _focusIdx = -1; // 이동 후 하이라이트할 인덱스

function render(){
  const box = $('sfsSlotList');
  const count = $('sfsCount');
  count.textContent = _slots.length + '개 저장됨';

  if(!_slots.length){
    box.innerHTML = '<div class="sfs-empty">저장된 항목이 없어요.<br>위에서 이름을 입력하고 저장하세요.</div>';
    _focusIdx = -1;
    return;
  }

  const len = _slots.length;
  box.innerHTML = _slots.map(function(s, i){
    const t = s.savedAt ? fmtDate(s.savedAt) : '';
    const focused = (i === _focusIdx) ? ' sfs-focus' : '';
    return '<div class="sfs-slot'+focused+'" data-idx="'+i+'">'
      + '<div class="sfs-order">'
      + '<button onclick="window._sfSlots.moveTop('+i+')" title="맨 위로"'+(i===0?' disabled':'')+'>⏫</button>'
      + '<button onclick="window._sfSlots.moveUp('+i+')" title="위로"'+(i===0?' disabled':'')+'>▲</button>'
      + '<button onclick="window._sfSlots.moveDown('+i+')" title="아래로"'+(i>=len-1?' disabled':'')+'>▼</button>'
      + '<button onclick="window._sfSlots.moveBottom('+i+')" title="맨 아래로"'+(i>=len-1?' disabled':'')+'>⏬</button>'
      + '</div>'
      + '<div class="sfs-slot-info"><div class="sfs-slot-name">'+ esc(s.name||'(이름없음)') +'</div><div class="sfs-slot-time">'+t+'</div></div>'
      + '<div class="sfs-slot-actions">'
      + '<button class="sfs-act rename" onclick="window._sfSlots.rename('+i+')" title="이름 수정">✏️</button>'
      + '<button class="sfs-act overwrite" onclick="window._sfSlots.overwrite('+i+')" title="현재 값으로 덮어쓰기">💾</button>'
      + '<button class="sfs-act export" onclick="window._sfSlots.exportOne('+i+')" title="내보내기">📤</button>'
      + '<button class="sfs-act load" onclick="window._sfSlots.load('+i+')">불러오기</button>'
      + '<button class="sfs-act delete" onclick="window._sfSlots.del('+i+')" title="삭제">🗑️</button>'
      + '</div></div>';
  }).join('');

  // 이동 후 해당 슬롯으로 스크롤 + 하이라이트 유지
  if(_focusIdx >= 0 && _focusIdx < len){
    var el = box.querySelector('[data-idx="'+_focusIdx+'"]');
    if(el) el.scrollIntoView({ block:'nearest', behavior:'smooth' });
  }
}

function esc(s){ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

function fmtDate(iso){
  const d = new Date(iso);
  const y = d.getFullYear();
  const m = String(d.getMonth()+1).padStart(2,'0');
  const dd = String(d.getDate()).padStart(2,'0');
  const hh = String(d.getHours()).padStart(2,'0');
  const mm = String(d.getMinutes()).padStart(2,'0');
  return y+'.'+m+'.'+dd+' '+hh+':'+mm;
}

// ── 액션들 ──
async function doSave(){
  const nameInput = $('sfsNewName');
  const btn = $('sfsSaveBtn');
  const name = nameInput.value.trim();
  if(!name){ nameInput.focus(); return; }

  const existing = _slots.findIndex(function(s){ return s.name === name; });
  if(existing >= 0 && !confirm('"'+name+'" 이미 있어요. 덮어쓸까요?')) return;

  btn.disabled = true;
  btn.textContent = '저장 중…';
  try{
    const entry = { name: name, data: window.slGetState(), savedAt: new Date().toISOString() };
    if(existing >= 0) _slots[existing] = entry;
    else _slots.push(entry);
    await saveSlots(_slots);
    _focusIdx = -1;
    render();
    nameInput.value = '';
  }catch(e){
    alert('저장 실패: ' + e.message);
  }
  btn.disabled = false;
  btn.textContent = '저장';
}

// ── 공개 API ──
window._sfSlots = {
  open: async function(){
    if(!window._sfAuth || !window._sfAuth.currentUser || window._sfAuth.currentUser.uid !== ADMIN_UID){
      alert('관리자 로그인이 필요합니다.');
      return;
    }
    injectStyles();
    injectModal();
    $('sfSlotOverlay').classList.add('open');
    $('sfsSlotList').innerHTML = '<div class="sfs-empty">불러오는 중…</div>';
    _slots = await loadSlots();
    _focusIdx = -1;
    render();
  },

  close: function(){
    const o = $('sfSlotOverlay');
    if(o) o.classList.remove('open');
  },

  load: function(i){
    const s = _slots[i];
    if(!s) return;
    if(!confirm('"'+s.name+'" 불러올까요?\n현재 입력값이 바뀝니다.')) return;
    window.slSetState(s.data);
    autoSave();
    this.close();
    if(typeof window.calculate === 'function') window.calculate();
  },

  del: async function(i){
    if(!confirm('삭제할까요?')) return;
    try{
      _slots.splice(i, 1);
      await saveSlots(_slots);
      _focusIdx = -1;
      render();
    }catch(e){ alert('삭제 실패: '+e.message); }
  },

  rename: async function(i){
    const nn = prompt('이름 수정', _slots[i].name || '');
    if(nn === null) return;
    const t = nn.trim();
    if(!t) return;
    try{
      _slots[i].name = t;
      await saveSlots(_slots);
      render();
    }catch(e){ alert('수정 실패: '+e.message); }
  },

  moveUp: async function(i){
    if(i <= 0) return;
    var list = $('sfsSlotList');
    var slotEl = list.querySelector('[data-idx="'+i+'"]');
    var h = slotEl ? slotEl.offsetHeight + 8 : 0; // slot height + margin
    var item = _slots.splice(i, 1)[0];
    _slots.splice(i-1, 0, item);
    _focusIdx = i-1;
    render();
    if(h) list.scrollTop = Math.max(0, list.scrollTop - h);
    try{ await saveSlots(_slots); }catch(e){ alert('순서 저장 실패: '+e.message); }
  },

  moveDown: async function(i){
    if(i >= _slots.length-1) return;
    var list = $('sfsSlotList');
    var slotEl = list.querySelector('[data-idx="'+i+'"]');
    var h = slotEl ? slotEl.offsetHeight + 8 : 0;
    var item = _slots.splice(i, 1)[0];
    _slots.splice(i+1, 0, item);
    _focusIdx = i+1;
    render();
    if(h) list.scrollTop += h;
    try{ await saveSlots(_slots); }catch(e){ alert('순서 저장 실패: '+e.message); }
  },

  moveTop: async function(i){
    if(i <= 0) return;
    var item = _slots.splice(i, 1)[0];
    _slots.splice(0, 0, item);
    _focusIdx = 0;
    render();
    try{ await saveSlots(_slots); }catch(e){ alert('순서 저장 실패: '+e.message); }
  },

  moveBottom: async function(i){
    if(i >= _slots.length-1) return;
    var item = _slots.splice(i, 1)[0];
    _slots.push(item);
    _focusIdx = _slots.length-1;
    render();
    try{ await saveSlots(_slots); }catch(e){ alert('순서 저장 실패: '+e.message); }
  },

  overwrite: async function(i){
    const s = _slots[i];
    if(!s) return;
    if(!confirm('"'+s.name+'" 현재 값으로 덮어쓸까요?')) return;
    try{
      _slots[i] = { name: s.name, data: window.slGetState(), savedAt: new Date().toISOString() };
      await saveSlots(_slots);
      render();
    }catch(e){ alert('덮어쓰기 실패: '+e.message); }
  },

  exportOne: function(i){
    var s = _slots[i];
    if(!s) return;
    var pageTitle = document.title.replace(/[^\w가-힣\s-]/g,'').trim().replace(/\s+/g,'_') || KEY;
    var slotName = (s.name||'unnamed').replace(/[^\w가-힣\s-]/g,'').trim().replace(/\s+/g,'_');
    var d = new Date(s.savedAt || Date.now());
    var ts = d.getFullYear()+String(d.getMonth()+1).padStart(2,'0')+String(d.getDate()).padStart(2,'0')+'_'+String(d.getHours()).padStart(2,'0')+String(d.getMinutes()).padStart(2,'0');
    var fname = pageTitle + '_' + slotName + '_' + ts + '.json';
    const blob = new Blob([JSON.stringify({ calcKey: KEY, pageTitle: document.title, slots: [s], exportedAt: new Date().toISOString() }, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = fname;
    a.click();
    URL.revokeObjectURL(a.href);
  },

  exportAll: function(){
    if(!_slots.length){ alert('내보낼 데이터가 없어요.'); return; }
    var pageTitle = document.title.replace(/[^\w가-힣\s-]/g,'').trim().replace(/\s+/g,'_') || KEY;
    var now = new Date();
    var ts = now.getFullYear()+String(now.getMonth()+1).padStart(2,'0')+String(now.getDate()).padStart(2,'0')+'_'+String(now.getHours()).padStart(2,'0')+String(now.getMinutes()).padStart(2,'0');
    var fname = pageTitle + '_전체_' + _slots.length + '개_' + ts + '.json';
    const blob = new Blob([JSON.stringify({ calcKey: KEY, pageTitle: document.title, slots: _slots, exportedAt: now.toISOString() }, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = fname;
    a.click();
    URL.revokeObjectURL(a.href);
  },

  importFile: function(){
    $('sfsImportInput').click();
  }
};

async function handleImport(e){
  const file = e.target.files[0];
  if(!file) return;
  try{
    const text = await file.text();
    const json = JSON.parse(text);
    let imported = [];
    if(Array.isArray(json.slots)) imported = json.slots;
    else if(Array.isArray(json)) imported = json;
    else { alert('올바른 형식이 아닙니다.'); return; }

    if(!imported.length){ alert('가져올 데이터가 없어요.'); return; }

    const mode = confirm(imported.length + '개 항목 발견.\n\n확인 = 기존에 추가 (병합)\n취소 = 기존 전체 교체');
    if(mode){
      // 병합 — 이름 중복 시 덮어쓰기
      imported.forEach(function(item){
        const idx = _slots.findIndex(function(s){ return s.name === item.name; });
        if(idx >= 0) _slots[idx] = item;
        else _slots.push(item);
      });
    } else {
      _slots = imported;
    }
    await saveSlots(_slots);
    render();
    alert('가져오기 완료!');
  }catch(err){
    alert('가져오기 실패: ' + err.message);
  }
  e.target.value = '';
}

// ── 트리거 버튼 자동 주입 ──
// 페이지에 #sfSlotTrigger가 없으면 자동으로 생성
document.addEventListener('DOMContentLoaded', function(){
  // 기존 버튼이 있으면 연결만
  const existing = $('sfSlotTrigger') || $('btnCloudOpen');
  if(existing){
    existing.addEventListener('click', function(){ window._sfSlots.open(); });
    return;
  }

  // 없으면 플로팅 버튼 생성
  const fab = document.createElement('button');
  fab.id = 'sfSlotTrigger';
  fab.innerHTML = '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 14l4-4L3 6M10 14h7M10 10h7M10 6h7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  fab.title = '저장 관리';
  fab.setAttribute('style', 'position:fixed;bottom:80px;right:16px;z-index:9000;width:48px;height:48px;border-radius:50%;background:#007AFF;color:#fff;border:none;cursor:pointer;box-shadow:0 4px 16px rgba(0,122,255,.35);display:flex;align-items:center;justify-content:center;transition:all .2s');
  fab.addEventListener('mouseenter', function(){ fab.style.transform='scale(1.08)'; });
  fab.addEventListener('mouseleave', function(){ fab.style.transform='scale(1)'; });
  fab.addEventListener('click', function(){ window._sfSlots.open(); });
  document.body.appendChild(fab);
});

})();
