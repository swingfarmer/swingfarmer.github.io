#!/usr/bin/env python3
"""(129 임시 probe — 확인 끝나면 지움) KIS 시장별 투자자 순매수가 어느 시장인지 확인.
HTS 11/24 코스피(억원): 개인 -24,315 / 외국인 +10,088 / 기관 +9,905 와 비교.
읽기 전용 조회만 함. 화면에만 출력(파일 저장 없음). 금액은 KIS 백만원 → 억원으로 바꿔 찍음."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_live_prices as F
from datetime import datetime

tok = F.get_token()
if not tok:
    print('토큰 없음 — 1분 뒤 다시'); sys.exit(1)
Q = '/uapi/domestic-stock/v1/quotations'
eok = lambda v: f"{F.to_int(v) / 100:,.0f}"

print('== ① inquire-investor-time-by-market (지금 쓰는 TR) — 조합별')
for a, b in [('999', 'S001'), ('KSP', '0001'), ('0001', '0001'), ('KSQ', '1001'), ('999', '0001')]:
    d = F.kis_get(f'{Q}/inquire-investor-time-by-market', 'FHPTJ04030000',
                  {'FID_INPUT_ISCD': a, 'FID_INPUT_ISCD_2': b}, tok)
    F.time.sleep(0.3)
    if str(d.get('rt_cd')) != '0':
        print(f'  {a}/{b}: 실패 {d.get("msg_cd","")} {d.get("msg1","")}'); continue
    r = d.get('output') or [{}]
    r = r[0] if isinstance(r, list) and r else r
    print(f'  {a}/{b}: 외국인 {eok(r.get("frgn_ntby_tr_pbmn"))} / 기관 {eok(r.get("orgn_ntby_tr_pbmn"))} / 개인 {eok(r.get("prsn_ntby_tr_pbmn"))}억')

print('== ② inquire-investor-daily-by-market (일별) — 코스피 오늘')
today = datetime.now(F.KST).strftime('%Y%m%d')
d = F.kis_get(f'{Q}/inquire-investor-daily-by-market', 'FHPTJ04040000',
              {'FID_COND_MRKT_DIV_CODE': 'U', 'FID_INPUT_ISCD': '0001', 'FID_INPUT_DATE_1': today,
               'FID_INPUT_ISCD_1': 'KSP', 'FID_INPUT_DATE_2': today, 'FID_INPUT_ISCD_2': '0001'}, tok)
if str(d.get('rt_cd')) != '0':
    print(f'  실패 {d.get("msg_cd","")} {d.get("msg1","")}')
else:
    rows = d.get('output') or d.get('output1') or []
    rows = rows if isinstance(rows, list) else [rows]
    for r in rows[:2]:
        print(f'  {r.get("stck_bsop_date","")}: 외국인 {eok(r.get("frgn_ntby_tr_pbmn"))} / 기관 {eok(r.get("orgn_ntby_tr_pbmn"))} / 개인 {eok(r.get("prsn_ntby_tr_pbmn"))}억')
