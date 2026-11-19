/* regime_calc.js (116) — 시장 국면 점수를 VM에서 계산해 JSON으로 출력
 * 점수 기준은 사이트 /sf-regime.js 한 곳 — 이 파일은 그 파일을 그대로 읽어 _compute만 부른다 (파이썬으로 다시 쓰지 않음).
 * 표기 함수(sfNum·sfPct·sfKor·sfDate)는 /sf-fmt.js.
 * 사용: node scripts/regime_calc.js [레포 경로]   → regime_alert.py가 부름
 * node 12(VM, apt)에서 돌게 옛 문법만 씀.
 */
var fs = require('fs'), path = require('path'), vm = require('vm');
var root = process.argv[2] || path.join(__dirname, '..');

var ctx = { console: console };
ctx.window = ctx;
vm.createContext(ctx);
['sf-fmt.js', 'sf-regime.js'].forEach(function (f) {
  vm.runInContext(fs.readFileSync(path.join(root, f), 'utf8'), ctx, { filename: f });
});

function rd(rel) {
  try { return JSON.parse(fs.readFileSync(path.join(root, 'data', rel), 'utf8')); } catch (e) { return null; }
}
var a = ['market_indicators.json', 'market_history.json', 'buffett.json', 'krx/new_high_low.json',
  'dashboard/putcall.json', 'dashboard/foreign_flow.json', 'dashboard/market_funds.json'].map(rd);
var missing = ['시장지표', '히스토리', '버핏', '신고신저', '풋콜', '외국인', '증시자금'].filter(function (n, i) { return !a[i]; });

var R = ctx.sfRegime._compute.apply(null, a);
process.stdout.write(JSON.stringify({
  date: a[3] && a[3].date || null,          // 신고가·신저가 날짜 = 한국 거래일 (하루 기준)
  auto: R.auto, avg: R.avg, n: R.S.length, total: R.I.length,
  I: R.I.map(function (x) { return { n: x.n, v: x.v, s: x.s }; }),
  name: R.NAME, cut: R.CUT, missing: missing
}));
