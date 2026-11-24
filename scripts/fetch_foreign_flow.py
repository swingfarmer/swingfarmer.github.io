#!/usr/bin/env python3
"""
fetch_foreign_flow.py — 외국인/기관 현물 순매수 + 바실리 시그널
(129) 기준을 「코스피200 합산 수량(주)」 → 「코스피 금액(KRX 몫, NXT 빼고)」으로 바꿈 — HTS 「투자자별 매매동향 코스피 KRX」와 같은 숫자.
      수량은 같이 남겨 둠(화면에 둘 다 표시). 연속일수·MA·±2σ·시그널·시장 국면 점수는 금액 기준.
소스: 금액 = KIS 시장별 투자자 일별 FHPTJ04040000 (KSP/0001, 한 번에 300거래일) + 프로그램 일별 FHPPG04600001
      수량 = data/kr/screener/investor_hist.json (fetch_screener.py, 코스피200 408종목 합산) — 있는 날만
출력: data/dashboard/foreign_flow.json — 한 줄 칸:
      frgn_amt·inst_amt·prsn_amt·prog_amt (백만원) / frgn_qty·inst_qty·prog_qty (주, 없으면 null)
      ma5·ma20·sigma·upper_2s·lower_2s (백만원, 외국인 금액) / signal / consec_buy·consec_sell (외국인 금액)
      ※ KIS 외국인 금액은 HTS KRX보다 100억 안팎 작게 나올 때가 있음(기타외국인 포함 차이로 보임, 129 확인 — 기관·개인은 같음)

시그널 계산:
  - 5MA / 20MA (이동평균)
  - ±2σ 밴드 (20일 표준편차 기반)
  - 연속 매도/매수 일수
  - 매수/매도 시그널 (밴드 터치 기준)

fetch_screener.py 이후 실행 (crontab 20:50)
55 20 * * 1-5 cd ~/swingfarmer.github.io && python3 scripts/fetch_foreign_flow.py >> ~/cron.log 2>&1
"""

import json, datetime, pathlib, sys, math, os, time

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
HIST_FILE = REPO_DIR / "data" / "kr" / "screener" / "investor_hist.json"
DATA_DIR = REPO_DIR / "data" / "dashboard"
OUTPUT_FILE = DATA_DIR / "foreign_flow.json"

TODAY_DASH = datetime.date.today().strftime("%Y-%m-%d")


def load_investor_hist():
    if not HIST_FILE.exists():
        print(f"[ERROR] {HIST_FILE} 없음")
        sys.exit(1)
    with open(HIST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


KEEP_DAYS = 120   # 파일에 남기는 거래일 수 (MA20·σ는 300일 전체로 계산한 뒤 자름)


def fetch_amounts():
    """(129) KIS — {날짜: {frgn, inst, prsn, prog}} 백만원. 실패면 None."""
    sys.path.insert(0, str(SCRIPT_DIR))
    import fetch_live_prices as F
    tok = F.get_token()
    if not tok:
        print("[ERROR] KIS 토큰 없음"); return None
    Q = '/uapi/domestic-stock/v1/quotations'
    t8 = datetime.date.today().strftime('%Y%m%d')
    d = F.kis_get(f'{Q}/inquire-investor-daily-by-market', 'FHPTJ04040000',
                  {'FID_COND_MRKT_DIV_CODE': 'U', 'FID_INPUT_ISCD': '0001', 'FID_INPUT_DATE_1': t8,
                   'FID_INPUT_ISCD_1': 'KSP', 'FID_INPUT_DATE_2': t8, 'FID_INPUT_ISCD_2': '0001'}, tok)
    if str(d.get('rt_cd')) != '0':
        print(f"[ERROR] 투자자 일별 실패: {d.get('msg_cd','')} {d.get('msg1','')}"); return None
    out = {}
    for r in d.get('output') or []:
        ds = str(r.get('stck_bsop_date', ''))
        if len(ds) != 8:
            continue
        out[f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'] = {'frgn': F.to_int(r.get('frgn_ntby_tr_pbmn')),
                                               'inst': F.to_int(r.get('orgn_ntby_tr_pbmn')),
                                               'prsn': F.to_int(r.get('prsn_ntby_tr_pbmn')), 'prog': None}
    if len(out) < 40:
        print(f"[ERROR] 투자자 일별 {len(out)}일뿐 — 저장 안 함"); return None
    time.sleep(0.5)
    keep = sorted(out)[-KEEP_DAYS:]
    d = F.kis_get(f'{Q}/comp-program-trade-daily', 'FHPPG04600001',
                  {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_MRKT_CLS_CODE': 'K',
                   'FID_INPUT_DATE_1': keep[0].replace('-', ''), 'FID_INPUT_DATE_2': t8}, tok)
    if str(d.get('rt_cd')) == '0':
        n = 0
        for r in d.get('output') or []:
            ds = str(r.get('stck_bsop_date', ''))
            k = f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'
            if k in out:
                out[k]['prog'] = F.to_int(r.get('whol_smtn_ntby_tr_pbmn')); n += 1
        print(f"[INFO] 프로그램 일별 {n}일")
    else:
        print(f"[WARN] 프로그램 일별 실패(빈 칸으로): {d.get('msg_cd','')} {d.get('msg1','')}")
    return out


def aggregate(hist):
    """전종목 일별 합산 (수량, 주)"""
    date_totals = {}
    for code, daily in hist.items():
        for date_str, vals in daily.items():
            if date_str not in date_totals:
                date_totals[date_str] = {"foreign": 0, "institution": 0, "program": 0}
            date_totals[date_str]["foreign"] += vals.get("foreign", 0) or 0
            date_totals[date_str]["institution"] += vals.get("institution", 0) or 0
            date_totals[date_str]["program"] += vals.get("program", 0) or 0

    rows = []
    for date_str in sorted(date_totals.keys()):
        t = date_totals[date_str]
        rows.append({
            "date": date_str,
            "frgn_net_spot": t["foreign"],
            "inst_net_spot": t["institution"],
            "program_net": t["program"],
        })
    return rows


def calc_signals(rows):
    """MA, 볼린저밴드, 연속일수, 시그널 계산 — (129) 외국인 금액(frgn_amt) 기준"""
    for i, entry in enumerate(rows):
        frgn = entry["frgn_amt"] or 0

        # ── 5MA ──
        if i >= 4:
            vals = [rows[j]["frgn_amt"] or 0 for j in range(i - 4, i + 1)]
            entry["ma5"] = round(sum(vals) / len(vals))
        else:
            entry["ma5"] = None

        # ── 20MA ──
        if i >= 19:
            vals = [rows[j]["frgn_amt"] or 0 for j in range(i - 19, i + 1)]
            ma20 = sum(vals) / len(vals)
            entry["ma20"] = round(ma20)

            # ── 표준편차 + ±2σ 밴드 ──
            variance = sum((v - ma20) ** 2 for v in vals) / len(vals)
            sigma = math.sqrt(variance)
            entry["sigma"] = round(sigma)
            entry["upper_2s"] = round(ma20 + 2 * sigma)
            entry["lower_2s"] = round(ma20 - 2 * sigma)

            # ── 시그널 판별 ──
            if frgn <= entry["lower_2s"]:
                entry["signal"] = "buy"       # 극단 매도 → 역발상 매수
            elif frgn >= entry["upper_2s"]:
                entry["signal"] = "sell"      # 극단 매수 → 과열 경계
            else:
                entry["signal"] = None
        else:
            entry["ma20"] = None
            entry["sigma"] = None
            entry["upper_2s"] = None
            entry["lower_2s"] = None
            entry["signal"] = None

        # ── 연속 매도/매수 일수 ──
        if i == 0:
            if frgn > 0:
                entry["consec_buy"] = 1
                entry["consec_sell"] = 0
            elif frgn < 0:
                entry["consec_buy"] = 0
                entry["consec_sell"] = 1
            else:
                entry["consec_buy"] = 0
                entry["consec_sell"] = 0
        else:
            prev = rows[i - 1]
            if frgn > 0:
                entry["consec_buy"] = prev.get("consec_buy", 0) + 1
                entry["consec_sell"] = 0
            elif frgn < 0:
                entry["consec_buy"] = 0
                entry["consec_sell"] = prev.get("consec_sell", 0) + 1
            else:
                entry["consec_buy"] = 0
                entry["consec_sell"] = 0

    return rows


def save_data(rows):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    latest = rows[-1] if rows else {}
    output = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "금액: KIS 코스피 투자자별(KRX 몫, NXT 빼고) · 수량: investor_hist.json (코스피200 408종목 합산)",
        "unit": "_amt·ma·σ = 백만원 / _qty = 주",
        "latest": latest,
        "history": rows,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] 저장: {OUTPUT_FILE} ({len(rows)}일)")


def main():
    print(f"=== fetch_foreign_flow.py — {TODAY_DASH} ===")
    amt = fetch_amounts()
    if not amt:
        sys.exit(1)          # 기존 파일 그대로 둠 (헬스체크가 「오래됨」으로 알림)
    qty = {}
    if HIST_FILE.exists():
        hist = load_investor_hist()
        print(f"[INFO] 수량 종목수: {len(hist)}")
        qty = {q["date"]: q for q in aggregate(hist)}
    rows = []
    for d in sorted(amt):
        a, q = amt[d], qty.get(d) or {}
        rows.append({"date": d, "frgn_amt": a["frgn"], "inst_amt": a["inst"], "prsn_amt": a["prsn"], "prog_amt": a["prog"],
                     "frgn_qty": q.get("frgn_net_spot"), "inst_qty": q.get("inst_net_spot"), "prog_qty": q.get("program_net")})
    rows = calc_signals(rows)[-KEEP_DAYS:]
    print(f"[INFO] 일수: {len(rows)} (수량 있는 날 {sum(1 for r in rows if r['frgn_qty'] is not None)})")

    if rows:
        lat = rows[-1]
        print(f"[최신] {lat['date']} 외국인={lat['frgn_amt']/100:,.0f}억 기관={lat['inst_amt']/100:,.0f}억 (수량 외국인={lat['frgn_qty']})")
        print(f"       MA5={lat.get('ma5')} MA20={lat.get('ma20')} σ={lat.get('sigma')}")
        print(f"       밴드=[{lat.get('lower_2s')}, {lat.get('upper_2s')}]")
        print(f"       시그널={lat.get('signal')} 연속매도={lat.get('consec_sell')}일 연속매수={lat.get('consec_buy')}일")

    save_data(rows)


if __name__ == "__main__":
    main()
