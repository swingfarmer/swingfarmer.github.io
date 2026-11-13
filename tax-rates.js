/* 세율 공통 (086) — 세법이 바뀌면 이 파일 하나만 고치면 됨
 * 쓰는 법: 페이지에서 script 태그로 /tax-rates.js?v=10 를 페이지 스크립트보다 먼저 넣고 window.SF_TAX 를 읽는다.
 * 구간 배열: [[상한(원), 세율%], ...] 누진. 세율은 국세 기준, 지방소득세(국세의 10%)는 별도 → SF_TAX.wl(세율)로 포함값.
 * 바꾼 뒤: 이 파일 ?v= 를 쓰는 페이지 전부 올릴 것. 확인일(checked)도 고칠 것.
 * 이 파일을 쓰는 페이지: /bond/, /tax/stock-kr/, /tax/stock-us/, /dividend-manager/, /property/, /realestate/entity-choice/, /realestate/commercial-yield/, /tax/income/, /tax/retirement/, /tax/retirement-compare/, /severance-exec/, /salary/, /insurance4/, /tax/corp-invest/, /tax/house/, /tax/land/, /realestate/home-swap/, /stock-tools/dividend/, /finance-tools/compound/, /fire/, /tax/financial-income/, /barbell/, /paygrowth/, /landtax/  (나머지 세금 페이지는 순차 이전 예정)
 */
window.SF_TAX = Object.freeze({
  year: 2026,
  checked: '2026-11-13',  // 089: 4대보험·간이세액표 자녀·퇴직소득 칸 추가 / 090: 고용보험 사업주분·고배당 분리과세·미국 배당 원천·주택·토지 양도세 추가, 양도세 정부안도 여기로(cgtPlan·cgtRule), ISA·연금 분리과세 / 092: 근로소득공제·근로소득세액공제·자녀세액공제(나이 연도별)·공익수용 감면(조특법 77) 추가, 토지 자경 5년 한도
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
  // 법인 수입배당금 익금불산입률 (법인세법 18조의2, 2023~) — 지분율 20% 미만 30, 20~50% 80, 50% 이상 100. 배당기준일 현재 3개월 이상 보유. ETF·리츠 분배금은 대상 아님 (087 확인)
  divExcl: [[20,30],[50,80],[Infinity,100]],
  // 고배당기업 배당소득 분리과세 (조특법 104조의27, 2026~2028 지급 배당 한시, 090 확인) — 국세 %, 지방세 별도.
  //   2천만 이하 14 / 3억 이하 20 / 50억 이하 25 / 초과 30. 일반 금융소득 2천만 기준과 별도 계산. 선택제(종합과세가 유리하면 안 고름)
  highDiv: [[2e7,14],[3e8,20],[5e9,25],[Infinity,30]],
  // ── 양도소득세 (090) ─────────────────────────────────────────────
  // 페이지는 숫자를 직접 쓰지 말고 SF_TAX.cgtRule('house' 또는 'land', 양도연도)로 그 해 규칙을 받아 쓴다.
  //   → 법이 바뀌면 아래 cgtHouse·cgtLand(현행) 또는 cgtPlan(예정)만 고치면 /tax/house/, /tax/land/, /realestate/home-swap/ 이 같이 바뀐다.
  //   → 2027.1.1이 되면 「지금 매도」가 자동으로 2027 규칙을 쓴다(오늘 연도로 고름).
  // 주택 현행 (2026.11, 소득세법 89·95·104조) — 1세대1주택 비과세 12억, 단기 1년 미만 70·1~2년 60(국세 %),
  //   조정대상지역 다주택 중과 2주택 +20·3주택+ +30%p (2026.5.9 유예 종료 → 5.10 양도분부터, 장특공제 배제), 기본공제 250만.
  //   ltcOne: 1세대1주택 장특공제 — 보유 3년 이상 + 거주 minLive년 이상일 때 보유 연 hold%(최대 holdMax) + 거주 연 live%(최대 liveMax), 합계 최대 max, 공제액 한도 cap
  //   ltcGen: 일반 장특공제 — mode 'hold' 보유 연 hold% / 'max' 보유·거주 중 큰 쪽 / 'live' 거주만. 보유 3년 이상부터, 최대 max
  //   basicLong: 장기거주 1주택 기본공제(0 = 없음), 조건 양도가액 longMaxPrice 이하·거주 longMinLive년 이상
  cgtHouse: {nontax: 12e8, short1: 70, short2: 60, heavy2: 20, heavy3: 30, basicDed: 2.5e6,
    basicLong: 0, longMaxPrice: 30e8, longMinLive: 10,
    ltcOne: {hold: 4, holdMax: 40, live: 4, liveMax: 40, max: 80, minLive: 2, cap: Infinity},
    ltcGen: {mode: 'hold', hold: 2, live: 0, max: 30, minLive: 0}},
  // 토지 현행 — 비사업용 가산 +10%p(장특공제 됨), 단기 1년 미만 50·1~2년 40, 8년 자경농지 세액감면 1년 1억·5년 2억(farmCap5, 조특법 69·133조, 092), 기본공제 250만
  cgtLand: {nonBiz: 10, nonBizLtc: true, short1: 50, short2: 40, farmCap: 1e8, farmCap5: 2e8, basicDed: 2.5e6, ltcRate: 2, ltcMax: 30},
  // 예정 변경 — 2026 세제개편 「정부안」(2026.8.3 발표, 2026.11 현재 국회 심의 중). 해당 연도 이후 양도분에 현행 위로 덮어씀(누적).
  //   국회에서 바뀌면 여기 숫자만 고칠 것. 확정되면 status를 '확정'으로 바꾸고, 시행된 해가 지나면 현행(cgtHouse·cgtLand)으로 옮겨도 됨.
  cgtPlan: {
    status: '정부안', note: '2026 세제개편 정부안 (2026.8.3 발표, 국회 심의 중)',
    2027: {house: {heavy2: 5, heavy3: 10, basicLong: 25e6}},
    2028: {house: {heavy2: 10, heavy3: 15,
             ltcOne: {hold: 2, holdMax: 40, live: 6, liveMax: 60, max: 80, minLive: 0, cap: 20e8},
             ltcGen: {mode: 'max', hold: 1, live: 2, max: 30, minLive: 0}},
           land: {nonBiz: 20, nonBizLtc: false}},
    2029: {house: {heavy2: 20, heavy3: 30,
             ltcOne: {hold: 0, holdMax: 0, live: 8, liveMax: 80, max: 80, minLive: 0, cap: 10e8},
             ltcGen: {mode: 'live', hold: 0, live: 2, max: 30, minLive: 2}}}
  },
  // cgtRule('house'|'land', 연도) → 그 해 양도분 규칙. 결과의 plan = 예정 변경이 섞였는지, planYears = 섞인 연도들
  cgtRule: function(kind, year){
    var T = window.SF_TAX, base = kind === 'land' ? T.cgtLand : T.cgtHouse, r = {}, k, used = [];
    for (k in base) r[k] = base[k];
    var ys = Object.keys(T.cgtPlan).filter(function(y){ return /^\d{4}$/.test(y); }).map(Number).sort();
    for (var i = 0; i < ys.length; i++){
      var o = T.cgtPlan[ys[i]][kind];
      if (ys[i] <= year && o){ for (k in o) r[k] = o[k]; used.push(ys[i]); }
    }
    r.plan = used.length > 0; r.planYears = used; r.year = year;
    return r;
  },
  // 절세계좌 분리과세 (090) — ISA 비과세 한도 넘는 이익 9.9%(지방세 포함), 연금 수령 연금소득세(지방세 포함) 70세 미만 5.5 / 80세 미만 4.4 / 80세 이상 3.3
  isaSep: 9.9, pensionTax: [5.5, 4.4, 3.3],
  // 미국 배당 원천징수 (한미 조세조약, 090) — 개인은 2천만 이하면 이걸로 끝, 법인은 외국납부세액공제
  usWithhold: 15,
  // 건강보험료율 (세금은 아니지만 매년 바뀌어 같이 둠) — 2026년 7.19%, 장기요양 = 건보료의 13.14%. 직장가입자 보수 외 소득 연 2천만 초과분에 소득월액보험료(전액 본인) (087 확인)
  health: {rate: 7.19, ltc: 13.14, otherIncomeFree: 20000000},
  // 4대보험 근로자 부담 (089 확인) — 국민연금 2026년 9.5%(근로자 4.75, 매년 1월 0.5%p씩 2033년 13%까지),
  //   기준소득월액 하한 41만·상한 659만 (2026.7~2027.6, 매년 7월 바뀜), 고용보험 근로자 0.9. 건보는 위 health(근로자 = rate/2)
  social: {nps: 4.75, npsMin: 410000, npsMax: 6590000, emp: 0.9},
  // 4대보험 사업주 부담 (090 확인) — 국민연금·건보·장기요양은 근로자와 같은 비율. 고용보험은 실업급여 0.9 + 고용안정·직업능력개발(사업주만):
  //   상시근로자 150인 미만 0.25 / 150인 이상 우선지원대상기업 0.45 / 150~1,000인 미만 0.65 / 1,000인 이상·국가·지자체 0.85. 산재는 업종별(페이지 입력)
  socialEmp: {emp: 0.9, stab: {u150: 0.25, prio: 0.45, u1000: 0.65, o1000: 0.85}},
  // 근로소득 간이세액표 8~20세 자녀 월 공제 (2026.3.1 지급분부터, 089 확인) — 1명 20,830 / 2명 45,830 / 3명 이상 2명 초과 1명당 33,330 추가
  childMonthly: {one: 20830, two: 45830, extra: 33330},
  // 근로소득공제 (소득세법 47조, 092 확인) — 총급여 구간별 누적 공제율 %, 공제 한도 2천만 → earnedDedAmt(총급여)
  earnedDed: {br: [[5e6,70],[15e6,40],[45e6,15],[1e8,5],[Infinity,2]], cap: 2e7},
  // 근로소득세액공제 (소득세법 59조, 092 국세청 확인) — 산출세액 130만 이하 55%, 초과분 30%. → earnedCrAmt(산출세액, 총급여)
  //   한도 lim: [총급여 상한, 시작액, (총급여 − 앞 구간 상한) × 비율 만큼 차감, 최소] — 3,300만↓ 74만 / 7천만↓ 74만−×0.008(최소 66만) / 1.2억↓ 66만−×1/2(최소 50만) / 초과 50만−×1/2(최소 20만)
  earnedCr: {base: 1.3e6, r1: 55, r2: 30, lim: [[3.3e7,74e4,0,74e4],[7e7,74e4,0.008,66e4],[1.2e8,66e4,0.5,50e4],[Infinity,50e4,0.5,20e4]]},
  // 자녀세액공제 (소득세법 59조의2, 092 확인) — 1명 25만 / 2명 55만 / 3명 이상 2명 초과 1명당 40만 (2025 귀속~). → childCrAmt(자녀 수)
  //   대상 나이(그 해 귀속 기준 이상, 20세 이하): 2026.4.21 개정 — 아동수당과 겹치지 않게 매년 1세씩 올라감 → childAge(연도)
  childCr: {one: 25e4, two: 55e4, extra: 4e5, minAge: {2025: 8, 2026: 9, 2027: 10, 2028: 11, 2029: 12, 2030: 13}},
  // 공익사업 수용·협의매수 토지 양도세 감면 (조특법 77조, 2025.1.1 양도분~, 092 확인) — 감면율 % 현금 15 / 일반채권 20 / 3년 만기특약 35 / 5년 만기특약 45.
  //   감면세액의 20% 농어촌특별세. until = 그 해 12.31 양도분까지(일몰, 연장되면 숫자만 고칠 것). 감면 종합한도(133조) 연 2억·5년 3억(다른 감면 합산)
  landExprop: {cash: 15, bond: 20, bond3: 35, bond5: 45, rural: 20, until: 2026, capYear: 2e8, cap5: 3e8},
  // 퇴직소득세 (소득세법 48·55조, 2023~ / 089 확인)
  //   근속연수공제: [근속 상한(년), 1년당 공제(원)] — ~5년 100만, ~10년 200만, ~20년 250만, 20년 초과 300만 (누적)
  retireYear: [[5,1e6],[10,2e6],[20,2.5e6],[Infinity,3e6]],
  //   환산급여공제: [환산급여 상한(원), 공제율%] 누적 → prog(환산급여, retireConv)
  retireConv: [[8e6,100],[7e7,60],[1e8,55],[3e8,45],[Infinity,35]],
  //   퇴직금을 연금계좌로 받아 연금으로 수령 시 퇴직소득세 부과율% — 실제 수령연차 10년 이하 70, 20년 이하 60, 20년 초과 50 (50은 2026.1.1 수령분부터)
  pensionRetire: [[10,70],[20,60],[Infinity,50]],
  wl: function(r){ return Math.round(r*1.1*100)/100; },
  // 누진 구간 세금(국세) — prog(과표, SF_TAX.corp) 처럼 쓴다. 지방세 포함은 결과 × (1 + local)
  // 근속연수공제 — 근속연수는 1년 미만 끝수를 1년으로 올려서 넣을 것 (페이지에서 Math.ceil)
  retYearDed: function(y){ var br=window.SF_TAX.retireYear, t=0, lo=0; for(var i=0;i<br.length;i++){ var hi=br[i][0]; if(y>lo){ t += (Math.min(y,hi)-lo)*br[i][1]; } lo=hi; } return t; },
  earnedDedAmt: function(g){ var T=window.SF_TAX; if(!(g>0)) return 0; return Math.min(T.prog(g, T.earnedDed.br), T.earnedDed.cap); },
  earnedCrAmt: function(tax, g){ var c=window.SF_TAX.earnedCr, lo=0, cap=0, cr; if(!(tax>0)) return 0;
    cr = tax <= c.base ? tax*c.r1/100 : c.base*c.r1/100 + (tax-c.base)*c.r2/100;
    for(var i=0;i<c.lim.length;i++){ var L=c.lim[i]; if(g <= L[0]){ cap = Math.max(L[3], L[1] - (g-lo)*L[2]); break; } lo=L[0]; }
    return Math.min(cr, cap); },
  childCrAmt: function(n){ var c=window.SF_TAX.childCr; n=parseInt(n,10)||0; if(n<=0) return 0; if(n===1) return c.one; return c.two + (n-2)*c.extra; },
  childAge: function(y){ var m=window.SF_TAX.childCr.minAge, ks=Object.keys(m).map(Number).sort(function(a,b){return a-b;}), r=m[ks[0]]; for(var i=0;i<ks.length;i++){ if(ks[i]<=y) r=m[ks[i]]; } return r; },
  prog: function(base, br){ var t=0, lo=0; if(!(base>0)) return 0; for(var i=0;i<br.length;i++){ var hi=br[i][0]; if(base>lo){ t += (Math.min(base,hi)-lo)*br[i][1]/100; } lo=hi; } return t; }
});
