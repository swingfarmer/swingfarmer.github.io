/* sf-fmt.js — 사이트 공통 표기 함수 (102, 103: kor·korc 라벨 형식, full·man 조, 106: sfNum·sfPct·sfDate)
 * common.js를 쓰는 모든 페이지가 <head>에서 읽음 (auth-guard.css 바로 앞).
 * common.js는 body 끝에서 읽는 페이지가 많아서, 페이지 스크립트가 바로 부르는 함수는 여기 둠.
 */
(function () {
  // (102) 금액 한글 표기 공통 — 페이지에 사본 두지 말고 sfKor(n, 형식)
  //   'full'(기본) 1억 2,345만 6,789원 / 'man' 1억 2,345만원(만 아래 버림, 1만 미만은 원까지) — (103) 1조 이상은 「1조 2,345억 …원」
  //   'short' 1.23억 · 1,235만 · 5,000 (원 안 붙음, 억·조는 소수 둘째 자리까지·끝 0 뺌)
  //   'eok'   1,234억 · 5,679만 · 5,000 (원 안 붙음, 억·만 정수 — 거래대금 표처럼 같은 단위로 견줄 때, 조로 안 올림)
  //   (103) 'kor'  2억 · 1억 5,000만 · 5,000만 · 3,000억 (원 안 붙음, 만 단위 반올림, 조로 안 올림 — 법 구간·공제 한도 같은 라벨)
  //   (103) 'korc' kor 와 같고 1억 미만 천만 단위면 「5천만」
  //   0 → '0원'(short·eok·kor·korc '0'), 음수 '-', 숫자 아니면 ''
  //   셋째 인자: 0일 때 대신 쓸 글 — 숫자 옆 보조 표기는 sfKor(n, 'full', '') 로 0이면 비움
  function sfKor(n, mode, zero) {
    n = Number(n);
    if (!isFinite(n)) return '';
    var r = Math.round(Math.abs(n)), s = (n < 0 && r) ? '-' : '';
    if (mode === 'eok') {
      if (!r && zero !== undefined) return zero;
      if (r < 1e4) return s + r.toLocaleString('ko-KR');
      var mm = Math.round(r / 1e4);
      if (mm < 1e4) return s + mm.toLocaleString('ko-KR') + '만';
      return s + Math.round(r / 1e8).toLocaleString('ko-KR') + '억';
    }
    if (mode === 'kor' || mode === 'korc') {
      if (!r) return zero !== undefined ? zero : '0';
      var M = Math.round(r / 1e4), ke = Math.floor(M / 1e4), km = M % 1e4;
      if (ke) return s + ke.toLocaleString('ko-KR') + '억' + (km ? ' ' + km.toLocaleString('ko-KR') + '만' : '');
      if (mode === 'korc' && km && km % 1000 === 0) return s + (km / 1000) + '천만';
      return s + km.toLocaleString('ko-KR') + '만';
    }
    if (mode === 'short') {
      if (!r && zero !== undefined) return zero;
      if (r < 1e4) return s + r.toLocaleString('ko-KR');
      var m = Math.round(r / 1e4);
      if (m < 1e4) return s + m.toLocaleString('ko-KR') + '만';
      var e = Math.round(r / 1e6) / 100;
      if (e < 1e4) return s + e.toLocaleString('ko-KR', {maximumFractionDigits: 2}) + '억';
      return s + (Math.round(r / 1e10) / 100).toLocaleString('ko-KR', {maximumFractionDigits: 2}) + '조';
    }
    if (!r) return zero !== undefined ? zero : '0원';
    var eok = Math.floor(r / 1e8), man = Math.floor((r % 1e8) / 1e4), won = r % 1e4, p = [];
    if (mode === 'man' && r >= 1e4) won = 0;
    if (eok >= 1e4) { p.push(Math.floor(eok / 1e4).toLocaleString('ko-KR') + '조'); eok = eok % 1e4; }   // (103) 조
    if (eok > 0) p.push(eok.toLocaleString('ko-KR') + '억');
    if (man > 0) p.push(man.toLocaleString('ko-KR') + '만');
    if (won > 0) p.push(won.toLocaleString('ko-KR'));
    return s + p.join(' ') + '원';
  }
  window.sfKor = sfKor;

  // (106) 숫자·퍼센트·날짜 표기 공통 — 페이지에 사본 두지 말고 한 줄 래퍼만 (예: const fmt = n => sfNum(n);)
  //   숫자가 아니거나 null·undefined·'' → empty(기본 '-'), 「-0」은 「0」
  function bad(n) { return n === null || n === undefined || n === '' || !isFinite(Number(n)); }
  function noNegZero(s) { return /^-0(\.0+)?$/.test(s) ? s.slice(1) : s; }

  //   sfNum(n)        1,235          정수로 반올림(Math.round) + 쉼표
  //   sfNum(n, 2)     1,234.50       소수 2자리 고정
  //   sfNum(n, '~2')  1,234.5        소수 최대 2자리(끝 0 뺌)
  function sfNum(n, d, empty) {
    if (bad(n)) return empty === undefined ? '-' : empty;
    n = Number(n);
    if (d === undefined || d === null) return noNegZero(Math.round(n).toLocaleString('ko-KR'));
    var o = (typeof d === 'string' && d.charAt(0) === '~')
      ? {maximumFractionDigits: +d.slice(1)}
      : {minimumFractionDigits: d, maximumFractionDigits: d};
    return noNegZero(n.toLocaleString('ko-KR', o));
  }

  //   sfPct(v)        12.35%         v는 이미 % 값(0.1235가 아니라 12.35). 비율이면 sfPct(r * 100)
  //   sfPct(v, 1)     12.3%          소수 자리(기본 2), 쉼표 없음(toFixed)
  //   sfPct(v, 2, 1)  +12.35%        셋째 인자 참이면 양수에 + (0.00%에는 안 붙음)
  function sfPct(v, d, sign, empty) {
    if (bad(v)) return empty === undefined ? '-' : empty;
    var s = noNegZero(Number(v).toFixed(d === undefined || d === null ? 2 : d));
    return (sign && Number(s) > 0 ? '+' : '') + s + '%';
  }

  //   sfDate(x, 형식)  x: Date·문자열('2026-11-17 14:05' 가능)·숫자(ms), 생략하면 지금. 항상 「이 컴퓨터 시각(한국)」 기준
  //   'ymd'(기본) 2026-11-17 / 'ym' 2026-11 / 'ymd8' 20261117 / 'dot' 2026.11.17 / 'dotm' 2026.11.17 14:05
  //   'md' 11/17 / 'hm' 14:05 / 'short' 오늘이면 14:05, 올해면 11.17., 아니면 2026.11.17.
  //   ※ new Date().toISOString().slice(0,10)은 UTC 날짜라 한국 0~9시에 「어제」가 나옴 → 쓰지 말고 sfDate()
  //   읽을 수 없는 날짜 → 문자열이면 그대로, 아니면 ''
  function sfDate(x, mode) {
    var d = x === undefined ? new Date() : (x instanceof Date ? x : new Date(typeof x === 'string' ? x.replace(' ', 'T') : x));
    if (!x && x !== undefined && x !== 0) return '';
    if (isNaN(d)) return typeof x === 'string' ? x : '';
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    var Y = d.getFullYear(), M = p(d.getMonth() + 1), D = p(d.getDate()), hm = p(d.getHours()) + ':' + p(d.getMinutes());
    switch (mode) {
      case 'ym': return Y + '-' + M;
      case 'ymd8': return '' + Y + M + D;
      case 'dot': return Y + '.' + M + '.' + D;
      case 'dotm': return Y + '.' + M + '.' + D + ' ' + hm;
      case 'md': return (d.getMonth() + 1) + '/' + d.getDate();
      case 'hm': return hm;
      case 'short':
        var now = new Date();
        if (d.toDateString() === now.toDateString()) return hm;
        if (Y === now.getFullYear()) return M + '.' + D + '.';
        return Y + '.' + M + '.' + D + '.';
      default: return Y + '-' + M + '-' + D;
    }
  }
  window.sfNum = sfNum;
  window.sfPct = sfPct;
  window.sfDate = sfDate;
})();
