#!/usr/bin/env python3
"""(129 임시 probe — 확인 끝나면 지움) 외국인 수급 금액 기준 전환용: KIS 일별 조회가 며칠치를 주는지,
프로그램 매매 일별이 되는지 확인. 읽기 전용, 화면에만 출력. 금액은 억원으로."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_live_prices as F
from datetime import datetime, timedelta

tok = F.get_token()
if not tok:
    print('토큰 없음 — 1분 뒤 다시'); sys.exit(1)
Q = '/uapi/domestic-stock/v1/quotations'
eok = lambda v: f"{F.to_int(v) / 100:,.0f}"
today = datetime.now(F.KST)
t8 = today.strftime('%Y%m%d')
s8 = (today - timedelta(days=120)).strftime('%Y%m%d')

print('== ① 투자자 일별(FHPTJ04040000) — 날짜 둘 다 오늘')
for d1, d2 in [(t8, t8), (s8, t8)]:
    d = F.kis_get(f'{Q}/inquire-investor-daily-by-market', 'FHPTJ04040000',
                  {'FID_COND_MRKT_DIV_CODE': 'U', 'FID_INPUT_ISCD': '0001', 'FID_INPUT_DATE_1': d1,
                   'FID_INPUT_ISCD_1': 'KSP', 'FID_INPUT_DATE_2': d2, 'FID_INPUT_ISCD_2': '0001'}, tok)
    F.time.sleep(0.4)
    if str(d.get('rt_cd')) != '0':
        print(f'  {d1}~{d2}: 실패 {d.get("msg_cd","")} {d.get("msg1","")}'); continue
    rows = d.get('output') or []
    rows = rows if isinstance(rows, list) else [rows]
    ds = [r.get('stck_bsop_date') for r in rows]
    print(f'  {d1}~{d2}: {len(rows)}줄, {min(ds) if ds else "-"} ~ {max(ds) if ds else "-"}')
    if rows:
        print('   칸:', ','.join(k for k in rows[0] if 'ntby_tr_pbmn' in k))
        for r in rows[:3]:
            print(f'   {r.get("stck_bsop_date")}: 외국인 {eok(r.get("frgn_ntby_tr_pbmn"))} / 기관 {eok(r.get("orgn_ntby_tr_pbmn"))} / 개인 {eok(r.get("prsn_ntby_tr_pbmn"))}억')

print('== ② 프로그램 일별(FHPPG04600001)')
d = F.kis_get(f'{Q}/comp-program-trade-daily', 'FHPPG04600001',
              {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_MRKT_CLS_CODE': 'K', 'FID_INPUT_DATE_1': s8, 'FID_INPUT_DATE_2': t8}, tok)
if str(d.get('rt_cd')) != '0':
    print(f'  실패 {d.get("msg_cd","")} {d.get("msg1","")}')
else:
    rows = d.get('output') or []
    rows = rows if isinstance(rows, list) else [rows]
    ds = [r.get('stck_bsop_date') for r in rows]
    print(f'  {len(rows)}줄, {min(ds) if ds else "-"} ~ {max(ds) if ds else "-"}')
    if rows:
        print('   칸:', ','.join(k for k in rows[0] if 'ntby' in k))
        for r in rows[:3]:
            print(f'   {r.get("stck_bsop_date")}: 전체 순매수 금액 {eok(r.get("whol_smtn_ntby_tr_pbmn"))}억')
