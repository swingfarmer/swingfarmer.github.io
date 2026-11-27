/* ============================================================
   sf-tree.js v5.10 (140: 외부용 계정도 owner 칸 공유) — 내 메뉴 트리 (모든 페이지 왼쪽)
   common.js가 읽는다(페이지에 따로 넣지 않음). 관리자 로그인일 때만 탭이 보인다.

   ■ 모양
     - 화면 왼쪽 끝에 고정된 세로 탭 「› 내 메뉴」. 누르면 트리가 펼쳐짐
     - PC(폭 761px 이상): 왼쪽 빈 여백에 펼침. 여백이 모자란 페이지만 본문을 그만큼 오른쪽으로 밂(body padding-left)
     - 폰(760px 이하): 본문 위로 덮음. 메뉴 하나 누르면 닫힘
     - 펼침/닫힘 상태 = localStorage sf-tree-open (페이지를 옮겨도 그대로, 브라우저별)
     - 폴더 접힘/펼침 = localStorage sf-tree-fold (브라우저별, 저장·되돌리기 대상 아님)
     - (129 v5.8) 접힌 탭을 키움(누르기 편하게 — PC 글씨 15px·폭 약 33px, 폰 14px) + 페이지를 스크롤하는 동안 탭을 잠깐 숨김(멈추고 0.15초 뒤 다시 보임 — 0.5초는 느리다고 해서 줄임, 펼쳤을 땐 안 숨김)
     - (132 v5.9) PC만: 펼친 트리 오른쪽 테두리(↔)를 끌어 넓이 바꿈(200~480px, 화면이 좁으면 본문 300px 남게) — 잠금과 관계없이 됨(보이는 모양만, 내용은 안 바뀜).
       테두리 더블클릭 = 기본(240px)으로. 넓이 = localStorage sf-tree-w(브라우저별 — PC마다 모니터가 달라서 계정에 안 둠). 폰은 그대로(화면 86%, 최대 290px)
       넓이는 CSS 변수 --sf-tree-w(html 요소)로 패널·탭 자리·본문 밀기가 같이 따라감
   ■ 트리
     - [+ 폴더] [+ 이 페이지] + 메뉴 검색(메인 카드 목록 = menu-search.js와 같은 출처: 메인 .tool-panel .tool-grid > a.card)
     - 폴더 2단계까지(폴더 안 폴더 1번). 지금 페이지는 파란색(location.pathname 비교, #탭은 안 봄)
     - 이름 바꾸기 = 줄 끝 ✎(또는 더블클릭) / 삭제 = 줄 끝 ✕(또는 오른쪽 클릭) → 한 번 더 물음 / 끌기 = 손잡이(⋮⋮)
     - (124 v5.7) 🔒 잠금(PC·폰 둘 다, 기본 잠금): 잠그면 손잡이·✎·✕·+폴더·+이 페이지·뒤로/앞으로·검색 추가가 숨고, 더블클릭 이름 바꾸기·오른쪽 클릭 삭제도 안 됨.
       이동(누르기)·폴더 접고 펴기·탭 자리 옮기기는 됨. 상태 = localStorage sf-tree-lock('0'이면 풀림, 브라우저별). 머리줄 🔒/🔓 버튼으로 바꿈
     - (124 v5.5) 폰(760px 이하)만: 접힌 「› 내 메뉴」 탭을 손가락으로 위아래로 끌어 자리 옮김(본문 카드를 가릴 때).
       (v5.6) 끄는 동안 손가락을 따라 화면 어디든 떠다니고(살짝 커짐·그림자), 손을 떼면 왼쪽 벽으로 미끄러져 붙음. 높이만 기억
       자리 = localStorage sf-tree-tabY(화면 위에서부터 px, 브라우저별). 화면 밖으로 안 나가게 맞춤. 짧게 누르면 예전처럼 열기/닫기. PC는 그대로
       (v5.2~5.4에 넣었던 「줄 꾹 눌러 끌기」는 사용자 뜻을 잘못 알아 넣은 것 → 뺌. 남긴 것: 목록 글자 선택 막음, 링크 끌기 막음,
        안드로이드 꾹 누름에서 나오던 contextmenu(=삭제 질문) 막음 — 폰 삭제는 줄 끝 ✕)
     - (123 v5.1) 스크롤바: 얇게 + 다크에서 어두운 색 (예전엔 다크에서도 밝은 회색 굵은 막대)
     - (123 v5) 폴더 표시: 펼침 ▾ 📂 / 접힘 ▸ 📁 + 안에 든 메뉴 수 배지. 폴더 더블클릭이 접기·펼치기와 겹쳐 이름 바꾸기가 잘 안 돼서 ✎ 버튼을 둠
   ■ 저장
     - 바뀔 때마다 Firestore calc_data/{SF_ADMIN_UIDS[0]} 의 sf_tree.{칸 이름} 에 자동 저장. 메인 저장(FAB)에는 안 들어감(119 결정)
     - 칸 이름 (121 사용자 결정): 사용자 본인 아이디 2개(SF_ADMIN_UIDS 1·2번째) = 'owner' 한 칸을 같이 씀(어느 아이디·PC든 같은 트리)
       그 밖의 관리자 아이디(3번째 = Claude 작업용 aichatetc) = 자기 uid 칸 따로 → Claude 시험이 사용자 트리를 안 건드림
     - 바뀌기 직전 모습을 hist에 최근 20번 보관 → 「↶ 뒤로」·「↷ 앞으로」
     - 이 브라우저 사본: localStorage sf-tree-cache:{칸 이름} (계정에서 못 읽을 때·첫 화면용)
   ■ (121 v3) 「↷ 앞으로」(fut), 줄 끝 ✕ 삭제, 헤더 📂 숨기기(localStorage sf-tree-hide), 닫힌 탭이 본문을 가리면 38px 밂(129),
     떠나기 직전 저장 보내기 + 이 브라우저 사본이 계정에 못 올라갔으면 다음 페이지에서 올림(at·synced)
   ■ 옛 문법만 쓴다(?. ?? 안 씀) — 공통 js 규칙
   ============================================================ */
(function () {
  'use strict';
  if (window.__sfTreeLoaded) return;
  window.__sfTreeLoaded = true;

  var PANEL_W = 240;          // 펼친 트리 기본 폭(PC). 본문은 이 폭 + 탭 폭(40)만큼 왼쪽 여백이 있게 밂
  var W_MIN = 200, W_MAX = 480, LS_W = 'sf-tree-w';   // (132) 끌어서 바꾸는 넓이 범위·저장 키
  var MOBILE_MAX = 760;       // 이 폭 이하 = 폰 방식(덮기)
  var HIST_MAX = 20;
  var FIELD = 'sf_tree';
  var LS_OPEN = 'sf-tree-open', LS_FOLD = 'sf-tree-fold', LS_CACHE = 'sf-tree-cache:';
  var FB = 'https://www.gstatic.com/firebasejs/12.14.0/';

  var uid = null;             // 저장 칸 이름 ('owner' 또는 uid)
  // (121) 사용자 본인 아이디 = 'owner' 한 칸 공유. 본인 아이디가 늘면 여기에 uid를 더하면 같이 씀(따로 쓰고 싶으면 안 넣으면 됨).
  //       여기 없는 관리자 아이디(Claude 작업용·다른 사람)는 자기 uid 칸을 따로 씀
  var OWNER_UIDS = ['1JrHgD2bpTRjrS2jw7MbpHciBph1', 'Ydd8v6LCN2TPjkqKD4DejLSWwaL2', 'DwZTLdBWiUVNXaifJxW6yg371rI2'];   // (140) 3번째 = 외부용 swingfarmer2026
  var LS_HIDE = 'sf-tree-hide';   // 헤더 📂 버튼으로 내 메뉴 통째로 숨김(이 브라우저만)
  var fut = [];               // 「↷ 앞으로」용 — 되돌린 모습들(끝이 가장 최근에 되돌린 것)
  var tree = [];              // [{id, t:'f'|'p', name, href?, kids?}]
  var hist = [];              // 직전 모습(JSON 문자열) 목록, 끝이 가장 최근
  var fold = {};              // 폴더 id → true(접힘)
  var remoteOk = null;
  var realUid = null;         // 로그인 uid (옛 칸 옮겨 오기용)
  var localAt = 0;            // 지금 트리를 마지막으로 바꾼 시각        // null 아직 / true / false(계정 저장 실패)
  var saveTimer = null;
  var menuList = null;        // 메뉴 검색 목록
  var els = {};

  function ls(k, v) {
    try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {}
    return null;
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function newId() { return 'n' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function normPath(p) {
    p = String(p || '').split('#')[0].split('?')[0];
    p = p.replace(/index\.html$/, '');
    if (p.charAt(p.length - 1) !== '/' && p.indexOf('.') === -1) p += '/';
    return p || '/';
  }
  function isMobile() { return window.innerWidth <= MOBILE_MAX; }
  function pageTitle() {
    var t = (document.title || '').replace(/\s*[\|·\-–—]\s*스윙파머.*$/i, '').trim();
    return t || location.pathname;
  }

  /* ── 트리 다루기 ── */
  function walk(list, fn, parent, level) {
    for (var i = 0; i < list.length; i++) {
      if (fn(list[i], list, i, parent || null, level || 0) === false) return false;
      if (list[i].kids && walk(list[i].kids, fn, list[i], (level || 0) + 1) === false) return false;
    }
    return true;
  }
  function find(id) {
    var r = null;
    walk(tree, function (n, list, i, parent, level) { if (n.id === id) { r = { node: n, list: list, index: i, parent: parent, level: level }; return false; } });
    return r;
  }
  function hasSubFolder(n) { if (!n.kids) return false; for (var i = 0; i < n.kids.length; i++) if (n.kids[i].t === 'f') return true; return false; }
  function countAll(n) { var c = 0; if (n.kids) walk(n.kids, function () { c++; }); return c; }
  function isInside(ancestor, id) { var hit = false; if (ancestor.kids) walk(ancestor.kids, function (n) { if (n.id === id) { hit = true; return false; } }); return hit; }
  function clean(list, level) {   // 저장값 검사(이상한 값이 들어와도 화면이 깨지지 않게)
    var out = [];
    if (!Array.isArray(list)) return out;
    for (var i = 0; i < list.length; i++) {
      var n = list[i];
      if (!n || typeof n !== 'object') continue;
      if (n.t === 'f') out.push({ id: String(n.id || newId()), t: 'f', name: String(n.name || '새 폴더'), kids: level < 1 ? clean(n.kids, level + 1) : clean(n.kids, level + 1).filter(function (k) { return k.t === 'p'; }) });
      else if (n.t === 'p' && n.href) out.push({ id: String(n.id || newId()), t: 'p', name: String(n.name || n.href), href: String(n.href) });
    }
    return out;
  }

  /* ── 바꾸기 (전부 이 함수를 거침 → 직전 모습 보관 + 저장) ── */
  function change(fn) {
    var before = JSON.stringify(tree);
    fn();
    if (JSON.stringify(tree) === before) { render(); return; }
    hist.push(before);
    if (hist.length > HIST_MAX) hist = hist.slice(hist.length - HIST_MAX);
    fut = [];   // 새로 바꾸면 「앞으로」 갈 길은 사라짐(일반 프로그램과 같음)
    afterChange();
  }
  function undo() {
    if (!hist.length) return;
    fut.push(JSON.stringify(tree));
    if (fut.length > HIST_MAX) fut = fut.slice(fut.length - HIST_MAX);
    tree = clean(JSON.parse(hist.pop()), 0);
    afterChange();
    flash('↶ 한 단계 되돌렸어요');
  }
  function redo() {
    if (!fut.length) return;
    hist.push(JSON.stringify(tree));
    if (hist.length > HIST_MAX) hist = hist.slice(hist.length - HIST_MAX);
    tree = clean(JSON.parse(fut.pop()), 0);
    afterChange();
    flash('↷ 한 단계 앞으로 갔어요');
  }
  function afterChange() {
    saveLocal();
    render();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveRemote, 250);
  }
  // 바꾸자마자 다른 페이지로 가도 계정 저장이 빠지지 않게: 떠날 때 남은 저장을 바로 보냄
  //  + 다음 페이지에서 이 브라우저 사본이 계정에 못 올라간 채면 사본을 올림(loadRemote, synced·at)

  /* ── 저장 ── */
  function saveLocal() {
    if (!uid) return;
    localAt = Date.now();
    ls(LS_CACHE + uid, JSON.stringify({ tree: tree, hist: hist, fut: fut, at: localAt, synced: false }));
  }
  function markSynced(at) {
    if (!uid) return;
    try { var c = JSON.parse(ls(LS_CACHE + uid) || 'null'); if (c && c.at === at) { c.synced = true; ls(LS_CACHE + uid, JSON.stringify(c)); } } catch (e) {}
  }
  var fsP = null;
  function fs() {
    if (!fsP) fsP = Promise.all([import(FB + 'firebase-app.js'), import(FB + 'firebase-firestore.js')]).then(function (m) {
      var apps = m[0].getApps();
      if (!apps.length) throw new Error('firebase 앱 없음');
      var f = m[1];
      var db = f.getFirestore(apps[0]);
      return { f: f, ref: f.doc(db, 'calc_data', window.SF_ADMIN_UIDS[0]) };
    });
    return fsP;
  }
  function saveRemote() {
    if (!uid) return;
    var me = uid;
    var payload = {};
    var at = localAt || Date.now();
    payload[me] = { tree: JSON.stringify(tree), hist: hist.slice(), fut: fut.slice(), at: at };
    var data = {}; data[FIELD] = payload;
    clearTimeout(saveTimer); saveTimer = null;
    fs().then(function (x) { return x.f.setDoc(x.ref, data, { merge: true }); })
      .then(function () { remoteOk = true; markSynced(at); renderStatus(); })
      .catch(function (e) { console.warn('[sf-tree] 계정 저장 실패', e); remoteOk = false; renderStatus(); });
  }
  function loadRemote() {
    var me = uid;
    fs().then(function (x) { return x.f.getDoc(x.ref); }).then(function (s) {
      if (me !== uid) return;
      var d = s.exists() ? s.data() : {};
      var mine = d[FIELD] && d[FIELD][me];
      remoteOk = true;
      if (!mine && me === 'owner' && d[FIELD] && realUid) {   // 121 바꾸기 전 자기 uid 칸에 저장한 게 있으면 그걸로 시작
        var old = d[FIELD][realUid];
        if (old && typeof old.tree === 'string') mine = old;
      }
      var c = null;
      try { c = JSON.parse(ls(LS_CACHE + me) || 'null'); } catch (e) {}
      if (c && c.synced === false && (!mine || !(mine.at >= c.at))) {
        saveRemote();   // 이 브라우저에서 바꾼 게 계정에 못 올라간 채 페이지를 떠났음 → 지금 올림
      } else if (mine && typeof mine.tree === 'string') {
        var strs = function (a) { return Array.isArray(a) ? a.filter(function (h) { return typeof h === 'string'; }).slice(-HIST_MAX) : []; };
        tree = clean(JSON.parse(mine.tree), 0);
        hist = strs(mine.hist);
        fut = strs(mine.fut);
        localAt = mine.at || Date.now();
        ls(LS_CACHE + me, JSON.stringify({ tree: tree, hist: hist, fut: fut, at: localAt, synced: true }));
        render();
      } else if (tree.length) {
        saveRemote();   // 계정엔 없고 이 브라우저에만 있으면 올림
      } else renderStatus();
    }).catch(function (e) { console.warn('[sf-tree] 계정에서 못 읽음', e); remoteOk = false; renderStatus(); });
  }

  /* ── 스타일 ── */
  var CSS = ''
  + '#sf-tree-tab{position:fixed;left:0;top:150px;z-index:9510;writing-mode:vertical-rl;text-orientation:mixed;background:#1F4E78;color:#fff;border:none;border-radius:0 8px 8px 0;padding:18px 9px;font:700 15px/1 -apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",sans-serif;letter-spacing:1px;cursor:pointer;box-shadow:2px 2px 8px rgba(0,0,0,.18);display:none;transition:opacity .15s}'
  + '#sf-tree-tab:hover{background:#2a6299}'
  + '#sf-tree-tab.st-tab-scroll{opacity:0;pointer-events:none}'   /* (129) 스크롤하는 동안 숨김 */
  + '#sf-tree-tab .st-arr{display:inline-block;writing-mode:horizontal-tb;font-size:18px;line-height:1;margin-bottom:3px}'   /* 세로 글씨 안에서 화살표만 바로 세움 */
  + 'body.sf-tree-on #sf-tree-tab{display:block}'
  + 'body.sf-tree-open #sf-tree-tab{left:var(--sf-tree-w,' + PANEL_W + 'px)}'
  + '#sf-tree{position:fixed;left:0;top:56px;bottom:0;width:var(--sf-tree-w,' + PANEL_W + 'px);z-index:9500;background:#fff;border-right:1px solid #dbe3ec;box-shadow:2px 0 10px rgba(0,0,0,.06);display:none;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",sans-serif;font-size:13px;color:#1f2937;box-sizing:border-box}'
  + 'body.sf-tree-on.sf-tree-open #sf-tree{display:flex}'
  + '#sf-tree *{box-sizing:border-box}'
  + '.st-head{display:flex;align-items:center;gap:4px;padding:8px 8px 6px;border-bottom:1px solid #eef2f6;flex-wrap:wrap}'
  + '.st-title{font-weight:800;color:#1F4E78;font-size:13.5px;margin-right:auto}'
  + '.st-btn{border:1px solid #cbd5e1;background:#f8fafc;color:#1F4E78;border-radius:6px;padding:3px 7px;font:600 11.5px/1.4 inherit;cursor:pointer;white-space:nowrap}'
  + '.st-btn:hover{background:#e8f0f8}'
  + '.st-btn:disabled{opacity:.4;cursor:default}'
  + '#sf-tree.st-locked .st-handle,#sf-tree.st-locked .st-del-x,#sf-tree.st-locked .st-ren-x,#sf-tree.st-locked .st-search,#sf-tree.st-locked .st-head .st-btn:not(.st-lockb){display:none!important}'
  + '#sf-tree:not(.st-locked) .st-lockb{background:#fef3c7;border-color:#f59e0b;color:#92400e}body.sf-dark #sf-tree:not(.st-locked) .st-lockb{background:#3a2e10;border-color:#b45309;color:#fcd34d}'
  + '.st-ibtn{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;background:#1F4E78;color:#fff;font:700 11px/1 inherit;cursor:pointer;border:none;padding:0}'
  + '.st-info{display:none;margin:6px 8px 0;padding:8px 10px;background:#eef5fc;color:#1e3a5f;border-radius:8px;font-size:11.5px;line-height:1.55}'
  + '.st-info.show{display:block}'
  + '.st-info b{color:#1F4E78}'
  + '.st-search{position:relative;padding:6px 8px}'
  + '.st-q{width:100%;font-size:12.5px;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;background:#fff;color:#1f2937;outline:none;font-family:inherit}'
  + '.st-q:focus{border-color:#1F4E78}'
  + '.st-drop{display:none;position:absolute;left:8px;right:8px;top:100%;background:#fff;border:1px solid #d1d5db;border-radius:8px;box-shadow:0 8px 20px rgba(0,0,0,.15);max-height:50vh;overflow-y:auto;z-index:2}'
  + '.st-drop.show{display:block}'
  + '.st-hit{padding:6px 9px;cursor:pointer;border-bottom:1px solid #f1f5f9;font-size:12.5px}'
  + '.st-hit:hover,.st-hit.sel{background:#eef4fa}'
  + '.st-hit small{display:block;color:#64748b;font-size:10.5px}'
  + '.st-none{padding:10px;color:#94a3b8;font-size:12px;text-align:center}'
  + '.st-list{flex:1;overflow-y:auto;padding:4px 4px 40px;position:relative}'
  + '.st-list,.st-drop{scrollbar-width:thin;scrollbar-color:#cbd5e1 transparent}'
  + 'body.sf-dark .st-list,body.sf-dark .st-drop{scrollbar-color:#3f4451 transparent}'
  + '.st-empty{color:#94a3b8;font-size:12px;line-height:1.6;padding:14px 10px;text-align:center}'
  + '.st-row,.st-row a{-webkit-user-drag:none}'
  + '.st-list,.st-list *{user-select:none!important;-webkit-user-select:none!important;-webkit-touch-callout:none!important}.st-list .st-edit{user-select:text!important;-webkit-user-select:text!important}'
  + '.st-row{display:flex;align-items:center;gap:3px;min-height:28px;padding:2px 4px;border-radius:6px;cursor:default;user-select:none;-webkit-user-select:none}'
  + '.st-row:hover{background:#f1f5f9}'
  + '.st-handle{flex:0 0 auto;width:16px;text-align:center;color:#94a3b8;cursor:grab;font-size:12px;letter-spacing:-2px;touch-action:none;padding:4px 0}'
  + '.st-handle:hover{color:#1F4E78}'
  + '.st-arrow{flex:0 0 auto;width:14px;text-align:center;color:#64748b;font-size:10px}'
  + '.st-folder > .st-arrow{font-size:12px;color:#1F4E78}'
  + '.st-cnt{flex:0 0 auto;font-size:10.5px;font-weight:700;color:#1F4E78;background:#e2ebf5;border-radius:9px;padding:0 6px;line-height:16px}'
  + '.st-folder.closed{background:#f5f8fb}'
  + '.st-folder.closed:hover{background:#eaf0f6}'
  + '.st-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#1f2937;text-decoration:none;padding:3px 2px}'
  + 'a.st-name:hover{text-decoration:underline}'
  + '.st-folder > .st-name{font-weight:700;cursor:pointer}'
  + '.st-row.cur{background:#dbeafe}'
  + '.st-row.cur > .st-name{color:#1d4ed8;font-weight:800}'
  + '.st-row.dragging{opacity:.35}'
  + '.st-row.into{background:#dbeafe;outline:2px dashed #3b82f6;outline-offset:-2px}'
  + '.st-del-x,.st-ren-x{flex:0 0 auto;border:none;background:none;color:#94a3b8;font-size:11px;line-height:1;padding:4px 5px;border-radius:4px;cursor:pointer;visibility:hidden}'
  + '.st-row:hover .st-del-x,.st-row:hover .st-ren-x{visibility:visible}'
  + '.st-del-x:hover{background:#fee2e2;color:#dc2626}'
  + '.st-ren-x:hover{background:#dbeafe;color:#1d4ed8}'
  + '@media(hover:none){.st-del-x,.st-ren-x{visibility:visible}}'
  + 'body.sf-dark .st-ren-x:hover{background:#1e3a5f;color:#93c5fd}'
  + 'body.sf-dark .st-del-x:hover{background:#3b1d1d;color:#f87171}'
  + 'body.sf-tree-hidden #sf-tree,body.sf-tree-hidden #sf-tree-tab,body.sf-tree-hidden #sf-tree-back{display:none!important}'
  + '#sf-tree-hbtn{display:none}body.sf-tree-on #sf-tree-hbtn{display:inline-flex}'
  + 'body.sf-tree-hidden #sf-tree-hbtn{opacity:.45}'
  + '.st-edit{flex:1;min-width:0;font-size:12.5px;padding:2px 5px;border:1px solid #3b82f6;border-radius:5px;font-family:inherit;color:#1f2937;background:#fff}'
  + '.st-line{position:absolute;left:6px;right:6px;height:0;border-top:2px solid #3b82f6;pointer-events:none;display:none}'
  + '.st-line:before{content:"";position:absolute;left:-4px;top:-5px;width:8px;height:8px;border-radius:50%;background:#3b82f6}'
  + '.st-ghost{position:fixed;z-index:9600;pointer-events:none;background:#fff;border:1px solid #93c5fd;border-radius:6px;padding:4px 10px;font:600 12.5px/1.4 -apple-system,BlinkMacSystemFont,"Malgun Gothic",sans-serif;color:#1F4E78;box-shadow:0 6px 16px rgba(0,0,0,.2);max-width:220px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}'
  + '.st-foot{border-top:1px solid #eef2f6;padding:5px 8px 5px 60px;font-size:10.5px;color:#94a3b8;min-height:22px}'
  + '.st-foot.bad{color:#dc2626}'
  + '.st-ask{position:absolute;left:8px;right:8px;top:64px;z-index:3;background:#fff;border:1px solid #fca5a5;border-radius:10px;box-shadow:0 10px 24px rgba(0,0,0,.2);padding:12px;font-size:12.5px;line-height:1.55}'
  + '.st-ask .st-ask-btns{display:flex;gap:6px;justify-content:flex-end;margin-top:10px}'
  + '.st-ask .st-del{background:#dc2626;border-color:#dc2626;color:#fff}'
  + '.st-toast{position:absolute;left:50%;bottom:30px;transform:translateX(-50%);background:#1f2937;color:#fff;border-radius:8px;padding:6px 12px;font-size:12px;white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .2s}'
  + '.st-toast.show{opacity:.92}'
  + '#sf-tree-back{position:fixed;inset:56px 0 0 0;background:rgba(0,0,0,.35);z-index:9490;display:none}'
  /* (132) PC 넓이 손잡이 — 오른쪽 테두리 */
  + '.st-grip{position:absolute;top:0;bottom:0;right:-4px;width:8px;cursor:col-resize;z-index:4;touch-action:none}'
  + '.st-grip:hover,.st-grip.on{background:linear-gradient(90deg,transparent 3px,#3b82f6 3px,#3b82f6 5px,transparent 5px)}'
  + 'body.st-resizing,body.st-resizing *{cursor:col-resize!important;user-select:none!important;-webkit-user-select:none!important}'
  + 'body.sf-dark .st-grip:hover,body.sf-dark .st-grip.on{background:linear-gradient(90deg,transparent 3px,#60a5fa 3px,#60a5fa 5px,transparent 5px)}'
  /* 다크 */
  + 'body.sf-dark #sf-tree-tab{background:#2a4a6e}'
  + 'body.sf-dark #sf-tree{background:#1a1d27;border-right-color:#2a2d3a;color:#e4e4e7}'
  + 'body.sf-dark .st-head,body.sf-dark .st-foot{border-color:#2a2d3a}'
  + 'body.sf-dark .st-title{color:#60a5fa}'
  + 'body.sf-dark .st-btn{background:#222532;border-color:#475569;color:#93c5fd}'
  + 'body.sf-dark .st-btn:hover{background:#2a2d3a}'
  + 'body.sf-dark .st-ibtn{background:#3b6ea5}'
  + 'body.sf-dark .st-info{background:#1a2c42;color:#aac7e8}'
  + 'body.sf-dark .st-info b{color:#93c5fd}'
  + 'body.sf-dark .st-q{background:#222532;border-color:#475569;color:#e4e4e7}'
  + 'body.sf-dark .st-drop{background:#1a1d27;border-color:#2a2d3a}'
  + 'body.sf-dark .st-hit{border-color:#2a2d3a;color:#e4e4e7}'
  + 'body.sf-dark .st-hit:hover,body.sf-dark .st-hit.sel{background:#1e3a5f}'
  + 'body.sf-dark .st-hit small{color:#a1a1aa}'
  + 'body.sf-dark .st-row:hover{background:#232a35}'
  + 'body.sf-dark .st-name{color:#e4e4e7}'
  + 'body.sf-dark .st-handle,body.sf-dark .st-arrow{color:#71717a}'
  + 'body.sf-dark .st-folder > .st-arrow{color:#93c5fd}'
  + 'body.sf-dark .st-cnt{background:#1e3a5f;color:#93c5fd}'
  + 'body.sf-dark .st-folder.closed{background:#1f2430}'
  + 'body.sf-dark .st-folder.closed:hover{background:#232a35}'
  + 'body.sf-dark .st-handle:hover{color:#93c5fd}'
  + 'body.sf-dark .st-row.cur,body.sf-dark .st-row.into{background:#1e3a5f}'
  + 'body.sf-dark .st-row.cur > .st-name{color:#93c5fd}'
  + 'body.sf-dark .st-edit{background:#222532;color:#e4e4e7}'
  + 'body.sf-dark .st-ghost{background:#1a1d27;color:#93c5fd;border-color:#3b6ea5}'
  + 'body.sf-dark .st-ask{background:#1a1d27;border-color:#7f1d1d;color:#e4e4e7}'
  + 'body.sf-dark .st-empty,body.sf-dark .st-none,body.sf-dark .st-foot{color:#71717a}'
  + 'body.sf-dark .st-foot.bad{color:#f87171}'
  /* 폰 */
  + '@media(max-width:' + MOBILE_MAX + 'px){#sf-tree{width:min(290px,86vw);box-shadow:4px 0 18px rgba(0,0,0,.25)}'
  + 'body.sf-tree-open #sf-tree-tab{left:min(290px,86vw)}'
  + 'body.sf-tree-on.sf-tree-open #sf-tree-back{display:block}'
  + '#sf-tree-tab{top:auto;bottom:150px;padding:14px 8px;font-size:14px;touch-action:none;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}'
  + '#sf-tree-tab.st-tab-moving{opacity:.92;border-radius:8px;transform:scale(1.08);box-shadow:0 8px 22px rgba(0,0,0,.35),0 0 0 2px rgba(96,165,250,.7);transition:transform .12s,border-radius .12s}'
  + '#sf-tree-tab.st-tab-snap{transition:left .28s cubic-bezier(.2,1.3,.4,1),transform .2s,border-radius .2s}'
  + '.st-row{min-height:34px;-webkit-touch-callout:none}.st-handle{width:22px;font-size:14px}.st-grip{display:none}}'
  + '@media print{#sf-tree,#sf-tree-tab,#sf-tree-back{display:none!important}}';

  /* ── 화면 만들기 ── */
  function build() {
    var st = document.createElement('style');
    st.id = 'sf-tree-css';
    st.textContent = CSS;
    document.head.appendChild(st);

    var tab = document.createElement('button');
    tab.id = 'sf-tree-tab';
    tab.type = 'button';
    tab.addEventListener('click', function () { if (tabJustMoved) return; setOpen(!document.body.classList.contains('sf-tree-open')); });
    // (129) 접혀 있을 때 페이지를 스크롤하는 동안 탭을 숨김 — 멈추고 0.15초 뒤 다시 보임
    var scrollT = null;
    window.addEventListener('scroll', function () {
      if (document.body.classList.contains('sf-tree-open') || tab.classList.contains('st-tab-moving')) return;
      tab.classList.add('st-tab-scroll');
      clearTimeout(scrollT);
      scrollT = setTimeout(function () { tab.classList.remove('st-tab-scroll'); }, 150);
    }, { passive: true });

    var back = document.createElement('div');
    back.id = 'sf-tree-back';
    back.addEventListener('click', function () { setOpen(false); });

    var p = document.createElement('div');
    p.id = 'sf-tree';
    p.innerHTML = ''
      + '<div class="st-head"><span class="st-title">📂 내 메뉴</span>'
      + '<button type="button" class="st-btn st-lockb" data-act="lock"></button>'
      + '<button type="button" class="st-btn" data-act="folder" title="맨 아래에 새 폴더">+ 폴더</button>'
      + '<button type="button" class="st-btn" data-act="here" title="지금 보고 있는 페이지를 맨 아래에 추가">+ 이 페이지</button>'
      + '<button type="button" class="st-btn" data-act="undo" title="마지막으로 바꾼 것을 되돌림(최근 20번)">↶ 뒤로</button>'
      + '<button type="button" class="st-btn" data-act="redo" title="되돌린 것을 다시 앞으로">↷ 앞으로</button>'
      + '<button type="button" class="st-ibtn" data-act="info" title="사용법·저장 방식">i</button></div>'
      + '<div class="st-info">'
      + '<b>🔒 잠금</b>: 잠겨 있으면 메뉴를 옮기거나 지우거나 이름을 바꿀 수 없어요(실수 방지). 누르고 이동·폴더 접기는 그대로. 고칠 때만 「🔒 잠금」을 눌러 「🔓 풀림」으로 바꾸고, 다 고치면 다시 잠가요. 이 브라우저에 기억(처음엔 잠금)<br>'
      + '<b>추가</b>: 「+ 이 페이지」 = 지금 페이지, 아래 검색칸 = 메인 메뉴에서 골라 넣기. 둘 다 맨 아래에 들어가요.<br>'
      + '<b>이름 바꾸기</b>: 줄에 마우스를 올리면 오른쪽 끝에 ✎ (또는 더블클릭) → 고치고 Enter (Esc = 취소)<br>'
      + '<b>삭제</b>: 줄에 마우스를 올리면 오른쪽 끝에 ✕ (또는 오른쪽 클릭) → 한 번 더 물어봐요. 폴더를 지우면 안에 든 것도 같이 지워져요<br>'
      + '<b>탭 자리</b>: 폰에서는 접힌 「› 내 메뉴」 탭을 손가락으로 위아래로 끌면 자리가 옮겨져요(이 브라우저에 기억)<br>'
      + '<b>순서·폴더 넣고 빼기</b>: 왼쪽 손잡이(⋮⋮)를 끌어요. 파란 줄 = 그 자리에 놓임, 폴더가 점선 테두리 = 폴더 안으로. 맨 아래 빈 곳에 놓으면 폴더 밖 맨 끝.<br>'
      + '<b>폴더</b>는 2단계까지(폴더 안에 폴더 한 번). 폴더 이름을 누르면 접고 펼쳐요 — ▾📂 = 펼침, ▸📁 + 숫자 = 접힘(숫자는 안에 든 메뉴 수)<br>'
      + '<b>저장</b>: 바꿀 때마다 계정(Firestore)에 자동 저장 — <b>내 관리자 아이디 2개는 같은 트리</b>를 같이 써서 어느 아이디·PC에서나 같아요(Claude 작업용 아이디만 따로). 메인 저장(💾 FAB)에는 안 들어가요(불러올 때 트리가 옛날로 덮이지 않게).<br>'
      + '<b>되살리기</b>: 바꾸기 직전 모습을 계정에 최근 20번 보관해요. 잘못 지웠으면 「↶ 뒤로」를 누른 만큼 한 단계씩 돌아가고, 너무 많이 돌아갔으면 「↷ 앞으로」로 다시 와요(뒤로 간 다음 새로 바꾸면 앞으로 갈 길은 사라져요).<br>'
      + '<b>숨기기</b>: 맨 위 헤더의 📂 버튼을 누르면 내 메뉴 탭이 통째로 사라져요(본문이 왼쪽 끝까지 쓰는 페이지용). 다시 누르면 나와요. 이 브라우저에만 기억돼요.<br>'
      + '<b>넓이(PC)</b>: 이 메뉴 오른쪽 테두리에 마우스를 대면 ↔ — 끌어서 넓히고 좁혀요(200~480px, 잠금과 관계없이 됨). <b>테두리를 더블클릭하면 처음 넓이(240px)로</b> 돌아가요. 이 브라우저(PC)에만 기억돼요. 폰은 그대로.<br>'
      + '펼침·닫힘과 폴더 접힘은 이 브라우저에만 기억돼요. <span style="opacity:.6">(트리 v5.9)</span></div>'
      + '<div class="st-search"><input class="st-q" type="search" autocomplete="off" placeholder="🔍 메뉴 검색해서 추가" aria-label="메뉴 검색해서 추가"><div class="st-drop"></div></div>'
      + '<div class="st-list"><div class="st-line"></div></div>'
      + '<div class="st-foot"></div>'
      + '<div class="st-toast"></div>'
      + '<div class="st-grip" title="끌어서 넓이 바꾸기 · 더블클릭 = 처음 넓이(240px)"></div>';

    document.body.appendChild(back);
    document.body.appendChild(p);
    document.body.appendChild(tab);
    els = { tab: tab, panel: p, back: back, list: p.querySelector('.st-list'), line: p.querySelector('.st-line'), foot: p.querySelector('.st-foot'),
      info: p.querySelector('.st-info'), q: p.querySelector('.st-q'), drop: p.querySelector('.st-drop'), undo: p.querySelector('[data-act="undo"]'), redo: p.querySelector('[data-act="redo"]'), toast: p.querySelector('.st-toast') };

    p.querySelector('.st-head').addEventListener('click', function (e) {
      var b = e.target.closest('[data-act]');
      if (!b) return;
      var a = b.getAttribute('data-act');
      if (a === 'info') els.info.classList.toggle('show');
      else if (a === 'lock') setLock(!locked);
      else if (locked) return;
      else if (a === 'undo') undo();
      else if (a === 'redo') redo();
      else if (a === 'folder') addFolder();
      else if (a === 'here') addPage(location.pathname + location.hash, pageTitle());
    });
    bindSearch();
    bindList();
    bindTabDrag();
    bindGrip();
    setLock(locked, true);
  }

  /* ── (132 v5.9) PC 넓이: 오른쪽 테두리 끌기 / 더블클릭 = 기본 ── */
  function maxW() { return Math.max(W_MIN, Math.min(W_MAX, window.innerWidth - 300)); }
  function clampW(w) { return Math.round(Math.max(W_MIN, Math.min(maxW(), w))); }
  function panelW() {
    var w = parseFloat(ls(LS_W));
    return isNaN(w) ? PANEL_W : clampW(w);
  }
  function applyW(w) {
    if (w === PANEL_W) document.documentElement.style.removeProperty('--sf-tree-w');
    else document.documentElement.style.setProperty('--sf-tree-w', w + 'px');
  }
  function bindGrip() {
    var g = els.panel.querySelector('.st-grip'), rs = null, raf = 0;
    applyW(panelW());
    g.addEventListener('pointerdown', function (e) {
      if (isMobile() || (e.button !== undefined && e.button !== 0)) return;
      e.preventDefault();
      rs = { x: e.clientX, w: els.panel.getBoundingClientRect().width };
      try { g.setPointerCapture(e.pointerId); } catch (err) {}
      g.classList.add('on');
      document.body.classList.add('st-resizing');
    });
    g.addEventListener('pointermove', function (e) {
      if (!rs) return;
      var w = clampW(rs.w + e.clientX - rs.x);
      applyW(w);
      rs.cur = w;
      if (!raf) raf = requestAnimationFrame(function () { raf = 0; layout(); });
    });
    function end() {
      if (!rs) return;
      var w = rs.cur; rs = null;
      g.classList.remove('on');
      document.body.classList.remove('st-resizing');
      if (w) { if (w === PANEL_W) ls(LS_W, null); else ls(LS_W, String(w)); }
      layout();
    }
    g.addEventListener('pointerup', end);
    g.addEventListener('pointercancel', end);
    g.addEventListener('dblclick', function () {
      ls(LS_W, null);
      applyW(PANEL_W);
      layout();
      flash('↔ 처음 넓이(' + PANEL_W + 'px)로 돌렸어요');
    });
    window.addEventListener('resize', function () { applyW(panelW()); });
  }

  /* ── (124 v5.7) 잠금 ── */
  var LS_LOCK = 'sf-tree-lock', locked = ls('sf-tree-lock') !== '0';
  function setLock(v, quiet) {
    locked = !!v;
    ls(LS_LOCK, locked ? '1' : '0');
    if (!els.panel) return;
    els.panel.classList.toggle('st-locked', locked);
    var b = els.panel.querySelector('.st-lockb');
    if (b) { b.textContent = locked ? '🔒 잠금' : '🔓 풀림'; b.title = locked ? '잠겨 있음 — 눌러서 풀면 옮기기·이름 바꾸기·지우기·추가 가능' : '풀려 있음 — 눌러서 잠그면 실수로 못 바꿈'; }
    if (locked && drag) onCancel();
    if (!quiet) flash(locked ? '🔒 잠갔어요 — 메뉴를 바꿀 수 없어요' : '🔓 풀었어요 — 다 고치면 다시 잠가 주세요');
  }

  function setOpen(on) {
    document.body.classList.toggle('sf-tree-open', !!on);
    els.tab.innerHTML = on ? '<span class="st-arr">‹</span> 닫기' : '<span class="st-arr">›</span> 내 메뉴';
    ls(LS_OPEN, on ? '1' : '0');
    if (!on) { closeAsk(); hideDrop(); }
    layout();
  }

  /* ── 그리기 ── */
  function countPages(n) {   // 폴더 안 메뉴 수(하위 폴더 안 것까지)
    var c = 0;
    for (var i = 0; i < n.kids.length; i++) c += n.kids[i].t === 'f' ? countPages(n.kids[i]) : 1;
    return c;
  }
  function render() {
    if (!els.list) return;
    var cur = normPath(location.pathname);
    var html = [];
    function row(n, level) {
      var pad = 4 + level * 16;
      if (n.t === 'f') {
        var closed = !!fold[n.id];
        html.push('<div class="st-row st-folder' + (closed ? ' closed' : '') + '" data-id="' + esc(n.id) + '" style="padding-left:' + pad + 'px">'
          + '<span class="st-handle" title="끌어서 옮기기">⋮⋮</span><span class="st-arrow">' + (closed ? '▸' : '▾') + '</span>'
          + '<span class="st-name" title="' + esc(n.name) + (closed ? ' (접힘 — 누르면 펼침)' : ' (펼침 — 누르면 접힘)') + '">' + (closed ? '📁 ' : '📂 ') + esc(n.name) + '</span>'
          + (closed ? '<span class="st-cnt" title="안에 든 메뉴 수">' + countPages(n) + '</span>' : '')
          + '<button type="button" class="st-ren-x" title="이름 바꾸기">✎</button>'
          + '<button type="button" class="st-del-x" title="지우기">✕</button></div>');
        if (!closed) for (var i = 0; i < n.kids.length; i++) row(n.kids[i], level + 1);
      } else {
        var isCur = normPath(n.href) === cur;
        html.push('<div class="st-row st-page' + (isCur ? ' cur' : '') + '" data-id="' + esc(n.id) + '" style="padding-left:' + pad + 'px">'
          + '<span class="st-handle" title="끌어서 옮기기">⋮⋮</span><span class="st-arrow"></span>'
          + '<a class="st-name" draggable="false" href="' + esc(n.href) + '" title="' + esc(n.name + ' — ' + n.href) + '">' + esc(n.name) + '</a>'
          + '<button type="button" class="st-ren-x" title="이름 바꾸기">✎</button>'
          + '<button type="button" class="st-del-x" title="지우기">✕</button></div>');
      }
    }
    for (var i = 0; i < tree.length; i++) row(tree[i], 0);
    if (!tree.length) html.push('<div class="st-empty">비어 있어요.<br>「+ 폴더」「+ 이 페이지」나<br>위 검색칸으로 메뉴를 넣어 보세요.</div>');
    els.list.innerHTML = html.join('');
    els.list.appendChild(els.line);
    els.undo.disabled = !hist.length;
    els.undo.title = hist.length ? '마지막으로 바꾼 것을 되돌림 (되돌릴 수 있는 것 ' + hist.length + '번)' : '되돌릴 것이 없어요';
    els.redo.disabled = !fut.length;
    els.redo.title = fut.length ? '되돌린 것을 다시 앞으로 (' + fut.length + '번)' : '앞으로 갈 것이 없어요 (「↶ 뒤로」를 누른 뒤에 쓸 수 있어요)';
    renderStatus();
  }
  function renderStatus() {
    if (!els.foot) return;
    var bad = remoteOk === false;
    els.foot.classList.toggle('bad', bad);
    els.foot.textContent = bad ? '⚠ 계정 저장 실패 — 이 브라우저에만 저장됨' : (remoteOk ? '☁ 계정에 자동 저장됨' : '계정 불러오는 중…');
  }
  var toastT = null;
  function flash(msg) {
    if (!els.toast) return;
    els.toast.textContent = msg;
    els.toast.classList.add('show');
    clearTimeout(toastT);
    toastT = setTimeout(function () { els.toast.classList.remove('show'); }, 1600);
  }

  /* ── 추가 ── */
  function addFolder() {
    var id = newId();
    change(function () { tree.push({ id: id, t: 'f', name: '새 폴더', kids: [] }); });
    startRename(id);
  }
  function addPage(href, name) {
    var dup = null;
    walk(tree, function (n) { if (n.t === 'p' && n.href === href) { dup = n; return false; } });
    if (dup) { flash('이미 있어요: ' + dup.name); highlight(dup.id); return; }
    var id = newId();
    change(function () { tree.push({ id: id, t: 'p', name: name, href: href }); });
    highlight(id);
  }
  function highlight(id) {
    var f = find(id);
    if (f && f.parent && fold[f.parent.id]) { delete fold[f.parent.id]; saveFold(); render(); }
    var r = els.list.querySelector('.st-row[data-id="' + id + '"]');
    if (r) { r.scrollIntoView({ block: 'nearest' }); r.style.transition = 'background .6s'; r.style.background = '#fde68a'; setTimeout(function () { r.style.background = ''; }, 700); }
  }
  function saveFold() { ls(LS_FOLD, JSON.stringify(fold)); }

  /* ── 메뉴 검색 (메인 카드 = menu-search.js와 같은 출처) ── */
  function readCards(doc) {
    var out = [], seen = {};
    var cards = doc.querySelectorAll('.tool-panel .tool-grid > a.card');
    for (var i = 0; i < cards.length; i++) {
      var a = cards[i], href = a.getAttribute('href');
      if (!href || seen[href]) continue;
      seen[href] = 1;
      var t = a.querySelector('.card-title'), ic = a.querySelector('.icon'), panel = a.closest('.tool-panel'), h = panel ? panel.querySelector('.panel-header h2') : null;
      out.push({ href: href, name: t ? t.textContent.trim() : href, icon: ic ? ic.textContent.trim() : '', cat: h ? h.textContent.trim() : '' });
    }
    return out;
  }
  function loadMenu() {
    if (menuList) return Promise.resolve(menuList);
    if (normPath(location.pathname) === '/' && document.querySelector('.tool-panel .tool-grid > a.card')) { menuList = readCards(document); return Promise.resolve(menuList); }
    try { var c = sessionStorage.getItem('sf-tree-menu'); if (c) { menuList = JSON.parse(c); return Promise.resolve(menuList); } } catch (e) {}
    return fetch('/').then(function (r) { return r.text(); }).then(function (t) {
      menuList = readCards(new DOMParser().parseFromString(t, 'text/html'));
      try { sessionStorage.setItem('sf-tree-menu', JSON.stringify(menuList)); } catch (e) {}
      return menuList;
    });
  }
  function nq(s) { return String(s || '').toLowerCase().replace(/[\s·・\-_/()\[\]&,.:]+/g, ''); }
  var CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
  function cho(s) { var o = ''; for (var i = 0; i < s.length; i++) { var c = s.charCodeAt(i); o += (c >= 0xAC00 && c <= 0xD7A3) ? CHO[Math.floor((c - 0xAC00) / 588)] : s[i]; } return o; }
  var hits = [], selHit = -1;
  function bindSearch() {
    var q = els.q;
    q.addEventListener('focus', function () { loadMenu().then(function () { if (q.value) searchNow(); }).catch(function () { menuList = null; }); });
    q.addEventListener('input', function () { loadMenu().then(searchNow).catch(function () { els.drop.innerHTML = '<div class="st-none">메뉴 목록을 못 불러왔어요</div>'; els.drop.classList.add('show'); }); });
    q.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { selHit = Math.min(hits.length - 1, selHit + 1); paintSel(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { selHit = Math.max(0, selHit - 1); paintSel(); e.preventDefault(); }
      else if (e.key === 'Enter') { if (hits[selHit >= 0 ? selHit : 0]) pickHit(hits[selHit >= 0 ? selHit : 0]); e.preventDefault(); }
      else if (e.key === 'Escape') { q.value = ''; hideDrop(); }
    });
    els.drop.addEventListener('mousedown', function (e) { e.preventDefault(); });   // 입력칸 포커스 유지
    els.drop.addEventListener('click', function (e) {
      var h = e.target.closest('.st-hit');
      if (h) pickHit(hits[+h.getAttribute('data-i')]);
    });
    q.addEventListener('blur', function () { setTimeout(hideDrop, 150); });
  }
  function searchNow() {
    var v = nq(els.q.value);
    if (!v) { hideDrop(); return; }
    var allCho = /^[ㄱ-ㅎ]+$/.test(v), scored = [];
    for (var i = 0; i < menuList.length; i++) {
      var m = menuList[i], t = nq(m.name), c = nq(m.cat), s = 0;
      if (t.indexOf(v) !== -1) s = 3;
      else if (allCho && cho(t).indexOf(v) !== -1) s = 2;
      else if (c.indexOf(v) !== -1 || nq(m.href).indexOf(v) !== -1) s = 1;
      if (s) scored.push({ m: m, s: s, i: i });
    }
    scored.sort(function (a, b) { return b.s - a.s || a.i - b.i; });
    hits = scored.slice(0, 30).map(function (x) { return x.m; });
    selHit = hits.length ? 0 : -1;
    els.drop.innerHTML = hits.length ? hits.map(function (m, i) {
      return '<div class="st-hit" data-i="' + i + '">' + esc(m.icon + ' ' + m.name) + '<small>' + esc(m.cat) + '</small></div>';
    }).join('') : '<div class="st-none">없어요</div>';
    els.drop.classList.add('show');
    paintSel();
  }
  function paintSel() {
    var a = els.drop.querySelectorAll('.st-hit');
    for (var i = 0; i < a.length; i++) a[i].classList.toggle('sel', i === selHit);
    if (a[selHit]) a[selHit].scrollIntoView({ block: 'nearest' });
  }
  function hideDrop() { if (els.drop) els.drop.classList.remove('show'); }
  function pickHit(m) {
    if (!m) return;
    els.q.value = '';
    hideDrop();
    addPage(m.href, m.name);
  }

  /* ── 목록: 누르기·더블클릭·오른쪽 클릭 ── */
  var clickT = null;
  function bindList() {
    var L = els.list;
    L.addEventListener('click', function (e) {
      if (dragJustEnded) { e.preventDefault(); return; }
      var row = e.target.closest('.st-row');
      if (!row || e.target.closest('.st-handle') || e.target.closest('.st-edit')) return;
      var id = row.getAttribute('data-id');
      if (!locked && e.target.closest('.st-del-x')) { e.preventDefault(); askDelete(id); return; }
      if (!locked && e.target.closest('.st-ren-x')) { e.preventDefault(); clearTimeout(clickT); startRename(id); return; }
      if (row.classList.contains('st-folder')) {
        if (fold[id]) delete fold[id]; else fold[id] = true;
        saveFold(); render();
        return;
      }
      var a = e.target.closest('a.st-name');
      if (!a) return;
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;   // 새 탭 열기는 그대로
      e.preventDefault();   // 더블클릭(이름 바꾸기)과 구분하려고 잠깐 기다렸다 이동
      var href = a.getAttribute('href');
      clearTimeout(clickT);
      if (locked) { if (isMobile()) setOpen(false); location.href = href; return; }   // (124) 잠금이면 기다릴 필요 없음
      clickT = setTimeout(function () {
        if (isMobile()) setOpen(false);
        location.href = href;
      }, 260);
    });
    L.addEventListener('dblclick', function (e) {
      var row = e.target.closest('.st-row');
      if (locked || !row || e.target.closest('.st-handle') || e.target.closest('.st-del-x') || e.target.closest('.st-ren-x')) return;
      clearTimeout(clickT);
      e.preventDefault();
      startRename(row.getAttribute('data-id'));
    });
    L.addEventListener('contextmenu', function (e) {
      var row = e.target.closest('.st-row');
      if (!row) return;
      if (Date.now() - lastTouch < 1500) { e.preventDefault(); return; }   // (124) 폰 꾹 누름 — 삭제 질문 안 띄움
      if (locked) return;   // (124) 잠금 — 브라우저 기본 메뉴
      e.preventDefault();
      askDelete(row.getAttribute('data-id'));
    });
    L.addEventListener('pointerdown', onDown);
    L.addEventListener('dragstart', function (e) { e.preventDefault(); });
    L.addEventListener('selectstart', function (e) { if (!e.target.closest || !e.target.closest('.st-edit')) e.preventDefault(); });
    L.addEventListener('touchstart', noteTouch, { passive: true });
  }

  function startRename(id) {
    if (locked) return;
    var row = els.list.querySelector('.st-row[data-id="' + id + '"]');
    var f = find(id);
    if (!row || !f) return;
    var nameEl = row.querySelector('.st-name');
    var inp = document.createElement('input');
    inp.className = 'st-edit';
    inp.value = f.node.name;
    nameEl.style.display = 'none';
    var hideEls = row.querySelectorAll('.st-cnt,.st-ren-x,.st-del-x');
    for (var hi = 0; hi < hideEls.length; hi++) hideEls[hi].style.display = 'none';
    row.appendChild(inp);
    inp.focus(); inp.select();
    var done = false;
    function finish(ok) {
      if (done) return; done = true;
      var v = inp.value.trim();
      if (ok && v && v !== f.node.name) change(function () { var g = find(id); if (g) g.node.name = v.slice(0, 60); });
      else render();
    }
    inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); e.stopPropagation(); });
    inp.addEventListener('blur', function () { finish(true); });
  }

  var askEl = null;
  function closeAsk() { if (askEl) { askEl.remove(); askEl = null; } }
  function askDelete(id) {
    if (locked) return;
    closeAsk();
    var f = find(id);
    if (!f) return;
    var n = f.node, cnt = n.t === 'f' ? countAll(n) : 0;
    askEl = document.createElement('div');
    askEl.className = 'st-ask';
    askEl.innerHTML = '<b>「' + esc(n.name) + '」</b> 지울까요?'
      + (n.t === 'f' && cnt ? '<br><span style="color:#dc2626">안에 든 ' + cnt + '개도 같이 지워져요.</span>' : '')
      + '<br><span style="font-size:11px;opacity:.75">잘못 지우면 「↶ 뒤로」로 살릴 수 있어요.</span>'
      + '<div class="st-ask-btns"><button type="button" class="st-btn" data-a="no">취소</button><button type="button" class="st-btn st-del" data-a="yes">지우기</button></div>';
    els.panel.appendChild(askEl);
    askEl.addEventListener('click', function (e) {
      var b = e.target.closest('[data-a]');
      if (!b) return;
      if (b.getAttribute('data-a') === 'yes') change(function () { var g = find(id); if (g) g.list.splice(g.index, 1); });
      closeAsk();
    });
    var yes = askEl.querySelector('[data-a="yes"]');
    if (yes) yes.focus();
  }

  /* ── 끌기 (손잡이 ⋮⋮, 마우스·터치 둘 다 pointer 이벤트) ── */
  var drag = null, dragJustEnded = false;
  function onDown(e) {
    var h = e.target.closest('.st-handle');
    if (locked || !h || (e.button !== undefined && e.button !== 0)) return;
    var row = h.closest('.st-row');
    drag = { id: row.getAttribute('data-id'), x: e.clientX, y: e.clientY, on: false, row: row, target: null, pid: e.pointerId };
    try { h.setPointerCapture(e.pointerId); } catch (err) {}
    e.preventDefault();
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    document.addEventListener('pointercancel', onCancel);
    document.addEventListener('keydown', onKey);
  }
  function onKey(e) { if (e.key === 'Escape') onCancel(); }
  function onMove(e) { if (drag) moveTo(e.clientX, e.clientY, false); }
  function startGhost() {
      drag.on = true;
      var f = find(drag.id);
      drag.row.classList.add('dragging');
      var g = document.createElement('div');
      g.className = 'st-ghost';
      g.textContent = (f.node.t === 'f' ? '📁 ' : '') + f.node.name;
      document.body.appendChild(g);
      drag.ghost = g;
  }
  function moveTo(x, y, force) {
    if (!drag.on) {
      if (!force && Math.abs(x - drag.x) + Math.abs(y - drag.y) < 5) return;
      startGhost();
    }
    drag.ghost.style.left = (x + 12) + 'px';
    drag.ghost.style.top = (y - 10) + 'px';
    autoScroll(y);
    drag.target = pickTarget(x, y);
    paintTarget();
  }

  /* ── (124) 폰 터치 기록: 꾹 누름에서 나오는 contextmenu(삭제 질문)를 구분하려고 ── */
  var lastTouch = 0;
  function noteTouch() { lastTouch = Date.now(); }

  /* ── (124 v5.5) 폰: 접힌 탭 위아래로 끌어 옮기기 ── */
  var LS_TABY = 'sf-tree-tabY', tabDrag = null, tabJustMoved = false;
  function tabClamp(y) {
    var h = els.tab.offsetHeight || 80;
    return Math.max(56, Math.min(window.innerHeight - h - 8, y));
  }
  function placeTab() {
    if (!els.tab) return;
    var y = parseFloat(ls(LS_TABY));
    if (!isMobile() || isNaN(y)) { els.tab.style.top = ''; els.tab.style.bottom = ''; return; }
    els.tab.style.top = tabClamp(y) + 'px';
    els.tab.style.bottom = 'auto';
  }
  function bindTabDrag() {
    var t = els.tab;
    t.addEventListener('pointerdown', function (e) {
      if (!isMobile() || (e.button !== undefined && e.button !== 0)) return;
      var r = t.getBoundingClientRect();
      tabDrag = { x: e.clientX, y: e.clientY, off: e.clientY - r.top, offX: e.clientX - r.left, on: false };
      try { t.setPointerCapture(e.pointerId); } catch (err) {}
    });
    t.addEventListener('pointermove', function (e) {
      if (!tabDrag) return;
      if (!tabDrag.on) {
        if (Math.abs(e.clientY - tabDrag.y) + Math.abs(e.clientX - tabDrag.x) < 8) return;
        tabDrag.on = true;
        t.classList.remove('st-tab-snap');
        t.classList.add('st-tab-moving');
      }
      if (e.cancelable) e.preventDefault();
      t.style.top = tabClamp(e.clientY - tabDrag.off) + 'px';
      t.style.bottom = 'auto';
      t.style.left = Math.max(0, Math.min(window.innerWidth - t.offsetWidth, e.clientX - tabDrag.offX)) + 'px';
    });
    function end() {
      if (!tabDrag) return;
      var d = tabDrag; tabDrag = null;
      t.classList.remove('st-tab-moving');
      if (!d.on) return;
      // 왼쪽 벽으로 미끄러져 붙기 (left를 비우면 CSS 자리 = 0 또는 펼친 트리 옆)
      t.classList.add('st-tab-snap');
      t.style.left = '';
      setTimeout(function () { t.classList.remove('st-tab-snap'); }, 320);
      ls(LS_TABY, String(Math.round(parseFloat(t.style.top) || 0)));
      tabJustMoved = true;
      setTimeout(function () { tabJustMoved = false; }, 400);
    }
    t.addEventListener('pointerup', end);
    t.addEventListener('pointercancel', end);
    window.addEventListener('resize', placeTab);
    placeTab();
  }

  function autoScroll(y) {
    var r = els.list.getBoundingClientRect();
    if (y < r.top + 24) els.list.scrollTop -= 8;
    else if (y > r.bottom - 24) els.list.scrollTop += 8;
  }
  // 놓을 자리: {mode:'before'|'after'|'into'|'end', id}
  function pickTarget(x, y) {
    var lr = els.list.getBoundingClientRect();
    if (x < lr.left - 30 || x > lr.right + 60 || y < lr.top - 10 || y > lr.bottom + 10) return null;
    var me = find(drag.id);
    if (!me) return null;
    var rows = els.list.querySelectorAll('.st-row'), best = null;
    for (var i = 0; i < rows.length; i++) {
      var rr = rows[i].getBoundingClientRect();
      if (y >= rr.top && y < rr.bottom) { best = rows[i]; break; }
    }
    if (!best) {
      var last = rows[rows.length - 1];
      if (!last || y >= last.getBoundingClientRect().bottom) return valid({ mode: 'end' }, me);
      return null;
    }
    var id = best.getAttribute('data-id');
    if (id === drag.id) return null;
    var t = find(id), r = best.getBoundingClientRect(), rel = (y - r.top) / r.height, mode;
    if (t.node.t === 'f') mode = rel < 0.28 ? 'before' : (rel > 0.72 ? 'after' : 'into');
    else mode = rel < 0.5 ? 'before' : 'after';
    // 펼친 폴더 바로 아래 칸(after) = 그 폴더 안 맨 앞으로 보는 게 자연스러움
    if (mode === 'after' && t.node.t === 'f' && !fold[t.node.id] && t.node.kids.length) { var first = t.node.kids[0]; if (first.id !== drag.id) return valid({ mode: 'before', id: first.id }, me) || valid({ mode: 'into', id: id }, me); return null; }
    return valid({ mode: mode, id: id }, me) || (mode === 'into' ? valid({ mode: 'after', id: id }, me) : null);
  }
  function valid(tg, me) {
    var n = me.node, level;
    if (tg.mode === 'end') level = 0;
    else {
      var t = find(tg.id);
      if (!t) return null;
      if (n.t === 'f' && (t.node.id === n.id || isInside(n, t.node.id))) return null;   // 자기 안으로 못 감
      if (tg.mode === 'into') { if (t.node.t !== 'f') return null; level = t.level + 1; }
      else level = t.level;
    }
    if (n.t === 'f' && level + (hasSubFolder(n) ? 1 : 0) > 1) return null;   // 폴더 2단계까지
    return tg;
  }
  function paintTarget() {
    var rows = els.list.querySelectorAll('.st-row.into');
    for (var i = 0; i < rows.length; i++) rows[i].classList.remove('into');
    var tg = drag && drag.target, line = els.line;
    line.style.display = 'none';
    if (!tg) return;
    if (tg.mode === 'into') { var r0 = els.list.querySelector('.st-row[data-id="' + tg.id + '"]'); if (r0) r0.classList.add('into'); return; }
    var top, left = 6, lr = els.list.getBoundingClientRect();
    if (tg.mode === 'end') {
      var all = els.list.querySelectorAll('.st-row'), last = all[all.length - 1];
      top = last ? last.getBoundingClientRect().bottom - lr.top + els.list.scrollTop : 4;
    } else {
      var row = els.list.querySelector('.st-row[data-id="' + tg.id + '"]'), rr = row.getBoundingClientRect();
      top = (tg.mode === 'before' ? rr.top : rr.bottom) - lr.top + els.list.scrollTop;
      left = parseFloat(row.style.paddingLeft) || 6;
    }
    line.style.top = (top - 1) + 'px';
    line.style.left = left + 'px';
    line.style.display = 'block';
  }
  function endDrag() {
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    document.removeEventListener('pointercancel', onCancel);
    document.removeEventListener('keydown', onKey);
    if (drag && drag.ghost) drag.ghost.remove();
    if (drag && drag.row) drag.row.classList.remove('dragging');
    els.line.style.display = 'none';
    var rows = els.list.querySelectorAll('.st-row.into');
    for (var i = 0; i < rows.length; i++) rows[i].classList.remove('into');
  }
  function onCancel() { endDrag(); drag = null; }
  function onUp() {
    var d = drag;
    endDrag();
    drag = null;
    if (!d || !d.on) return;
    dragJustEnded = true;
    setTimeout(function () { dragJustEnded = false; }, 50);
    if (!d.target) return;
    moveNode(d.id, d.target);
  }
  function moveNode(id, tg) {
    change(function () {
      var me = find(id);
      if (!me) return;
      var node = me.list.splice(me.index, 1)[0];
      if (tg.mode === 'end') { tree.push(node); return; }
      var t = find(tg.id);
      if (!t) { me.list.splice(me.index, 0, node); return; }
      if (tg.mode === 'into') { t.node.kids.push(node); if (fold[t.node.id]) { delete fold[t.node.id]; saveFold(); } }
      else t.list.splice(t.index + (tg.mode === 'after' ? 1 : 0), 0, node);
    });
  }
  window.sfTreeMove = moveNode;   // (확인용) 콘솔에서 옮기기 시험

  /* ── PC: 왼쪽 여백 재서 모자라면 본문 밀기 ── */
  var basePad = null, layoutT = null;
  function contentLeft() {
    var W = window.innerWidth, best = Infinity;
    function scan(el, depth) {
      if (!el || el.nodeType !== 1) return;
      var id = el.id || '';
      if (id === 'sf-header' || id === 'sf-tree' || id === 'sf-tree-tab' || id === 'sf-tree-back' || id === 'sf-auth-gate' || id === 'sfSlotOverlay') return;
      var tag = el.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'LINK' || tag === 'NOSCRIPT') return;
      var cs = getComputedStyle(el);
      if (cs.position === 'fixed' || cs.display === 'none' || cs.visibility === 'hidden') return;
      var r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return;
      if (r.width < W - 30) { if (r.left < best) best = r.left; return; }
      var kids = el.children, any = false;
      if (depth < 4) for (var i = 0; i < kids.length; i++) { var b0 = best; scan(kids[i], depth + 1); if (best !== b0 || kids[i].getBoundingClientRect().width >= W - 30) any = true; }
      if (!any || depth >= 4) { var l = r.left + parseFloat(cs.paddingLeft || 0); if (l < best) best = l; }
    }
    var ch = document.body.children;
    for (var i = 0; i < ch.length; i++) scan(ch[i], 0);
    return best === Infinity ? 0 : best;
  }
  function setPad(px) {
    if (px > 0) document.body.style.setProperty('padding-left', px + 'px', 'important');
    else document.body.style.removeProperty('padding-left');
  }
  function layout() {
    var b = document.body.classList, on = b.contains('sf-tree-on') && !b.contains('sf-tree-hidden');
    var open = on && b.contains('sf-tree-open');
    setPad(0);
    if (!on || isMobile()) return;
    if (basePad === null) basePad = parseFloat(getComputedStyle(document.body).paddingLeft) || 0;
    // 닫혀 있어도 세로 탭(약 33px, 129에서 키움)이 본문 글자를 가리지 않게 — 본문이 왼쪽 끝까지 붙은 페이지만 그만큼 밂
    var target = open ? panelW() + 40 : 38, L0 = contentLeft();
    if (L0 >= target) return;
    var P = target - L0;
    setPad(basePad + P);
    var L1 = contentLeft();
    if (L1 < target - 1) {   // 가운데 정렬 본문은 민 만큼의 절반만 움직임 → 기울기로 다시 계산
      var slope = (L1 - L0) / P;
      if (slope > 0.05) { P = Math.min(800, (target - L0) / slope); setPad(basePad + P); }
    }
  }
  function relayoutSoon() { clearTimeout(layoutT); layoutT = setTimeout(layout, 120); }

  /* ── 시작: 관리자 로그인일 때만 ── */
  function showFor(u) {
    var ok = !!(u && window.SF_ADMIN_UIDS && window.SF_ADMIN_UIDS.indexOf(u.uid) !== -1);
    if (!ok) { uid = null; document.body.classList.remove('sf-tree-on'); layout(); return; }
    var key = OWNER_UIDS.indexOf(u.uid) !== -1 ? 'owner' : u.uid;
    realUid = u.uid;
    if (uid === key) return;
    uid = key;
    var c = null;
    try { c = JSON.parse(ls(LS_CACHE + uid) || 'null'); } catch (e) {}
    tree = c ? clean(c.tree, 0) : [];
    hist = c && Array.isArray(c.hist) ? c.hist.slice(-HIST_MAX) : [];
    fut = c && Array.isArray(c.fut) ? c.fut.slice(-HIST_MAX) : [];
    localAt = c && c.at || 0;
    remoteOk = null;
    render();
    document.body.classList.add('sf-tree-on');
    placeTab();
    setOpen(ls(LS_OPEN) === '1');
    loadRemote();
  }
  function setHidden(h) {
    document.body.classList.toggle('sf-tree-hidden', !!h);
    ls(LS_HIDE, h ? '1' : null);
    var hb = document.getElementById('sf-tree-hbtn');
    if (hb) hb.title = h ? '내 메뉴 보이기 (지금 숨김)' : '내 메뉴 숨기기 — 본문이 왼쪽 끝까지 쓰는 페이지에서';
    layout();
  }
  function addHeaderBtn(tries) {
    var tools = document.querySelector('#sf-header .sf-tools');
    if (!tools) { if ((tries || 0) < 50) setTimeout(function () { addHeaderBtn((tries || 0) + 1); }, 100); return; }
    if (document.getElementById('sf-tree-hbtn')) return;
    var hb = document.createElement('button');
    hb.id = 'sf-tree-hbtn'; hb.type = 'button'; hb.className = 'sf-btn'; hb.textContent = '📂';
    hb.addEventListener('click', function () { setHidden(!document.body.classList.contains('sf-tree-hidden')); });
    var guide = tools.querySelector('a[href="/guide/"]');
    tools.insertBefore(hb, guide || tools.firstChild);
    setHidden(ls(LS_HIDE) === '1');
  }
  function start() {
    try { fold = JSON.parse(ls(LS_FOLD) || '{}') || {}; } catch (e) { fold = {}; }
    build();
    els.tab.innerHTML = '<span class="st-arr">›</span> 내 메뉴';
    window.addEventListener('resize', relayoutSoon);
    window.addEventListener('pagehide', function () { if (saveTimer) saveRemote(); });
    addHeaderBtn();
    window.addEventListener('load', function () { setTimeout(layout, 300); });
    setTimeout(layout, 1500);
    var tries = 0;
    (function waitAuth() {
      if (window._sfFirebaseReady && window._sfFirebaseReady.promise) {
        window._sfFirebaseReady.promise.then(function (auth) { auth.onAuthStateChanged(showFor); });
      } else if (window._sfAuth) {
        window._sfAuth.onAuthStateChanged(showFor);
      } else if (++tries < 100) setTimeout(waitAuth, 100);
    })();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
