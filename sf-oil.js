/* sf-oil.js — 오피넷 국제유가·석유제품 공통 (113)
 * 데이터: VM이 화~토 21:20 오피넷에서 받아 Oracle OIL_INTL_PRICES에 쌓음(하루 늦게 올라옴, fetch_opinet_oil.py).
 *   오피넷 약관(복제·유통·제3자 이용 금지) 때문에 공개 JSON 없음 → 관리자 로그인 API /api/oil-intl 로만 읽음.
 * 쓰는 곳: /indicators/ (⛽ 국제유가·석유제품 칸), 🔒 /stock-tools/kal/ (항공유·두바이 추세)
 *
 *   sfOilLoad(cb, days)  로그인을 최대 15초 기다린 뒤 일별 자료를 읽어 cb(rows) / 못 읽으면 cb(null, 이유)
 *                        이유: 'login'(로그인 안 함) · 'http'(API 오류) · 'empty'(자료 없음)
 *                        rows = 날짜 오름차순 [{price_date, dubai, brent, wti, kero(=항공유, 싱가포르 등유),
 *                                gas92, gas95, diesel001, diesel005, hsfo, naphtha, spread(=kero−dubai)}]
 *                        0·음수는 휴장·결측이라 null로 바꿈(107 규칙: 0을 값으로 쓰지 않음)
 *   sfOilAvg(rows, mode, keys)  mode 'm'(월) / 'q'(분기) → 위가 최근, [{k, n, ongoing, 키별 평균}]
 *                        평균은 값 있는 날만의 단순 평균. 맨 위 기간이 아직 안 끝났으면 ongoing=true
 */
(function () {
  var API = 'https://swingfarmer.duckdns.org/api/oil-intl';
  var COLS = ['dubai', 'brent', 'wti', 'kero', 'gas92', 'gas95', 'diesel001', 'diesel005', 'hsfo', 'naphtha'];
  var cache = {};

  function clean(data) {
    return (data || []).map(function (r) {
      var o = { price_date: r.price_date };
      COLS.forEach(function (k) { var v = +r[k]; o[k] = (r[k] != null && v > 0) ? v : null; });
      o.spread = (o.kero != null && o.dubai != null) ? Math.round((o.kero - o.dubai) * 100) / 100 : null;
      return o;
    }).filter(function (o) { return COLS.some(function (k) { return o[k] != null; }); });
  }

  window.sfOilLoad = function (cb, days) {
    days = days || 1100;
    if (cache[days]) return cb(cache[days]);
    (function wait(tries) {
      var u = window._sfAuth && window._sfAuth.currentUser;
      if (!u) { if (tries < 30) return setTimeout(function () { wait(tries + 1); }, 500); return cb(null, 'login'); }
      u.getIdToken().then(function (t) {
        return fetch(API + '?days=' + days, { headers: { Authorization: 'Bearer ' + t } });
      }).then(function (r) { return r.ok ? r.json() : Promise.reject('http'); })
        .then(function (d) {
          var rows = clean(d && d.data);
          if (!rows.length) return cb(null, 'empty');
          cache[days] = rows; cb(rows);
        }).catch(function () { cb(null, 'http'); });
    })(0);
  };

  window.sfOilAvg = function (rows, mode, keys) {
    keys = keys || COLS.concat(['spread']);
    var key = function (r) {
      var y = r.price_date.slice(0, 4), m = +r.price_date.slice(5, 7);
      return mode === 'q' ? y + ' ' + Math.ceil(m / 3) + 'Q' : y + '-' + String(m).padStart(2, '0');
    };
    var G = {};
    rows.forEach(function (r) {
      var k = key(r), g = G[k] || (G[k] = { k: k, n: 0, v: {} });
      g.n++;
      keys.forEach(function (c) { if (r[c] != null) (g.v[c] = g.v[c] || []).push(r[c]); });
    });
    var out = Object.keys(G).sort().reverse().map(function (k) {
      var g = G[k], o = { k: k, n: g.n };
      keys.forEach(function (c) { var a = g.v[c]; o[c] = a && a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : null; });
      return o;
    });
    if (out.length && rows.length) {   // 맨 위 기간이 아직 안 끝났으면 표시 (마지막 자료일 기준)
      var L = rows[rows.length - 1].price_date, mm = +L.slice(5, 7), endM = mode === 'q' ? Math.ceil(mm / 3) * 3 : mm;
      var lastDay = new Date(+L.slice(0, 4), endM, 0).getDate();
      if (endM !== mm || +L.slice(8, 10) < lastDay - 3) out[0].ongoing = true;
    }
    return out;
  };
})();
