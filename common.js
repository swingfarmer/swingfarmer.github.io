/* ============================================
   스윙파머 공통 스크립트 (common.js) v7
   - 인증 게이트 (Firebase Auth, 관리자 전용)
   - 상단 고정 헤더 (메인 링크 + 글자크기 + 다크모드)
   - 다크모드 (localStorage 저장)
   - 글자크기 4단계 (작게/기본/크게/더크게)
   사용법: 각 페이지 <head> 또는 <body> 끝에
   <script src="/common.js"></script> 한 줄 추가
   ============================================ */

/* ── 관리자 UID (사이트 전체에서 여기 한 곳만 고침) ──
   auth-guard.js · sf-slots.js · 이 파일 · VM api_server.py 가 모두 이 줄을 읽음.
   UID를 바꾸거나 추가하면: 이 줄 수정 → 전 페이지 common.js ?v= 올림 → VM git pull (api_server는 다음 요청부터 자동 반영).
   첫 번째 UID = 저장 슬롯(Firestore calc_data/{UID}) 위치. 순서 바꾸면 기존 저장 슬롯이 안 보임. */
window.SF_ADMIN_UIDS = Object.freeze(['1JrHgD2bpTRjrS2jw7MbpHciBph1','Ydd8v6LCN2TPjkqKD4DejLSWwaL2']);

/* ── 인증 게이트 (눈가림) ── */
/* ── Firebase 초기화 (공용) ── */
var _sfFirebaseReady = (function(){
  var ADMIN_UIDS = window.SF_ADMIN_UIDS;
  var FB_CFG = {apiKey:'AIzaSyB-Ynu-KdYL4sqPers2XnPt5dEEsKsXvMY',authDomain:'swingfarmer-board01.firebaseapp.com',projectId:'swingfarmer-board01'};
  var _auth = null;
  var _resolve;
  var _promise = new Promise(function(r){ _resolve = r; });

  window._sfAuth = null;  // 외부 접근용

  return {
    promise: _promise,
    init: function(mods) {
      var initializeApp = mods[0].initializeApp, getApps = mods[0].getApps;
      var getAuth = mods[1].getAuth;
      var app = getApps().length ? getApps()[0] : initializeApp(FB_CFG);
      _auth = getAuth(app);
      window._sfAuth = _auth;
      _resolve(_auth);
      return { auth: _auth, mods: mods, ADMIN_UIDS: ADMIN_UIDS, FB_CFG: FB_CFG };
    }
  };
})();

/* ── API 토큰 부착 fetch (공용) ── */
window.sfApiFetch = function(url, opts) {
  opts = opts || {};
  var method = (opts.method || 'GET').toUpperCase();

  // GET은 토큰 불필요
  if (method === 'GET') {
    return fetch(url, opts).then(function(r) {
      return r.json().then(function(d) { return {ok: r.ok, status: r.status, data: d}; });
    });
  }

  // POST/PUT/DELETE: Firebase ID Token 부착
  if (!window._sfAuth || !window._sfAuth.currentUser) {
    return Promise.resolve({ok: false, status: 401, data: {error: '로그인 필요'}});
  }

  return window._sfAuth.currentUser.getIdToken().then(function(token) {
    opts.headers = opts.headers || {};
    opts.headers['Authorization'] = 'Bearer ' + token;
    return fetch(url, opts).then(function(r) {
      return r.json().then(function(d) { return {ok: r.ok, status: r.status, data: d}; });
    });
  });
};

(function(){
  var ADMIN_UIDS = window.SF_ADMIN_UIDS;

  // 이미 인증된 세션 체크
  var cached = false;
  try { cached = sessionStorage.getItem('sf_authed') === '1'; } catch(e){}

  // 캐시 안 됐으면 게이트 오버레이 삽입
  if (!cached) {
    var overlay = document.createElement('div');
    overlay.id = 'sf-auth-gate';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:999999;background:rgba(245,247,250,0.97);display:flex;align-items:center;justify-content:center;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,sans-serif';
    overlay.innerHTML = '<div style="text-align:center;max-width:360px;padding:40px">'
      + '<div style="font-size:48px;margin-bottom:16px">🔒</div>'
      + '<div style="font-size:20px;font-weight:800;color:#1F4E78;margin-bottom:8px">스윙파머 금융도구</div>'
      + '<div style="font-size:14px;color:#666;margin-bottom:24px;line-height:1.6">개인 전용 공간입니다.<br>관리자 로그인이 필요합니다.</div>'
      + '<button id="sf-gate-login" style="background:#1F4E78;color:#fff;border:none;padding:14px 32px;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;box-shadow:0 2px 10px rgba(31,78,120,0.3)">🔑 Google 로그인</button>'
      + '<div id="sf-gate-msg" style="margin-top:16px;font-size:13px;color:#dc2626;display:none"></div>'
      + '</div>';
    if (document.body) document.body.appendChild(overlay);
    else document.addEventListener('DOMContentLoaded', function(){ document.body.appendChild(overlay); });
  }

  // Firebase 항상 로드 (게이트 + API 토큰 둘 다 필요)
  Promise.all([
    import('https://www.gstatic.com/firebasejs/12.14.0/firebase-app.js'),
    import('https://www.gstatic.com/firebasejs/12.14.0/firebase-auth.js')
  ]).then(function(mods){
    var fb = _sfFirebaseReady.init(mods);
    var auth = fb.auth;
    var onAuthStateChanged = mods[1].onAuthStateChanged;
    var GoogleAuthProvider = mods[1].GoogleAuthProvider, signInWithPopup = mods[1].signInWithPopup;

    function unlock(){
      try { sessionStorage.setItem('sf_authed','1'); } catch(e){}
      var g = document.getElementById('sf-auth-gate');
      if(g) g.style.display = 'none';
    }
    function showErr(msg){
      var m = document.getElementById('sf-gate-msg');
      if(m){ m.textContent = msg; m.style.display = 'block'; }
    }

    onAuthStateChanged(auth, function(user){
      if(user && ADMIN_UIDS.indexOf(user.uid) !== -1){ unlock(); }
      else if(user && !cached){ showErr('관리자 계정이 아닙니다. (' + (user.email||'') + ')'); }
    });

    // 게이트 로그인 버튼 (캐시 안 됐을 때만)
    if (!cached) {
      var provider = new GoogleAuthProvider();
      provider.setCustomParameters({ prompt: 'select_account' });
      function bindLogin(){
        var btn = document.getElementById('sf-gate-login');
        if(!btn) return;
        btn.addEventListener('click', function(){
          btn.textContent = '로그인 중...'; btn.disabled = true;
          signInWithPopup(auth, provider).catch(function(e){
            btn.textContent = '🔑 Google 로그인'; btn.disabled = false;
            if(e.code !== 'auth/popup-closed-by-user') showErr('로그인 실패: ' + e.message);
          });
        });
      }
      if(document.getElementById('sf-gate-login')) bindLogin();
      else document.addEventListener('DOMContentLoaded', bindLogin);
    }
  }).catch(function(e){
    console.warn('Auth gate: Firebase load failed', e);
    var g = document.getElementById('sf-auth-gate');
    if(g) g.style.display = 'none';
  });
})();

(function () {
  'use strict';

  var MAIN_URL = '/';

  // ---------- 1. 공통 스타일 주입 ----------
  var css = `
  :root {
    --sf-font-scale: 1;
  }
  /* 헤더 높이만큼 본문 밀기 */
  body { padding-top: 56px !important; }

  /* === 공통 헤더 === */
  #sf-header {
    position: fixed; top: 0; left: 0; right: 0; height: 56px; z-index: 99999;
    background: #1F4E78; color: #fff;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Malgun Gothic', sans-serif;
  }
  #sf-header .sf-logo {
    display: flex; align-items: center; gap: 8px;
    color: #fff; text-decoration: none; font-weight: 800; font-size: 17px;
    letter-spacing: -0.3px; cursor: pointer;
  }
  #sf-header .sf-logo:hover { opacity: 0.85; }
  #sf-header .sf-logo .sf-logo-icon {
    width: 28px; height: 28px; display: block; flex-shrink: 0;
  }
  #sf-header .sf-tools { display: flex; align-items: center; gap: 6px; }
  #sf-header .sf-btn {
    background: rgba(255,255,255,0.14); border: none; color: #fff;
    width: 36px; height: 36px; border-radius: 8px; cursor: pointer;
    font-size: 15px; display: flex; align-items: center; justify-content: center;
    transition: background 0.15s; padding: 0; line-height: 1;
    text-decoration: none;
  }
  #sf-header .sf-btn:hover { background: rgba(255,255,255,0.28); }
  #sf-header .sf-btn.wide { width: auto; padding: 0 10px; font-size: 13px; font-weight: 600; gap: 4px; }
  #sf-header .sf-fontsize { display: flex; align-items: center; gap: 3px; background: rgba(255,255,255,0.1); border-radius: 8px; padding: 3px; }
  #sf-header .sf-fontsize button {
    background: transparent; border: none; color: #fff; cursor: pointer;
    width: 30px; height: 30px; border-radius: 6px; font-weight: 700;
    display: flex; align-items: center; justify-content: center; padding: 0;
    transition: background 0.15s;
  }
  #sf-header .sf-fontsize button:hover { background: rgba(255,255,255,0.2); }
  #sf-header .sf-fontsize button.active { background: #fff; color: #1F4E78; }
  #sf-header .sf-fontsize .sf-a-sm { font-size: 11px; }
  #sf-header .sf-fontsize .sf-a-md { font-size: 14px; }
  #sf-header .sf-fontsize .sf-a-lg { font-size: 17px; }
  #sf-header .sf-fontsize .sf-a-xl { font-size: 20px; }
  #sf-header .sf-fontsize .sf-divider { font-size: 12px; opacity: 0.4; }

  @media (max-width: 600px) {
    #sf-header { padding: 0 10px; }
    #sf-header .sf-logo { font-size: 15px; }
    #sf-header .sf-btn.label-hide span.txt { display: none; }
    #sf-header .sf-fontsize .sf-a-lg { display: none; }
  }

  /* 글자크기 - body zoom (헤더는 고정 크기 유지) */
  #sf-content-zoom { }

  /* ── 브레드크럼 ── */
  #sf-breadcrumb {
    max-width: var(--sf-max-w, 960px); margin: 0 auto; padding: 6px 20px 0;
    font-size: 12px; color: #888; line-height: 1.5;
  }
  #sf-breadcrumb a { color: #1F4E78; text-decoration: none; }
  #sf-breadcrumb a:hover { text-decoration: underline; }
  #sf-breadcrumb .sf-bc-sep { margin: 0 5px; opacity: 0.5; }
  #sf-breadcrumb .sf-bc-cur { color: #333; font-weight: 600; }
  body.sf-dark #sf-breadcrumb { color: #71717a; }
  body.sf-dark #sf-breadcrumb a { color: #60a5fa; }
  body.sf-dark #sf-breadcrumb .sf-bc-cur { color: #e4e4e7; }
  @media (max-width: 600px) { #sf-breadcrumb { padding: 4px 12px 0; font-size: 11px; } }

  /* ============ 다크모드 ============ */
  body.sf-dark {
    background: #14181f !important;
    color: #d8dde5 !important;
  }
  body.sf-dark .panel,
  body.sf-dark .card,
  body.sf-dark .section,
  body.sf-dark .category,
  body.sf-dark .content,
  body.sf-dark .selector-box,
  body.sf-dark .case-info,
  body.sf-dark .stat,
  body.sf-dark .crash-card,
  body.sf-dark .manual,
  body.sf-dark .summary-grid > *,
  body.sf-dark .link-card,
  body.sf-dark .stock-item {
    background: #1e242e !important;
    color: #d8dde5 !important;
    border-color: #2c333f !important;
  }
  body.sf-dark h1, body.sf-dark h2, body.sf-dark h3 {
    color: #6ba3e0 !important;
    border-color: #6ba3e0 !important;
  }
  body.sf-dark .card-title,
  body.sf-dark .stat-value,
  body.sf-dark .stock-name { color: #6ba3e0 !important; }
  body.sf-dark .desc,
  body.sf-dark .card-desc,
  body.sf-dark .panel-sub,
  body.sf-dark .cat-desc,
  body.sf-dark .stat-label,
  body.sf-dark .stock-note,
  body.sf-dark p { color: #aab3c0 !important; }
  body.sf-dark a { color: #6ba3e0; }
  body.sf-dark .back-link { color: #6ba3e0 !important; }
  body.sf-dark input,
  body.sf-dark select,
  body.sf-dark textarea {
    background: #2a313d !important;
    color: #e8ecf2 !important;
    border-color: #3a4250 !important;
  }
  body.sf-dark table th { background: #2a4a6e !important; }
  body.sf-dark table td { border-color: #2c333f !important; }
  body.sf-dark table tr:nth-child(even) { background: #232a35 !important; }
  body.sf-dark .info-box { background: #1a2c42 !important; color: #aac7e8 !important; }
  body.sf-dark .disclaimer { background: #1e242e !important; color: #aab3c0 !important; border-color: #2c333f !important; }
  body.sf-dark .tag { background: #2a313d !important; color: #aab3c0 !important; }
  /* 그라데이션 컬러 카드는 살짝 어둡게 */
  body.sf-dark .card.large[style*="gradient"] { filter: brightness(0.85); }
  /* 검은 위젯 띠는 그대로 둠 */

  /* 다크 토글된 헤더 표시 */
  body.sf-dark #sf-header { background: #11151b; box-shadow: 0 2px 8px rgba(0,0,0,0.4); }

  /* === 금액 한글표기 (data-won 마커) === */
  .sf-won-kor { font-size: 12px; color: #1F4E78; font-weight: 600; margin-top: 3px; min-height: 15px; line-height: 1.4; }
  body.sf-dark .sf-won-kor { color: #6ba3e0; }
  `;

  // 검색엔진 색인 차단 (전 페이지 공통)
  if (!document.querySelector('meta[name="robots"]')) {
    var nx = document.createElement('meta'); nx.name = 'robots'; nx.content = 'noindex,nofollow';
    document.head.appendChild(nx);
  }

  var styleEl = document.createElement('style');
  styleEl.id = 'sf-common-style';
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  // ---------- 2. 헤더 DOM 생성 ----------
  function buildHeader() {
    var header = document.createElement('div');
    header.id = 'sf-header';
    header.innerHTML =
      '<a class="sf-logo" href="' + MAIN_URL + '">' +
        '<svg class="sf-logo-icon" viewBox="0 0 32 32" aria-hidden="true"><rect x="0.5" y="0.5" width="31" height="31" rx="6" fill="#FFFFFF" stroke="#CBD5E1"/><g stroke="#E2E8F0" stroke-width="1"><line x1="9" y1="9" x2="27" y2="9"/><line x1="9" y1="15" x2="27" y2="15"/><line x1="9" y1="21" x2="27" y2="21"/></g><g stroke="#94A3B8" stroke-width="1.4" stroke-linecap="round"><line x1="6" y1="5" x2="6" y2="26"/><line x1="6" y1="26" x2="27" y2="26"/><line x1="4" y1="9" x2="6" y2="9"/><line x1="4" y1="15" x2="6" y2="15"/><line x1="4" y1="21" x2="6" y2="21"/></g><path d="M 8.5 22 L 13.5 16 L 18 19 L 26 8.5" stroke="#16A34A" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>' +  // 091: 📈 이모지 → favicon.svg와 같은 그림(기기마다 이모지 모양 달라서)
        '<span>스윙파머</span>' +
      '</a>' +
      '<div class="sf-tools">' +
        '<div class="sf-fontsize" title="글자 크기">' +
          '<button class="sf-a-sm" data-size="0.9" title="작게">A</button>' +
          '<button class="sf-a-md" data-size="1" title="기본">A</button>' +
          '<button class="sf-a-lg" data-size="1.2" title="크게">A</button>' +
          '<button class="sf-a-xl" data-size="1.4" title="더 크게">A</button>' +
        '</div>' +
        '<button class="sf-btn" id="sf-dark-toggle" title="다크모드">🌙</button>' +
      '</div>';
    document.body.insertBefore(header, document.body.firstChild);
  }

  // ---------- 3. 다크모드 ----------
  function applyDark(on) {
    if (on) {
      document.body.classList.add('sf-dark');
      var t = document.getElementById('sf-dark-toggle');
      if (t) t.textContent = '☀️';
    } else {
      document.body.classList.remove('sf-dark');
      var t2 = document.getElementById('sf-dark-toggle');
      if (t2) t2.textContent = '🌙';
    }
    syncChartTheme();
  }

  // ---------- 3-1. 차트(Chart.js) 테마 연동 (078) ----------
  // 페이지 코드를 안 고치고 공통에서 처리: 다크/라이트에 맞춰 축 글씨·격자선 색을 바꾸고,
  // 배경에 묻히는 선 색(다크에서 아주 어두운 색, 라이트에서 아주 밝은 회색)만 보정.
  // 빨강·파랑 등 의미가 있는 색은 건드리지 않음. 원래 색은 기억해 뒀다가 테마를 되돌리면 복원.
  var CH_STORE = (typeof WeakMap !== 'undefined') ? new WeakMap() : null;
  var chartPluginDone = false;
  var chDefOrig = null;
  // 페이지가 원래 다크로 만들어졌는지 (common-dark.css 사용). 원래 테마일 때는 페이지가 정한 색을 그대로 두고,
  // 반대 테마로 바뀌었을 때만 보정함.
  function chNativeDark() { return !!document.querySelector('link[href*="common-dark.css"]'); }

  function chParse(s) {
    if (typeof s !== 'string') return null;
    s = s.trim().toLowerCase();
    var m;
    if (s === 'white') s = '#ffffff'; else if (s === 'black') s = '#000000';
    if ((m = s.match(/^#([0-9a-f]{3,8})$/))) {
      var h = m[1];
      if (h.length === 3 || h.length === 4) h = h.replace(/./g, '$&$&');
      if (h.length !== 6 && h.length !== 8) return null;
      return { r: parseInt(h.substr(0, 2), 16), g: parseInt(h.substr(2, 2), 16), b: parseInt(h.substr(4, 2), 16),
               a: h.length === 8 ? parseInt(h.substr(6, 2), 16) / 255 : 1 };
    }
    if ((m = s.match(/^rgba?\(([^)]+)\)$/))) {
      var p = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
      if (p.length < 3 || p.some(isNaN)) return null;
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    }
    return null;
  }
  function chLum(c) {
    function f(v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  function chSat(c) {
    var mx = Math.max(c.r, c.g, c.b) / 255, mn = Math.min(c.r, c.g, c.b) / 255;
    if (mx === mn) return 0;
    var l = (mx + mn) / 2;
    return (mx - mn) / (l > 0.5 ? (2 - mx - mn) : (mx + mn));
  }
  function chOut(r, g, b, a) {
    r = Math.round(r); g = Math.round(g); b = Math.round(b);
    return a < 1 ? 'rgba(' + r + ',' + g + ',' + b + ',' + (Math.round(a * 100) / 100) + ')' : 'rgb(' + r + ',' + g + ',' + b + ')';
  }
  // kind: 'text'(축·범례 글씨) / 'grid'(격자·축선) / 'data'(데이터 선·막대) / 'backdrop'(레이더 눈금 배경)
  function chThemed(val, kind, dark) {
    var c = chParse(val);
    if (!c) return val;
    var neutral = chSat(c) < 0.2, L = chLum(c);
    if (kind === 'backdrop') return dark ? 'rgba(0,0,0,0)' : val;
    if (kind === 'text') {
      if (neutral) return dark ? '#aab3c0' : '#555555';
      if (dark && L < 0.14) return chOut(c.r + (255 - c.r) * 0.55, c.g + (255 - c.g) * 0.55, c.b + (255 - c.b) * 0.55, c.a);
      return val;
    }
    if (kind === 'grid') {
      if (c.a === 0 || !neutral) return val;
      return dark ? 'rgba(255,255,255,0.09)' : 'rgba(0,0,0,0.08)';
    }
    // data
    if (dark && L < 0.14) {
      if (neutral) return chOut(200, 206, 216, c.a);
      return chOut(c.r + (255 - c.r) * 0.55, c.g + (255 - c.g) * 0.55, c.b + (255 - c.b) * 0.55, c.a);
    }
    if (!dark && neutral && L > 0.75 && c.a >= 0.5) return chOut(85, 85, 85, c.a);
    return val;
  }
  function chSlot(store, obj, key, kind, dark, id, keepOrig) {
    if (!obj) return;
    var cur = obj[key];
    if (typeof cur !== 'string' && !Array.isArray(cur)) return;
    var rec = store[id];
    var same = rec && (Array.isArray(cur) ? (Array.isArray(rec.applied) && cur.join('|') === rec.applied.join('|')) : cur === rec.applied);
    if (!same) rec = store[id] = { orig: Array.isArray(cur) ? cur.slice() : cur, applied: null };   // 페이지가 값을 새로 넣은 경우
    var next = keepOrig ? (Array.isArray(rec.orig) ? rec.orig.slice() : rec.orig)
      : Array.isArray(rec.orig)
        ? rec.orig.map(function (v) { return typeof v === 'string' ? chThemed(v, kind, dark) : v; })
        : chThemed(rec.orig, kind, dark);
    rec.applied = next;
    obj[key] = next;
  }
  function chApply(chart) {
    if (!CH_STORE || !chart || !chart.config) return;
    var dark = document.body.classList.contains('sf-dark');
    var nat = (dark === chNativeDark());
    var store = CH_STORE.get(chart);
    if (!store) { store = {}; CH_STORE.set(chart, store); }
    var opt = chart.config.options || {};
    var scales = opt.scales || {};
    Object.keys(scales).forEach(function (id) {
      var s = scales[id];
      if (!s || typeof s !== 'object') return;
      chSlot(store, s.ticks, 'color', 'text', dark, 's.' + id + '.ticks', nat);
      chSlot(store, s.ticks, 'backdropColor', 'backdrop', dark, 's.' + id + '.backdrop', nat);
      chSlot(store, s.title, 'color', 'text', dark, 's.' + id + '.title', nat);
      chSlot(store, s.pointLabels, 'color', 'text', dark, 's.' + id + '.pl', nat);
      chSlot(store, s.grid, 'color', 'grid', dark, 's.' + id + '.grid', nat);
      chSlot(store, s.border, 'color', 'grid', dark, 's.' + id + '.border', nat);
      chSlot(store, s.angleLines, 'color', 'grid', dark, 's.' + id + '.angle', nat);
    });
    var pl = opt.plugins || {};
    if (pl.legend) chSlot(store, pl.legend.labels, 'color', 'text', dark, 'legend', nat);
    chSlot(store, pl.title, 'color', 'text', dark, 'title', nat);
    chSlot(store, pl.subtitle, 'color', 'text', dark, 'subtitle', nat);
    var dsl = (chart.config.data && chart.config.data.datasets) || [];
    dsl.forEach(function (ds, i) {
      if (!ds) return;
      ['borderColor', 'backgroundColor', 'pointBackgroundColor', 'pointBorderColor'].forEach(function (k) {
        // 원형 차트의 흰 구분선 등은 그대로 둠 (다크에서만 어두운 색 보정)
        chSlot(store, ds, k, 'data', dark, 'd.' + i + '.' + k, nat);
      });
    });
  }
  function chDefaults() {
    var C = window.Chart;
    if (!C || !C.defaults) return;
    var dark = document.body.classList.contains('sf-dark');
    if (!chDefOrig) chDefOrig = { color: C.defaults.color, borderColor: C.defaults.borderColor };
    if (dark === chNativeDark()) {          // 원래 테마 → 페이지/라이브러리 기본값 그대로
      C.defaults.color = chDefOrig.color;
      C.defaults.borderColor = chDefOrig.borderColor;
      return;
    }
    C.defaults.color = dark ? '#aab3c0' : '#555555';
    C.defaults.borderColor = dark ? 'rgba(255,255,255,0.09)' : 'rgba(0,0,0,0.08)';
  }
  function chEach(fn) {
    var C = window.Chart;
    if (!C || !C.instances) return;
    Object.keys(C.instances).forEach(function (k) { try { fn(C.instances[k]); } catch (e) {} });
  }
  function setupChartTheme() {
    var C = window.Chart;
    if (!C || !C.register || chartPluginDone) return !!chartPluginDone;
    chartPluginDone = true;
    chDefaults();
    try {
      // 차트가 만들어지거나 갱신될 때마다 현재 테마 색을 입힘
      C.register({ id: 'sfTheme', beforeUpdate: function (chart) { try { chApply(chart); } catch (e) {} } });
    } catch (e) {}
    chEach(function (ch) { ch.update('none'); });   // 이미 그려진 차트
    return true;
  }
  window.sfSyncChartTheme = function () { syncChartTheme(); };   // 페이지에서 직접 부를 일이 있을 때용
  function syncChartTheme() {
    if (!window.Chart) return;
    if (!chartPluginDone) { setupChartTheme(); return; }
    chDefaults();
    chEach(function (ch) { ch.update('none'); });
  }

  // ---------- 3-2. 넘치는 표 가로 스크롤 (078) ----------
  // 표가 화면보다 넓은데 가로 스크롤 영역이 없으면 표만 감싸서 스크롤되게 함 (주로 모바일).
  // 실제로 넘칠 때만 동작하고, 이미 스크롤되는 상자 안에 있으면 건드리지 않음.
  function fixTableOverflow() {
    var tables = document.querySelectorAll('table');
    for (var i = 0; i < tables.length; i++) {
      var tb = tables[i], par = tb.parentElement;
      if (!par || par.classList.contains('sf-table-scroll') || tb.closest('#sf-header, .sf-no-scroll-wrap')) continue;
      if (tb.offsetParent === null) continue;                 // 숨겨진 탭 안의 표는 보일 때 다시 검사
      if (tb.scrollWidth <= par.clientWidth + 1) continue;    // 안 넘침
      var el = par, scrolls = false;
      for (var d = 0; el && d < 4 && el !== document.body; d++, el = el.parentElement) {
        var ox = getComputedStyle(el).overflowX;
        if (ox === 'auto' || ox === 'scroll') { scrolls = true; break; }
      }
      if (scrolls) continue;
      var wrap = document.createElement('div');
      wrap.className = 'sf-table-scroll';
      wrap.style.cssText = 'overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%';   // 다크 전용 페이지는 common.css를 안 써서 직접 지정
      par.insertBefore(wrap, tb);
      wrap.appendChild(tb);
    }
  }
  function setupTableOverflow() {
    var timer = null;
    function run() { clearTimeout(timer); timer = setTimeout(fixTableOverflow, 250); }
    run();
    window.addEventListener('resize', run);
    window.addEventListener('load', run);
    document.addEventListener('click', run);                  // 탭 전환 등으로 표가 새로 보일 때
    if (typeof MutationObserver !== 'undefined') {
      new MutationObserver(run).observe(document.body, { childList: true, subtree: true });
    }
  }

  // ---------- 4. 글자크기 (px 측정 방식 - 검증됨) ----------
  var sfBaseSizes = null;
  function cacheBaseSizes() {
    if (sfBaseSizes) return;
    sfBaseSizes = [];
    var sel = 'p, li, td, th, span, a, label, h1, h2, h3, h4, .card-title, .card-desc, .desc, .subtitle, .tag, .stat-value, .stat-label, .stock-name, .stock-note, .cat-desc, .panel-sub, input, select, button, blockquote';
    var nodes = document.querySelectorAll(sel);
    nodes.forEach(function (el) {
      if (el.closest && el.closest('#sf-header')) return;
      var px = parseFloat(window.getComputedStyle(el).fontSize);
      if (px) sfBaseSizes.push({el: el, base: px});
    });
  }
  function applyFontSize(scale) {
    scale = parseFloat(scale) || 1;
    document.documentElement.style.setProperty('--sf-font-scale', scale);
    cacheBaseSizes();
    sfBaseSizes.forEach(function (item) {
      item.el.style.fontSize = (item.base * scale) + 'px';
    });
    var btns = document.querySelectorAll('#sf-header .sf-fontsize button');
    btns.forEach(function (b) {
      b.classList.toggle('active', parseFloat(b.getAttribute('data-size')) === scale);
    });
  }

  // ---------- 4-B. 금액 한글표기 엔진 (data-won 마커) ----------
  // 사용법: 금액 input에 data-won 만 추가하면 바로 아래에 "1억 2,000만원" 자동 표기.
  //   - 원 단위 입력:   <input ... data-won>
  //   - 만원 단위 입력: <input ... data-won="man">
  //   - 위치를 직접 지정하려면: <div class="sf-won-kor" data-won-for="입력칸id"></div>
  function wonToKorean(n) {
    n = Math.round(Math.abs(n));
    if (!n) return '';
    var eok = Math.floor(n / 100000000);
    var man = Math.floor((n % 100000000) / 10000);
    var won = n % 10000;
    var parts = [];
    if (eok > 0) parts.push(eok.toLocaleString('ko-KR') + '억');
    if (man > 0) parts.push(man.toLocaleString('ko-KR') + '만');
    if (won > 0) parts.push(won.toLocaleString('ko-KR'));
    return parts.join(' ') + '원';
  }
  function sfReadVal(input) {
    var raw = (input.value || '').replace(/[^0-9.\-]/g, '');
    var v = parseFloat(raw);
    if (isNaN(v)) return 0;
    if (input.getAttribute('data-won') === 'man') v *= 10000; // 만원 단위
    return v;
  }
  function sfHintFor(input) {
    // 1) 명시적 위치 지정(data-won-for) 우선
    if (input.id) {
      var ex = document.querySelector('.sf-won-kor[data-won-for="' + input.id + '"]');
      if (ex) return ex;
    }
    // 2) 이미 만든 것 재사용
    if (input.__sfHint) return input.__sfHint;
    // 3) input 바로 뒤에 자동 생성
    var hint = document.createElement('div');
    hint.className = 'sf-won-kor';
    if (input.nextSibling) input.parentNode.insertBefore(hint, input.nextSibling);
    else input.parentNode.appendChild(hint);
    input.__sfHint = hint;
    return hint;
  }
  function sfAttachWon(input) {
    if (input.__sfWonBound) return;
    input.__sfWonBound = true;
    var upd = function () { sfHintFor(input).textContent = wonToKorean(sfReadVal(input)); };
    input.addEventListener('input', upd);
    input.addEventListener('change', upd);
    upd();
  }
  function initWonReadout() {
    document.querySelectorAll('input[data-won]').forEach(sfAttachWon);
  }
  // 동적으로 input을 추가하는 페이지는 새 input 생긴 뒤 window.sfRefreshWon() 호출
  window.sfRefreshWon = initWonReadout;
  window.wonToKorean = wonToKorean;

  // ---------- 4-C. 브레드크럼 (자동 섹션 표시) ----------
  var SF_SECTIONS = {
    'news':'📰 정보·시장', 'correlation':'📰 정보·시장', 'indicators':'📰 정보·시장',
    'dashboard':'📰 정보·시장', 'market':'📰 정보·시장', 'crash-history':'📰 정보·시장',
    'macro':'📰 정보·시장', 'quotes':'📰 정보·시장', 'events':'📰 정보·시장',
    'books':'📰 정보·시장', 'data':'📰 정보·시장', 'rates':'📰 정보·시장',
    'breadth':'📰 정보·시장', 'krx':'📰 정보·시장', 'research':'📰 정보·시장',
    'heatmap':'📰 정보·시장', 'today':'📰 정보·시장',
    'free':'💰 자산·연금·파이어', 'pension':'💰 자산·연금·파이어', 'gold-calc':'💰 자산·연금·파이어',
    'assets':'💰 자산·연금·파이어', 'wealth-reports':'💰 자산·연금·파이어',
    'barbell':'💰 자산·연금·파이어', 'budget':'💰 자산·연금·파이어',
    'fire':'💰 자산·연금·파이어', 'cashflow':'💰 자산·연금·파이어',
    'stock-tools':'📈 주식·투자', 'price-compare':'📈 주식·투자', 'leverage-backtester':'📈 주식·투자',
    'risk':'📈 주식·투자', 'target-simple':'📈 주식·투자', 'target-price':'📈 주식·투자',
    'avg':'📈 주식·투자', 'us-dividend':'📈 주식·투자', 'dividend-calendar':'📈 주식·투자',
    'dividend-manager':'📈 주식·투자', 'screener':'📈 주식·투자', 'margin-ratio':'📈 주식·투자',
    'sector':'📈 주식·투자', 'momentum':'📈 주식·투자', 'similar':'📈 주식·투자',
    'strategy':'📈 주식·투자', 'valuation':'📈 주식·투자', 'return-calc':'📈 주식·투자',
    'portfolio':'🔒 개인 관리', 'rebalancing':'📈 주식·투자', 'futures':'📈 주식·투자',
    'hdsteel':'📈 주식·투자', 'hd-enc':'📈 주식·투자', 'kr-finance':'📈 주식·투자', 'etf':'📈 주식·투자', 'bond':'📈 주식·투자',
    'property':'🏠 부동산', 'realestate':'🏠 부동산', 'realestate-tracker':'🏠 부동산',
    'redevelopment':'🏠 부동산', 'landtax':'💸 세금', 'gambuk':'💸 세금',
    'tax':'💸 세금', 'corp-tax':'💸 세금', 'annual-check':'🧮 금융·생활', 'tax-calendar':'💸 세금',
    'salary':'💼 근로·회사', 'severance':'💼 근로·회사', 'severance-exec':'💼 근로·회사',
    'paygrowth':'💼 근로·회사', 'workout':'🧮 금융·생활',
    'finance-tools':'🧮 금융·생활', 'loan-switch':'🧮 금융·생활', 'insurance4':'💼 근로·회사',
    'car-compare':'🧮 금융·생활', 'telecom':'🧮 금융·생활', 'health':'🧮 금융·생활',
    'card-manager':'🧮 금융·생활', 'company':'💼 근로·회사', 'commerce':'🏠 부동산',
    'schedule':'🧮 금융·생활', 'status':'🔒 개인 관리', 'community':'🔒 개인 관리',
    'notes':'🔒 개인 관리', 'webtoon':'🔒 개인 관리', 'asset-notes':'🔒 개인 관리'
  };
  function buildBreadcrumb() {
    var path = location.pathname.replace(/\/$/,'') || '/';
    if (path === '/' || path === '/1808') return; // 메인·전체메뉴는 생략
    var parts = path.split('/').filter(Boolean);
    var sec = SF_SECTIONS[parts[0]];
    if (!sec) return;
    var title = document.title.replace(/\s*[\|·\-–—]\s*스윙파머.*$/i,'').trim();
    var bc = document.createElement('div');
    bc.id = 'sf-breadcrumb';
    var html = '<a href="/">🏠 메인</a><span class="sf-bc-sep">›</span>';
    html += '<span>' + sec + '</span>';
    if (title && title.length < 40) {
      html += '<span class="sf-bc-sep">›</span><span class="sf-bc-cur">' + title + '</span>';
    }
    bc.innerHTML = html;
    // 헤더 바로 다음에 삽입
    var header = document.getElementById('sf-header');
    if (header && header.nextSibling) {
      header.parentNode.insertBefore(bc, header.nextSibling);
    }
  }

  // ---------- 5. 초기화 + 이벤트 ----------
  function init() {
    buildHeader();
    buildBreadcrumb();

    // 저장된 설정 불러오기
    var savedSize = '1';
    try {
      var savedDark = localStorage.getItem('sf-dark');
      if (savedDark === '1') applyDark(true);
      var s = localStorage.getItem('sf-fontsize');
      if (s) savedSize = s;
    } catch (e) {}

    // 글자크기 적용 (저장값 또는 기본). 콘텐츠 로딩 후 측정되도록 지연.
    setTimeout(function () { applyFontSize(savedSize); }, 300);

    // 금액 한글표기 (data-won 마커가 있는 페이지만 작동)
    initWonReadout();

    // 차트 테마 연동: Chart.js가 늦게 로드되는 페이지도 있어 잠깐 동안 기다림
    if (!setupChartTheme()) {
      var chTries = 0;
      var chTimer = setInterval(function () {
        if (setupChartTheme() || ++chTries > 40) clearInterval(chTimer);
      }, 250);
    }
    // 넘치는 표 가로 스크롤
    setupTableOverflow();

    // 아이폰·아이패드: 입력칸(16px 미만 글씨)을 누르면 화면이 자동 확대되는 것 방지.
    // 손가락 두 개로 확대하는 건 iOS에서 계속 됨. 안드로이드·PC는 건드리지 않음.
    try {
      var ua = navigator.userAgent || '';
      var isIOS = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
      if (isIOS) {
        var vp = document.querySelector('meta[name="viewport"]');
        if (vp && !/maximum-scale/.test(vp.content)) vp.content = vp.content + ', maximum-scale=1';
      }
    } catch (e) {}

    // 다크모드 토글
    var darkBtn = document.getElementById('sf-dark-toggle');
    darkBtn.addEventListener('click', function () {
      var isDark = document.body.classList.contains('sf-dark');
      applyDark(!isDark);
      try { localStorage.setItem('sf-dark', !isDark ? '1' : '0'); } catch (e) {}
    });

    // 글자크기
    var sizeBtns = document.querySelectorAll('#sf-header .sf-fontsize button');
    sizeBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var scale = btn.getAttribute('data-size');
        applyFontSize(scale);
        try { localStorage.setItem('sf-fontsize', scale); } catch (e) {}
      });
    });
  }

  // ---------- 6. 탭/필터 상태 저장·복원 (전역) ----------
  var SF_TP = 'sf-tp-';
  var TP_ATTRS = ['data-tab','data-f','data-filter','data-section','data-period','data-mode','data-sort'];
  var tpPath = location.pathname.replace(/\/$/,'') || '/';

  function tpSave(attr, val) {
    try { localStorage.setItem(SF_TP + tpPath + ':' + attr, val); } catch(e){}
  }
  function tpRestore() {
    TP_ATTRS.forEach(function(attr) {
      try {
        var saved = localStorage.getItem(SF_TP + tpPath + ':' + attr);
        if (!saved) return;
        var btn = document.querySelector('[' + attr + '="' + CSS.escape(saved) + '"]');
        if (btn && !btn.classList.contains('active')) btn.click();
      } catch(e){}
    });
  }

  // 이벤트 위임: 탭 클릭 시 저장
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('button, [role="tab"], .tab-btn, .chart-tab, .ftab, .period-btn, .filter-btn, .mode-btn, .sort-btn, .weight-btn, .tab, .seg-btn');
    if (!btn) return;
    TP_ATTRS.forEach(function(attr) {
      var val = btn.getAttribute(attr);
      if (val) tpSave(attr, val);
    });
  });

  // select 드롭다운 상태 저장·복원 (id가 있는 select만)
  var SF_SEL = 'sf-sel-';
  function selSave(el) {
    if (!el.id) return;
    try { localStorage.setItem(SF_SEL + tpPath + ':' + el.id, el.value); } catch(e){}
  }
  function selRestore() {
    document.querySelectorAll('select[id]').forEach(function(sel) {
      // 모달/숨김 영역 안의 select 제외
      if (sel.closest('.modal, .modal-overlay, [style*="display:none"], [style*="display: none"]')) return;
      try {
        var saved = localStorage.getItem(SF_SEL + tpPath + ':' + sel.id);
        if (saved && sel.querySelector('option[value="' + CSS.escape(saved) + '"]')) {
          sel.value = saved;
          sel.dispatchEvent(new Event('change', {bubbles:true}));
        }
      } catch(e){}
    });
  }
  document.addEventListener('change', function(e) {
    if (e.target.tagName === 'SELECT' && e.target.id) selSave(e.target);
  });

  // 복원은 페이지 스크립트 실행 후 (동적 탭 포함)
  function tpDelayedRestore() { setTimeout(function(){ tpRestore(); selRestore(); }, 200); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function(){ init(); tpDelayedRestore(); });
  } else {
    init();
    tpDelayedRestore();
  }
})();
