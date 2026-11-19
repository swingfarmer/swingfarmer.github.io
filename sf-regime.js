/* ============================================================
   sf-regime.js v1 (115) — 시장 국면 점수 (공포·혼조·과열) 공통 계산
   - 원래 /today/ 안에 있던 코드(107·108)를 그대로 옮긴 것. /today/ 「🧭 시장 국면」과 /guide/ 「국면별」이 같이 씀.
   - 점수 기준을 바꿀 때는 여기 한 곳만 고친다 → 두 페이지가 같이 바뀜.
   - 지표마다 −2(공포) ~ +2(과열), 평균이 CUT.hot 이상 과열 / CUT.fear 이하 공포 / 그 사이 혼조.
   - 필요: /sf-fmt.js (sfNum·sfPct·sfKor·sfDate) — 부를 때만 씀.
   사용: sfRegime().then(R => { R.auto('hot'|'mix'|'fear'), R.avg, R.I(지표 목록), R.S(점수 있는 지표), R.src(원본 json) })
   ============================================================ */
(function () {
  var CUT = { hot: 0.8, fear: -0.8 };
  var NAME = { hot: '🔥 과열 — 경계', mix: '🌫 혼조 — 희망+경계', fear: '🧊 공포 — 희망' };
  window.SF_REGIME_CUT = CUT;
  window.SF_REGIME_NAME = NAME;

  var B = '/data';
  function grade(v, cuts) { // cuts=[c2,c1,c-1,c-2] : v>=c2 +2, >=c1 +1, >c-1 0, >c-2 -1, else -2
    if (v == null || !isFinite(v)) return null;
    return v >= cuts[0] ? 2 : v >= cuts[1] ? 1 : v > cuts[2] ? 0 : v > cuts[3] ? -1 : -2;
  }
  function rsi(c, n) {
    n = n || 14;
    if (c.length < n + 1) return null;
    var g = 0, l = 0, i, d;
    for (i = 1; i <= n; i++) { d = c[i] - c[i - 1]; d > 0 ? g += d : l -= d; }
    g /= n; l /= n;
    for (i = n + 1; i < c.length; i++) { d = c[i] - c[i - 1]; g = (g * (n - 1) + Math.max(d, 0)) / n; l = (l * (n - 1) + Math.max(-d, 0)) / n; }
    return l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  function j(u) { return fetch(B + u).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }

  function compute(mkt, hist, buf, nhl, pc, ff, mf) {
    var I = [];
    var vix = mkt && (mkt.indicators || []).find(function (x) { return x.ticker === '^VIX'; });
    if (vix) I.push({ n: 'VIX (미국 공포지수)', v: sfNum(vix.price, 2), s: grade(-vix.price, [-13, -16, -22, -30]), d: '13↓ +2 · 16↓ +1 · 22~30 −1 · 30↑ −2' });
    var ks = (hist || []).map(function (r) { return r.KS11; }).filter(function (x) { return x != null; });
    if (ks.length > 60) {
      var last = ks[ks.length - 1], r = rsi(ks.slice(-120));
      I.push({ n: '코스피 RSI(14)', v: sfNum(r, 1), s: grade(r, [70, 60, 40, 30]), d: '70↑ +2 · 60↑ +1 · 40~30 −1 · 30↓ −2' });
      var ma20 = ks.slice(-20).reduce(function (a, b) { return a + b; }, 0) / 20, gap = last / ma20 * 100;
      I.push({ n: '코스피 20일 이격도', v: sfNum(gap, 1), s: grade(gap, [108, 104, 96, 92]), d: '108↑ +2 · 104↑ +1 · 96~92 −1 · 92↓ −2' });
      var hi = Math.max.apply(null, ks.slice(-250)), dd = (last / hi - 1) * 100;
      I.push({ n: '코스피 52주 고점 대비', v: sfPct(dd, 1, 1), s: dd >= -3 ? 1 : dd > -10 ? 0 : dd > -20 ? -1 : -2, d: '−3% 안 +1 · −10~−20% −1 · −20%↓ −2 (고점 ' + sfNum(hi, 0) + ')' });
    }
    if (buf && buf.buffett_index != null) {
      var b = buf.buffett_index;
      I.push({ n: '버핏지수 (한국)', v: sfPct(b, 0), s: grade(b, [200, 150, 100, 80]), d: '200↑ +2 · 150↑ +1 · 100~80 −1 · 80↓ −2 (10년 평균 95, 최고 261)' });
    }
    if (nhl && nhl.all) {
      var net = nhl.all.high_pct - nhl.all.low_pct;
      I.push({ n: '신고가 − 신저가 (전체 %)', v: sfPct(net, 1, 1), s: grade(net, [5, 1, -3, -10]), d: '신고 ' + nhl.all.new_high + ' · 신저 ' + nhl.all.new_low + ' · 5↑ +2 · 1↑ +1 · −3~−10 −1 · −10↓ −2' });
    }
    if (pc && pc.latest && pc.latest.ma5 != null) {
      var p = pc.latest.ma5;
      I.push({ n: '풋콜비율 SPY (5일)', v: sfNum(p, 2), s: grade(-p, [-0.9, -1.0, -1.2, -1.4]), d: '0.9↓ +2 · 1.0↓ +1 · 1.2~1.4 −1 · 1.4↑ −2' });
    }
    if (ff && ff.latest) {
      var L = ff.latest, sc = L.consec_buy >= 5 ? 1 : L.consec_sell >= 5 ? -1 : 0;
      I.push({ n: '외국인 현물 (코스피200)', v: L.consec_buy ? L.consec_buy + '일 연속 순매수' : L.consec_sell ? L.consec_sell + '일 연속 순매도' : '-', s: sc, d: '5일↑ 연속 순매수 +1 · 연속 순매도 −1 (±1까지만)' });
    }
    // (108) 코스피 PER·신용잔고÷예탁금 — 10년 안 백분위로 점수 (data/dashboard/market_funds.json, fetch_market_funds.py)
    if (mf && mf.latest) {
      var M = mf.latest, eok = function (v) { return sfKor(v * 1e8, 'short'); };
      if (M.per != null) I.push({ n: '코스피 PER (10년 백분위)', v: sfNum(M.per, 2) + '배 · ' + sfNum(M.per_pct, 0) + '%', s: grade(M.per_pct, [90, 70, 30, 10]),
        d: '백분위 90↑ +2 · 70↑ +1 · 30~10 −1 · 10↓ −2 · PBR ' + sfNum(M.pbr, 2) + ' (' + sfNum(M.pbr_pct, 0) + '%) · 이익이 갑자기 늘면 PER은 싸 보임(' + sfDate(M.per_date, 'md') + ')' });
      if (M.lev != null) I.push({ n: '신용잔고 ÷ 예탁금 (10년 백분위)', v: sfPct(M.lev, 1) + ' · ' + sfNum(M.lev_pct, 0) + '%', s: grade(M.lev_pct, [90, 70, 30, 10]),
        d: '백분위 90↑ +2 · 70↑ +1 · 30~10 −1 · 10↓ −2 · 신용 ' + eok(M.credit) + ' ÷ 예탁금 ' + eok(M.dep) + ' · 20일 예탁금 ' + sfPct(M.dep_20d, 1, 1) + ' (' + sfDate(M.funds_date, 'md') + ', 금투협)' });
    }
    var S = I.filter(function (x) { return x.s != null; });
    var avg = S.length ? S.reduce(function (a, b) { return a + b.s; }, 0) / S.length : 0;
    var auto = avg >= CUT.hot ? 'hot' : avg <= CUT.fear ? 'fear' : 'mix';
    return { I: I, S: S, avg: avg, auto: auto, NAME: NAME, CUT: CUT, src: { mkt: mkt, hist: hist, buf: buf, nhl: nhl, pc: pc, ff: ff, mf: mf } };
  }

  var _p = null;
  window.sfRegime = function () {
    if (_p) return _p;
    _p = Promise.all([j('/market_indicators.json'), j('/market_history.json'), j('/buffett.json'), j('/krx/new_high_low.json'),
      j('/dashboard/putcall.json'), j('/dashboard/foreign_flow.json'), j('/dashboard/market_funds.json')])
      .then(function (a) { return compute.apply(null, a); });
    return _p;
  };
  window.sfRegime._compute = compute;   // 검증용
})();
