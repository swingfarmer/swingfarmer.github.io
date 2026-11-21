/* =============================================================
   /sf-live.js — 실시간·준실시간 페이지 공통 (122에서 만듦)
   ① 오른쪽 위 표시 「🔴 장중 · 11/24 10:31 기준 · 1분마다」 / 「11/21 18:45 기준 · 10분마다 확인」
   ② 다시 읽기 타이머 — 화면이 보일 때만(document.hidden 아님) 주기마다 load를 부름.
      다른 탭에 있다가 돌아오면 주기가 지났으면 바로, 아니면 남은 시간 뒤에.
      페이지 통째 새로고침은 하지 않는다(입력칸이 날아감) — load가 데이터 부분만 다시 그린다.

   쓰는 법 (head에서 sf-fmt.js 다음에 <script src="/sf-live.js?v=N"></script>):
     var live = sfLive({
       load: function(){ return Promise(결과) },   // 데이터 읽고 화면을 다시 그린 뒤 아래 info를 돌려줌
       // info = { at: '2026-11-24 10:31' | '2026-11-24' | Date, open: 장중이면 true,
       //          kind: '종가 ' 처럼 「기준」 앞에 붙일 말(없으면 생략),
       //          every: 다음까지 ms (없으면 아래 every 옵션),
       //          cycle: 주기 문구를 직접 줄 때(예: '화~토 아침 갱신'), every:0이면 타이머 멈춤,
       //          warn: 경고 문구(예: '갱신 멈춤') }
       every: 60000,        // 기본 주기 ms (info.every가 우선)
       mount: 요소,          // 없으면 페이지 첫 <h1> 오른쪽 위에 작은 표시를 만듦. 주면 그 요소 안에 글자만 넣음
       title: '마우스 올리면 나올 설명'   // 선택
     });
       start: false         // 선택 — 바로 읽지 않고 페이지가 live.now()를 부를 때 시작(기본 데이터를 먼저 그려야 할 때)
     live.now()       — 지금 바로 다시 읽기(🔄 버튼, start:false일 때 시작). 끝나면 resolve되는 Promise
     live.show(info)  — 타이머는 그대로 두고 표시만 info로 고정(미국 탭처럼 다른 데이터를 볼 때). live.show(null)이면 원래대로
   load가 실패(throw/reject)하면 표시 끝에 「⚠️ 못 읽음」을 붙이고 1분 뒤 다시 시도(주기가 더 짧으면 그 주기).
   주기 문구: 장중이면 「N분마다」, 장 밖이면 「N분마다 확인」(1분 미만은 초).
   목록은 sf-private/handoff/누적목록.md 7장 [자동 새로고침 목록]. VM node v12도 읽을 수 있게 옛 문법만 씀.
   ============================================================= */
(function () {
  if (window.sfLive) return;

  var css = '.sf-live{float:right;margin:6px 0 4px 12px;padding:3px 10px;border-radius:999px;font-size:12px;line-height:1.5;'
    + 'font-weight:500;white-space:nowrap;color:#475569;background:rgba(100,116,139,.09);border:1px solid rgba(100,116,139,.22);'
    + 'cursor:default;position:relative;z-index:1}'
    + '.sf-live b{color:#dc2626;font-weight:700}'
    + '.sf-live .sf-live-warn{color:#b45309;font-weight:600}'
    + 'body.sf-dark .sf-live{color:#a1a1aa;background:rgba(148,163,184,.08);border-color:rgba(148,163,184,.22)}'
    + 'body.sf-dark .sf-live b{color:#f87171}'
    + 'body.sf-dark .sf-live .sf-live-warn{color:#fbbf24}'
    + '.sf-live-in b{color:#dc2626;font-weight:700}.sf-live-in .sf-live-warn{color:#b45309;font-weight:600}'
    + 'body.sf-dark .sf-live-in b{color:#f87171}body.sf-dark .sf-live-in .sf-live-warn{color:#fbbf24}'
    + '@media (max-width:640px){.sf-live{float:none;display:table;margin:0 0 6px auto;font-size:11.5px;white-space:normal;text-align:right}}';
  function addCss() {
    if (document.getElementById('sf-live-css')) return;
    var s = document.createElement('style'); s.id = 'sf-live-css'; s.textContent = css;
    (document.head || document.documentElement).appendChild(s);
  }
  addCss();

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  // '2026-11-24 10:31(:00)( KST)' / '2026-11-24' / '20261124' / Date → '11/24 10:31' / '11/24'
  function fmtAt(x) {
    if (!x) return '';
    if (x instanceof Date) {
      var k = new Date(x.getTime() + 9 * 3600e3);   // 한국 시각
      return pad(k.getUTCMonth() + 1) + '/' + pad(k.getUTCDate()) + ' ' + pad(k.getUTCHours()) + ':' + pad(k.getUTCMinutes());
    }
    var m = String(x).match(/(\d{4})-?(\d{2})-?(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
    if (!m) return String(x);
    return m[2] + '/' + m[3] + (m[4] ? ' ' + m[4] + ':' + m[5] : '');
  }
  function fmtCycle(ms, open) {
    if (!(ms > 0)) return '';
    var t = ms < 60e3 ? Math.round(ms / 1000) + '초' : (ms % 60e3 ? (ms / 60e3).toFixed(1) : ms / 60e3) + '분';
    return t + '마다' + (open ? '' : ' 확인');
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  window.sfLive = function (opt) {
    opt = opt || {};
    var el = opt.mount || null, inline = !!opt.mount;
    var busyP = null, last = null, pinned = null, timer = null, lastAt = 0, cur = opt.every || 60e3, busy = false, failed = false;
    var title = opt.title || '기준 시각 = 화면에 보이는 데이터가 만들어진 시각. 이 화면이 보일 때만 주기마다 데이터만 다시 읽음(입력칸은 그대로). 다른 탭에 있다가 돌아오면 주기가 지났으면 바로 읽음.';

    function ensureEl() {
      if (el) return el;
      var h1 = document.querySelector('h1');
      el = document.createElement('span');
      el.className = 'sf-live';
      if (h1 && h1.parentNode) h1.parentNode.insertBefore(el, h1);
      else if (document.body) document.body.insertBefore(el, document.body.firstChild);
      return el;
    }
    function text(info) {
      if (!info) return failed ? '<span class="sf-live-warn">⚠️ 못 읽음 · 1분 뒤 다시</span>' : '불러오는 중…';
      var s = '';
      if (info.open) s += '🔴 <b>장중</b> · ';
      var at = fmtAt(info.at);
      if (at) s += esc(at) + ' ' + esc(info.kind || '') + '기준';
      var cy = info.cycle != null ? esc(info.cycle) : fmtCycle(info.every != null ? info.every : cur, info.open);
      if (cy) s += (s && !/· $/.test(s) ? ' · ' : '') + cy;
      if (info.warn) s += ' · <span class="sf-live-warn">⚠️ ' + esc(info.warn) + '</span>';
      if (failed) s += ' · <span class="sf-live-warn">⚠️ 못 읽음</span>';
      return s;
    }
    function render() {
      var e = ensureEl();
      if (!e) return;
      if (inline) { if (e.className.indexOf('sf-live-in') < 0) e.className += (e.className ? ' ' : '') + 'sf-live-in'; }
      var i = pinned || last;
      e.innerHTML = pinned ? text(pinned).replace(/ · <span class="sf-live-warn">⚠️ 못 읽음<\/span>$/, '') : text(last);
      e.title = title;
      e.setAttribute('data-sf-live', i && i.open ? 'open' : 'closed');
    }
    function schedule(ms) {
      clearTimeout(timer); timer = null;
      if (!(ms > 0)) return;
      timer = setTimeout(tick, ms);
    }
    function tick() {
      timer = null;
      if (document.hidden) return;   // 안 보이면 멈춤 — 돌아올 때 visibilitychange가 이어감
      run();
    }
    function run() {
      if (busy) return busyP;
      busy = true; lastAt = Date.now();
      var p;
      try { p = Promise.resolve(opt.load()); } catch (e) { p = Promise.reject(e); }
      return (busyP = p.then(function (info) {
        busy = false; failed = false;
        if (info) last = info;
        cur = last && last.every != null ? last.every : (opt.every || 60e3);
        render(); schedule(cur);
      }, function () {
        busy = false; failed = true;
        render(); schedule(Math.min(cur > 0 ? cur : 60e3, 60e3));
      }));
    }
    document.addEventListener('visibilitychange', function () {
      if (document.hidden || busy || !lastAt) return;
      var every = failed ? Math.min(cur > 0 ? cur : 60e3, 60e3) : cur;
      if (!(every > 0)) return;
      var left = every - (Date.now() - lastAt);
      if (left <= 0) { clearTimeout(timer); run(); } else schedule(left);
    });

    function start() { render(); if (opt.start !== false) run(); }
    if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);

    return {
      now: function () { clearTimeout(timer); return run(); },   // Promise(끝나면 resolve, 실패해도 resolve)
      show: function (info) { pinned = info || null; render(); },
      fmtAt: fmtAt
    };
  };
  window.sfLive.fmtAt = fmtAt;
})();
