/* ============================================
   스윙파머 공통 스크립트 (common.js)
   - 상단 고정 헤더 (메인 링크 + 다크모드 + 글자크기 + 문의)
   - 다크모드 (localStorage 저장)
   - 글자크기 4단계 (작게/기본/크게/더크게)
   사용법: 각 페이지 <head> 또는 <body> 끝에
   <script src="/common.js"></script> 한 줄 추가
   ============================================ */

(function () {
  'use strict';

  var KAKAO_URL = 'https://open.kakao.com/o/svyzG3wi';
  var MAIN_URL = '/';

  // ---------- 1. 공통 스타일 주입 ----------
  var css = `
  :root {
    --sf-font-scale: 1;
  }
  /* 헤더 높이만큼 본문 밀기 */
  body { padding-top: 56px !important; }
  body.sf-has-notice { padding-top: 90px !important; }

  /* === 공지 띠 (헤더 바로 아래) === */
  #sf-notice {
    position: fixed; top: 56px; left: 0; right: 0; z-index: 99998;
    background: #fef3c7; color: #92400e;
    border-bottom: 1px solid #fde68a;
    padding: 7px 16px;
    font-size: 12.5px; font-weight: 500;
    display: flex; align-items: center; justify-content: center; gap: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
  }
  #sf-notice .sf-notice-text { flex: 1; text-align: center; line-height: 1.4; }
  #sf-notice .sf-notice-text b { color: #b45309; }
  #sf-notice .sf-notice-close {
    background: rgba(0,0,0,0.08); border: none; color: #92400e;
    width: 22px; height: 22px; border-radius: 50%; cursor: pointer;
    font-size: 14px; line-height: 1; display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; transition: background 0.15s;
  }
  #sf-notice .sf-notice-close:hover { background: rgba(0,0,0,0.18); }
  body.sf-dark #sf-notice {
    background: #1a2c42; color: #fcd34d;
    border-bottom-color: #1e3a5f;
  }
  body.sf-dark #sf-notice .sf-notice-text b { color: #fbbf24; }
  body.sf-dark #sf-notice .sf-notice-close { background: rgba(255,255,255,0.1); color: #fcd34d; }
  body.sf-dark #sf-notice .sf-notice-close:hover { background: rgba(255,255,255,0.18); }
  @media (max-width: 600px) {
    #sf-notice { font-size: 11.5px; padding: 6px 12px; }
  }

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
    width: 28px; height: 28px; border-radius: 6px;
    background: linear-gradient(135deg, #fff, #cfe0f5);
    display: flex; align-items: center; justify-content: center;
    font-size: 16px;
  }
  #sf-header .sf-tools { display: flex; align-items: center; gap: 6px; }
  #sf-header .sf-btn {
    background: rgba(255,255,255,0.14); border: none; color: #fff;
    width: 36px; height: 36px; border-radius: 8px; cursor: pointer;
    font-size: 15px; display: flex; align-items: center; justify-content: center;
    transition: background 0.15s; padding: 0; line-height: 1;
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
  `;

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
        '<span class="sf-logo-icon">📈</span>' +
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
        '<a class="sf-btn wide label-hide" href="' + KAKAO_URL + '" target="_blank" title="수정사항 문의">💬<span class="txt">문의</span></a>' +
      '</div>';
    document.body.insertBefore(header, document.body.firstChild);
  }

  // ---------- 2-B. 공지 띠 생성 ----------
  function buildNotice() {
    // 세션 동안 이미 닫았는지 확인
    try {
      if (sessionStorage.getItem('sf-notice-closed') === '1') return;
    } catch (e) {}

    var notice = document.createElement('div');
    notice.id = 'sf-notice';
    notice.innerHTML =
      '<div class="sf-notice-text">ℹ️ <b>모든 계산기는 입력 기록이 저장되지 않습니다.</b> 새로고침하면 사라져요. 민감 정보 안심하고 입력하세요.</div>' +
      '<button class="sf-notice-close" id="sf-notice-close" title="이 세션 동안 숨기기">✕</button>';
    document.body.insertBefore(notice, document.body.firstChild.nextSibling);
    document.body.classList.add('sf-has-notice');

    document.getElementById('sf-notice-close').addEventListener('click', function () {
      notice.remove();
      document.body.classList.remove('sf-has-notice');
      try { sessionStorage.setItem('sf-notice-closed', '1'); } catch (e) {}
    });
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

  // ---------- 5. 초기화 + 이벤트 ----------
  function init() {
    buildHeader();
    buildNotice();

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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
