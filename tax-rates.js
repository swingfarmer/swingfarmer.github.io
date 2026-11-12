/* 세율 공통 (086) — 세법이 바뀌면 이 파일 하나만 고치면 됨
 * 쓰는 법: 페이지에서 script 태그로 /tax-rates.js?v=2 를 페이지 스크립트보다 먼저 넣고 window.SF_TAX 를 읽는다.
 * 구간 배열: [[상한(원), 세율%], ...] 누진. 세율은 국세 기준, 지방소득세(국세의 10%)는 별도 → SF_TAX.wl(세율)로 포함값.
 * 바꾼 뒤: 이 파일 ?v= 를 쓰는 페이지 전부 올릴 것. 확인일(checked)도 고칠 것.
 * 이 파일을 쓰는 페이지: /bond/, /tax/stock-kr/, /tax/stock-us/  (나머지 세금 페이지는 순차 이전 예정)
 */
window.SF_TAX = Object.freeze({
  year: 2026,
  checked: '2026-11-13',
  // 이자·배당 원천징수 (소득세 14% + 지방소득세 1.4%)
  interest: 15.4,
  // 금융소득 종합과세 기준 (이자+배당, 연)
  finThreshold: 20000000,
  // 종합소득세 (소득세법 55조, 2023~)
  income: [[14e6,6],[50e6,15],[88e6,24],[150e6,35],[300e6,38],[500e6,40],[1e9,42],[Infinity,45]],
  // 법인세 일반법인 (법인세법 55조, 2026.1.1 이후 시작 사업연도)
  corp: [[2e8,10],[2e10,20],[3e11,22],[Infinity,25]],
  // 성실신고대상 소규모법인 (지배주주 50% 초과 + 상시근로자 5인 미만 + 임대·이자·배당 수입 50% 이상 등)
  corpSmall: [[2e10,20],[3e11,22],[Infinity,25]],
  // 지방소득세 = 국세 × 10%
  local: 0.1,
  // 해외주식 양도소득세 (지방세 포함 22%, 연 250만원 공제)
  overseasStock: {rate: 22, deduct: 2500000},
  // 증권거래세 (매도대금 대비 %, 2026.1.1 양도분부터) — 코스피는 거래세 0.05 + 농특세 0.15, 코스닥은 거래세 0.20 (087 확인)
  stockTx: {kospi: 0.20, kosdaq: 0.20},
  // 국내주식 대주주 양도소득세 (국세 %, 지방세 별도 → wl) — 과표 3억 이하 20, 초과 25 / 1년 미만 보유 30
  majorCgt: [[3e8,20],[Infinity,25]],
  majorCgtShort: 30,
  // 대주주 판정 (종목별) — 평가액 50억 이상, 또는 지분율 코스피 1%·코스닥 2% 이상 (2025.9 정부가 10억 하향안 철회, 087 확인)
  majorHold: {amount: 5e9, kospiPct: 1, kosdaqPct: 2},
  wl: function(r){ return Math.round(r*1.1*100)/100; },
  // 누진 구간 세금(국세) — prog(과표, SF_TAX.corp) 처럼 쓴다. 지방세 포함은 결과 × (1 + local)
  prog: function(base, br){ var t=0, lo=0; if(!(base>0)) return 0; for(var i=0;i<br.length;i++){ var hi=br[i][0]; if(base>lo){ t += (Math.min(base,hi)-lo)*br[i][1]/100; } lo=hi; } return t; }
});
