"""
DART 계정 이름 조회 (104) — 읽기 전용, 화면에만 출력 (파일 저장 안 함)
fetch_dart.py가 D&A·차입금·지배주주 순이익·주당배당을 못 찾는 종목의 실제 계정 이름을 보려고 만듦.

사용법:
  . ~/.env_secrets
  python3 scripts/dart_probe.py 005930 000660 --year 2025

출력: 종목마다 연결(없으면 별도) 전체 재무제표에서 키워드가 든 줄 + 배당 공시(alotMatter) 줄
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_dart as F

KEYS = ['상각', '차입', '사채', '리스부채', '지배', '당기순이익', '순손익']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('codes', nargs='+')
    ap.add_argument('--year', default='2025')
    ap.add_argument('--reprt', default='11011', help='11011 연간 / 11014 3분기')
    a = ap.parse_args()
    if not F.DART_API_KEY:
        print('❌ DART_API_KEY 없음 — . ~/.env_secrets 먼저'); sys.exit(1)
    cmap = F.download_corp_codes()
    for code in a.codes:
        cc = cmap.get(code)
        print(f'\n━━ {code} (corp {cc}) ━━')
        if not cc: print('  매핑 없음'); continue
        full = F.fetch_full_accounts(cc, a.year, a.reprt)
        fs = full[0].get('_fs') if full else '-'
        print(f'  전체 재무제표: {len(full)}줄, {fs}')
        for it in full:
            nm = it.get('account_nm', '')
            if any(k in nm for k in KEYS):
                amt = F.parse_amount(it.get('thstrm_amount'))
                print(f"  {it.get('sj_div',''):3} | {it.get('account_id','')[:55]:55} | {nm[:40]} | {amt}억")
        d = F.api_call('alotMatter', {'corp_code': cc, 'bsns_year': a.year, 'reprt_code': a.reprt})
        print(f"  배당 공시: status {d.get('status') if d else None}")
        for it in (d or {}).get('list', []):
            print(f"    {it.get('se','')[:28]:28} | {it.get('stock_knd','')!r:10} | {it.get('thstrm','')}")


if __name__ == '__main__':
    main()
