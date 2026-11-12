/* ════════════════════════════════════════════════════════════════
   메뉴 찾기 (089) — 메인(/)과 전체 메뉴(/1808/)에서 같이 씀
   ────────────────────────────────────────────────────────────────
   - 페이지 안의 a.card(메뉴 카드)를 그대로 읽어서 찾는다.
     → 메뉴를 추가·수정하면 카드만 고치면 됨. 이 파일은 안 고쳐도 됨.
   - 찾는 곳: 카드 제목 + 설명 + 카테고리 이름 (띄어쓰기 무시, 영문 대소문자 무시)
     띄어 쓰면 단어마다 따로 찾음: "배당 세금" → 배당·세금이 둘 다 들어간 메뉴가 위로
   - 순서 (위일수록 먼저):
       ① 제목에 친 글자가 그대로 들어있음
       ② 초성으로 제목이 맞음 (ㅂㄷㅅ → 부동산)
       ③ 설명·카테고리에 그대로 들어있음
       ④ 친 글자가 순서 상관없이 전부 들어있음
       ⑤ 한 글자라도 겹침 → 회색으로 맨 아래 따로 (사용자 요청: "1글자라도 겹치는 건 다 나오게")
          단, 초성만 친 경우(ㅂㄷㅅ)는 ⑤를 안 보여줌 — ㅅ 하나로 거의 전부 걸려서 의미 없음
   - 키보드: ↑↓ 고르기, Enter 이동, Esc 닫기. 입력칸 밖에서 / 누르면 바로 입력칸으로.
   - 페이지에 <div id="sfMenuSearch"></div> 자리만 있으면 됨. 스타일도 이 파일이 넣음(라이트+다크).
   ════════════════════════════════════════════════════════════════ */
(function(){
  var host = document.getElementById('sfMenuSearch');
  if(!host) return;

  /* ── 스타일 (라이트 + 다크) ── */
  var css = ''
  + '.ms-wrap{position:relative;margin:0 auto 18px;max-width:560px}'
  + '.ms-input{width:100%;box-sizing:border-box;font-size:15px;padding:11px 40px 11px 14px;border:2px solid #cbd5e1;border-radius:10px;background:#fff;color:#1a1a1a;font-family:inherit;outline:none;font-weight:500}'
  + '.ms-input:focus{border-color:#1F4E78;box-shadow:0 0 0 3px rgba(31,78,120,.12)}'
  + '.ms-clear{position:absolute;right:8px;top:50%;transform:translateY(-50%);border:none;background:#e5e7eb;color:#666;width:24px;height:24px;border-radius:50%;cursor:pointer;font-size:12px;display:none;line-height:24px;padding:0}'
  + '.ms-wrap.has-q .ms-clear{display:block}'
  + '.ms-drop{display:none;position:absolute;left:0;right:0;top:calc(100% + 6px);background:#fff;border:1px solid #d1d5db;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.14);z-index:50;max-height:62vh;overflow-y:auto;text-align:left}'
  + '.ms-wrap.open .ms-drop{display:block}'
  + '.ms-item{display:flex;align-items:flex-start;gap:10px;padding:9px 12px;text-decoration:none;color:inherit;border-bottom:1px solid #f1f5f9;cursor:pointer}'
  + '.ms-item:last-child{border-bottom:none}'
  + '.ms-item.sel,.ms-item:hover{background:#eef4fa}'
  + '.ms-ic{font-size:18px;line-height:1.3;flex:0 0 auto}'
  + '.ms-body{flex:1;min-width:0}'
  + '.ms-title{font-size:13.5px;font-weight:700;color:#1F4E78}'
  + '.ms-title mark{background:#fde68a;color:inherit;border-radius:2px;padding:0 1px}'
  + '.ms-cat{display:inline-block;font-size:10.5px;font-weight:600;color:#64748b;background:#f1f5f9;border-radius:8px;padding:1px 7px;margin-left:6px;vertical-align:1px}'
  + '.ms-desc{font-size:11.5px;color:#666;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'
  + '.ms-item.weak{opacity:.6}'
  + '.ms-sep{font-size:11px;color:#94a3b8;padding:6px 12px;background:#f8fafc;border-bottom:1px solid #f1f5f9}'
  + '.ms-empty{font-size:13px;color:#999;padding:16px;text-align:center}'
  + '.ms-help{font-size:11px;color:#94a3b8;padding:6px 12px;border-top:1px solid #f1f5f9;background:#f8fafc;position:sticky;bottom:0}'
  + 'body.sf-dark .ms-input{background:#222532;border-color:#475569;color:#e4e4e7}'
  + 'body.sf-dark .ms-input:focus{border-color:#60a5fa;box-shadow:0 0 0 3px rgba(96,165,250,.15)}'
  + 'body.sf-dark .ms-clear{background:#2a2d3a;color:#a1a1aa}'
  + 'body.sf-dark .ms-drop{background:#1a1d27;border-color:#2a2d3a;box-shadow:0 8px 24px rgba(0,0,0,.5)}'
  + 'body.sf-dark .ms-item{border-color:#2a2d3a}'
  + 'body.sf-dark .ms-item.sel,body.sf-dark .ms-item:hover{background:#1e3a5f}'
  + 'body.sf-dark .ms-title{color:#60a5fa}'
  + 'body.sf-dark .ms-title mark{background:#854d0e;color:#fef3c7}'
  + 'body.sf-dark .ms-cat{background:#2a2d3a;color:#a1a1aa}'
  + 'body.sf-dark .ms-desc{color:#a1a1aa}'
  + 'body.sf-dark .ms-sep,body.sf-dark .ms-help{background:#222532;border-color:#2a2d3a;color:#71717a}'
  + 'body.sf-dark .ms-empty{color:#71717a}'
  + '@media(max-width:600px){.ms-input{font-size:14px;padding:9px 36px 9px 12px}.ms-desc{font-size:10.5px}.ms-title{font-size:12.5px}}';
  var st = document.createElement('style');
  st.id = 'sf-menu-search-css';
  st.textContent = css;
  document.head.appendChild(st);

  /* ── 입력칸 ── */
  host.className = 'ms-wrap';
  host.innerHTML = '<input class="ms-input" type="search" autocomplete="off" spellcheck="false"'
    + ' placeholder="🔍 메뉴 찾기 — 한 글자만 쳐도 나옴 (초성 ㅂㄷㅅ 가능)" aria-label="메뉴 찾기">'
    + '<button type="button" class="ms-clear" title="지우기">✕</button>'
    + '<div class="ms-drop" role="listbox"></div>';
  var input = host.querySelector('.ms-input');
  var clearBtn = host.querySelector('.ms-clear');
  var drop = host.querySelector('.ms-drop');

  /* ── 글자 다루기 ── */
  var CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
  function norm(s){ return (s || '').toLowerCase().replace(/[\s·・\-_/()\[\]&,.:↗]+/g, ''); }
  function chosung(s){
    var out = '';
    for(var i = 0; i < s.length; i++){
      var c = s.charCodeAt(i);
      if(c >= 0xAC00 && c <= 0xD7A3) out += CHO[Math.floor((c - 0xAC00) / 588)];
      else out += s[i];
    }
    return out;
  }
  function isAllCho(s){ return s.length > 0 && /^[ㄱ-ㅎ]+$/.test(s); }
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

  /* ── 카드 읽기 (카테고리 이름: 메인 = 패널 제목, 1808 = 섹션 제목) ── */
  function catOf(card){
    var panel = card.closest('.tool-panel');
    if(panel){ var h = panel.querySelector('.panel-header h2'); if(h) return h.textContent.trim(); }
    var body = card.closest('.section-body[data-body]');
    if(body){
      var t = document.querySelector('.section-title[data-section="' + body.getAttribute('data-body') + '"]');
      if(t){ var c = t.cloneNode(true); c.querySelectorAll('.cnt,.arrow').forEach(function(x){ x.remove(); }); return c.textContent.trim(); }
    }
    return '';
  }
  var items = null;
  function build(){
    items = [];
    var byHref = {};
    function add(href, target, order, icon, title, desc, cat){
      if(!href) return;
      if(byHref[href]){   // 같은 메뉴가 두 카테고리에 있으면 한 줄로 합치고 카테고리만 이어 붙임
        var it0 = byHref[href];
        if(cat && it0.cat.indexOf(cat) < 0){ it0.cat += ' / ' + cat; it0.nRest = norm(it0.desc + ' ' + it0.cat); }
        return;
      }
      var it = {
        href: href, target: target || '', order: order, icon: icon || '📌', title: title, desc: desc, cat: cat,
        nTitle: norm(title), nRest: norm(desc + ' ' + cat), cho: norm(chosung(title))
      };
      byHref[href] = it;
      items.push(it);
    }
    document.querySelectorAll('.card').forEach(function(card, i){
      var t = card.querySelector('.card-title'), d = card.querySelector('.card-desc'), ic = card.querySelector('.icon');
      if(!t) return;
      var title = t.textContent.trim(), desc = d ? d.textContent.trim() : '', icon = ic ? ic.textContent.trim() : '';
      var cat = catOf(card);
      if(card.tagName === 'A'){
        add(card.getAttribute('href'), card.getAttribute('target'), i, icon, title, desc, cat);
      } else {
        // 링크가 카드 안에 따로 있는 카드(접속 통계 · 관리: GA / Firebase 버튼) → 버튼마다 한 줄
        card.querySelectorAll('a[href]').forEach(function(a, k){
          var c = a.cloneNode(true); c.querySelectorAll('.star-btn').forEach(function(x){ x.remove(); });   // 메인의 ☆ 버튼 글자 빼기
          add(a.getAttribute('href'), a.getAttribute('target'), i + k / 10, icon, title + ' — ' + c.textContent.trim(), desc, cat);
        });
      }
    });
  }

  /* ── 찾기 ── */
  function search(q){
    var nq = norm(q);
    if(!nq) return [];
    var chars = {};
    for(var i = 0; i < nq.length; i++) chars[nq[i]] = 1;
    var keys = Object.keys(chars);
    var choQ = isAllCho(nq);
    var words = (q || '').split(/\s+/).map(norm).filter(Boolean);   // "배당 세금"처럼 띄어 쓰면 단어마다 따로 찾음
    var multi = words.length > 1;
    function allIn(str){ return words.every(function(w){ return str.indexOf(w) >= 0; }); }
    var res = [];
    items.forEach(function(it){
      var all = it.nTitle + it.nRest;
      var hit = 0;
      keys.forEach(function(ch){ if(all.indexOf(ch) >= 0 || (choQ && it.cho.indexOf(ch) >= 0)) hit++; });
      var tier;
      if(it.nTitle.indexOf(nq) >= 0 || (multi && allIn(it.nTitle))) tier = 0;
      else if(choQ && it.cho.indexOf(nq) >= 0) tier = 1;
      else if(it.nRest.indexOf(nq) >= 0 || (multi && allIn(all))) tier = 2;
      else if(hit === keys.length) tier = 3;
      else if(hit > 0 && !choQ) tier = 4;   // 초성만 친 경우는 일부 겹침을 안 보여줌(ㅅ 하나로 거의 다 걸려서 의미 없음)
      else return;
      var tHit = 0;
      keys.forEach(function(ch){ if(it.nTitle.indexOf(ch) >= 0) tHit++; });
      res.push({it: it, tier: tier, hit: hit, tHit: tHit});
    });
    res.sort(function(a, b){
      return a.tier - b.tier || b.hit - a.hit || b.tHit - a.tHit || a.it.order - b.it.order;
    });
    return {list: res, chars: chars};
  }

  /* 제목에서 친 글자 표시 */
  function mark(title, chars){
    var out = '';
    for(var i = 0; i < title.length; i++){
      var ch = title[i];
      out += chars[ch.toLowerCase()] ? '<mark>' + esc(ch) + '</mark>' : esc(ch);
    }
    return out;
  }

  /* ── 그리기 ── */
  var rows = [], sel = -1;
  function render(){
    if(!items) build();
    var q = input.value;
    host.classList.toggle('has-q', !!q);
    if(!norm(q)){ host.classList.remove('open'); drop.innerHTML = ''; rows = []; sel = -1; return; }
    var r = search(q);
    var html = '', weakShown = false, strong = 0, weak = 0;
    r.list.forEach(function(x){ if(x.tier < 4) strong++; else weak++; });
    if(!r.list.length){
      html = '<div class="ms-empty">겹치는 메뉴가 없음</div>';
    } else {
      r.list.forEach(function(x, idx){
        if(x.tier === 4 && !weakShown){
          weakShown = true;
          html += '<div class="ms-sep">' + (strong ? '' : '정확히 맞는 메뉴 없음 · ') + '글자 일부만 겹침 (' + weak + '개)</div>';
        }
        var it = x.it;
        html += '<a class="ms-item' + (x.tier === 4 ? ' weak' : '') + '" data-i="' + idx + '" href="' + esc(it.href) + '"'
          + (it.target ? ' target="' + esc(it.target) + '" rel="noopener"' : '') + '>'
          + '<span class="ms-ic">' + esc(it.icon) + '</span><span class="ms-body">'
          + '<span class="ms-title">' + mark(it.title, r.chars) + '</span>'
          + (it.cat ? '<span class="ms-cat">' + esc(it.cat) + '</span>' : '')
          + '<div class="ms-desc">' + esc(it.desc) + '</div></span></a>';
      });
    }
    html += '<div class="ms-help">' + (r.list.length ? (strong + '개' + (weak ? ' + 일부 겹침 ' + weak + '개' : '') + ' · ') : '')
      + '↑↓ 고르고 Enter로 이동 · Esc 닫기 · 입력칸 밖에서 / 누르면 바로 찾기</div>';
    drop.innerHTML = html;
    drop.scrollTop = 0;
    rows = Array.prototype.slice.call(drop.querySelectorAll('.ms-item'));
    sel = rows.length ? 0 : -1;
    paintSel();
    host.classList.add('open');
  }
  function paintSel(){
    rows.forEach(function(r, i){ r.classList.toggle('sel', i === sel); });
    if(sel >= 0 && rows[sel]){
      var r = rows[sel], top = r.offsetTop, bot = top + r.offsetHeight;
      if(top < drop.scrollTop) drop.scrollTop = top - 30;
      else if(bot > drop.scrollTop + drop.clientHeight - 30) drop.scrollTop = bot - drop.clientHeight + 30;
    }
  }

  input.addEventListener('input', render);
  input.addEventListener('focus', function(){ if(input.value) render(); });
  input.addEventListener('keydown', function(e){
    if(e.key === 'ArrowDown'){ if(rows.length){ sel = (sel + 1) % rows.length; paintSel(); } e.preventDefault(); }
    else if(e.key === 'ArrowUp'){ if(rows.length){ sel = (sel - 1 + rows.length) % rows.length; paintSel(); } e.preventDefault(); }
    else if(e.key === 'Enter'){ if(sel >= 0 && rows[sel]){ e.preventDefault(); rows[sel].click(); } }
    else if(e.key === 'Escape'){
      if(host.classList.contains('open')) host.classList.remove('open');
      else { input.value = ''; render(); }
      e.preventDefault();
    }
  });
  drop.addEventListener('mousemove', function(e){
    var a = e.target.closest('.ms-item');
    if(!a) return;
    var i = rows.indexOf(a);
    if(i >= 0 && i !== sel){ sel = i; rows.forEach(function(r, k){ r.classList.toggle('sel', k === sel); }); }
  });
  clearBtn.addEventListener('click', function(){ input.value = ''; render(); input.focus(); });
  document.addEventListener('click', function(e){ if(!host.contains(e.target)) host.classList.remove('open'); });
  document.addEventListener('keydown', function(e){
    if(e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target, tag = t && t.tagName;
    if(tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
    e.preventDefault();
    input.focus();
    input.select();
  });

  window.SF_MENU_SEARCH = { search: function(q){ if(!items) build(); return search(q); } };  // 점검용
})();
