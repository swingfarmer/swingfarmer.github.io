#!/usr/bin/env python3
"""
fetch_foreign_flow.py — 외국인 현선물 매매동향 수집
KIS Open API → data/dashboard/foreign_flow.json

수집 항목:
  - 현물: 외국인/기관 순매수 (KOSPI 시장 전체)
  - 선물: 외국인 선물 순매수 (계약수)
  - 콜옵션/풋옵션: 외국인 순매수 (금액)

사용 API:
  1) FHPTJ04400000 — 국내기관/외국인 매매종목가집계 (현물)
  2) FHKST03030100 — 기관/외국인 선물 매매추이 (선물)

crontab: 평일 20:50 (장마감+정산 후)
  50 20 * * 1-5 cd /home/opc/swingfarmer.github.io && . ~/.env_secrets && python3 scripts/fetch_foreign_flow.py >> logs/foreign_flow.log 2>&1

필요 환경변수: KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCESS_TOKEN (또는 자동갱신)
"""

import os, sys, json, requests, datetime, pathlib

# ── Config ──
BASE_URL = "https://openapi.koreainvestment.com:9443"
APP_KEY = os.environ.get("KIS_APP_KEY", "")
APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
ACCESS_TOKEN = os.environ.get("KIS_ACCESS_TOKEN", "")

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
DATA_DIR = REPO_DIR / "data" / "dashboard"
OUTPUT_FILE = DATA_DIR / "foreign_flow.json"

TODAY = datetime.date.today().strftime("%Y%m%d")
TODAY_DASH = datetime.date.today().strftime("%Y-%m-%d")

HEADERS_BASE = {
    "content-type": "application/json; charset=utf-8",
    "appkey": APP_KEY,
    "appsecret": APP_SECRET,
    "authorization": f"Bearer {ACCESS_TOKEN}",
}


def get_token_if_needed():
    """ACCESS_TOKEN 없으면 자동 발급"""
    global ACCESS_TOKEN, HEADERS_BASE
    if ACCESS_TOKEN:
        return
    print("[INFO] ACCESS_TOKEN 없음 — 자동 발급 시도")
    url = f"{BASE_URL}/oauth2/tokenP"
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET}
    r = requests.post(url, json=body, timeout=10)
    r.raise_for_status()
    ACCESS_TOKEN = r.json()["access_token"]
    HEADERS_BASE["authorization"] = f"Bearer {ACCESS_TOKEN}"
    print("[INFO] 토큰 발급 완료")


def fetch_spot_foreign():
    """
    FHPTJ04400000 — 국내기관·외국인 매매종목 가집계
    FID_ETC_CLS_CODE = "1" → 외국인
    시장 전체 순매수 합계 (상위 N종목 합산)
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/foreign-institution-total"
    headers = {**HEADERS_BASE, "tr_id": "FHPTJ04400000"}
    params = {
        "FID_COND_MRKT_DIV_CODE": "V",   # V: KOSPI
        "FID_COND_SCR_DIV_CODE": "16174",
        "FID_INPUT_ISCD": "0000",         # 전체
        "FID_DIV_CLS_CODE": "1",          # 순매수
        "FID_RANK_SORT_CLS_CODE": "0",
        "FID_ETC_CLS_CODE": "1",          # 1: 외국인
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("rt_cd") != "0":
            print(f"[WARN] 현물 외국인 API 실패: {data.get('msg1', 'unknown')}")
            return None

        # 상위 종목들의 순매수 합산
        items = data.get("output", [])
        total_net = 0
        for item in items:
            # 순매수거래대금 (단위: 원 → 억원)
            net = int(item.get("ntby_tr_pbmn", "0") or "0")
            total_net += net

        # 억원 단위로 변환
        total_net_eok = round(total_net / 100_000_000)
        print(f"[현물] 외국인 순매수 상위 합산: {total_net_eok:,}억원 ({len(items)}종목)")
        return total_net_eok

    except Exception as e:
        print(f"[ERROR] 현물 외국인: {e}")
        return None


def fetch_spot_institution():
    """기관 순매수도 수집"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/foreign-institution-total"
    headers = {**HEADERS_BASE, "tr_id": "FHPTJ04400000"}
    params = {
        "FID_COND_MRKT_DIV_CODE": "V",
        "FID_COND_SCR_DIV_CODE": "16174",
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "1",
        "FID_RANK_SORT_CLS_CODE": "0",
        "FID_ETC_CLS_CODE": "2",          # 2: 기관계
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("rt_cd") != "0":
            return None
        items = data.get("output", [])
        total_net = sum(int(item.get("ntby_tr_pbmn", "0") or "0") for item in items)
        total_net_eok = round(total_net / 100_000_000)
        print(f"[현물] 기관 순매수 상위 합산: {total_net_eok:,}억원")
        return total_net_eok
    except Exception as e:
        print(f"[ERROR] 현물 기관: {e}")
        return None


def fetch_futures_foreign():
    """
    외국인 선물 순매수 — 일자별 매매동향
    FHKST03010100 또는 투자자별 매매동향 활용

    NOTE: KIS API에서 선물 투자자별 동향 엔드포인트가
    제한적일 수 있음. 사용 가능한 대안:
    - FHKST03030100 (업종별 투자자매매동향)
    - 네이버/KRX에서 스크래핑
    """
    # 방법 1: KIS API 시도
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/investor-trend-estimate"
    headers = {**HEADERS_BASE, "tr_id": "FHPTJ04160200"}
    params = {
        "FID_COND_MRKT_DIV_CODE": "V",
        "FID_COND_SCR_DIV_CODE": "20174",
        "FID_INPUT_ISCD": "0000",
        "FID_INPUT_DATE_1": TODAY,
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        data = r.json()
        if data.get("rt_cd") == "0" and data.get("output"):
            out = data["output"]
            # 외국인 선물 순매수 필드 탐색
            frgn = out[0] if isinstance(out, list) else out
            fut_net = int(frgn.get("frgn_ntby_qty", "0") or "0")
            print(f"[선물] 외국인 순매수: {fut_net:,}계약")
            return fut_net
    except Exception as e:
        print(f"[WARN] KIS 선물 API 시도 실패: {e}")

    # 방법 2: 네이버증권 크롤링 (fallback)
    try:
        return fetch_futures_from_naver()
    except Exception as e:
        print(f"[ERROR] 네이버 fallback 실패: {e}")
        return None


def fetch_futures_from_naver():
    """네이버증권에서 외국인 선물 순매수 가져오기 (fallback)"""
    import re
    url = "https://finance.naver.com/sise/investorDealTrendDay.naver"
    params = {"bizdate": TODAY.replace("-", ""), "sosok": "04"}  # 04: KOSPI200선물
    headers_naver = {"User-Agent": "Mozilla/5.0"}

    r = requests.get(url, params=params, headers=headers_naver, timeout=10)
    # HTML 파싱은 복잡해지므로 일단 None 반환
    print("[INFO] 네이버 선물 크롤링 — 별도 구현 필요")
    return None


def load_history():
    """기존 히스토리 로드"""
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("history", [])
    return []


def save_data(history, today_entry):
    """히스토리에 오늘 데이터 추가 후 저장"""
    # 오늘 날짜 중복 방지
    history = [h for h in history if h.get("date") != TODAY_DASH]
    history.append(today_entry)

    # 최근 250일만 유지
    history = history[-250:]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "latest": today_entry,
        "history": history,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] 저장: {OUTPUT_FILE} ({len(history)}일)")


def main():
    if not APP_KEY or not APP_SECRET:
        print("[ERROR] KIS_APP_KEY / KIS_APP_SECRET 환경변수 없음")
        sys.exit(1)

    get_token_if_needed()

    spot_frgn = fetch_spot_foreign()
    spot_inst = fetch_spot_institution()
    fut_frgn = fetch_futures_foreign()

    today_entry = {
        "date": TODAY_DASH,
        "frgn_net_spot": spot_frgn,          # 억원
        "inst_net_spot": spot_inst,           # 억원
        "frgn_net_fut": fut_frgn,            # 계약
        "call_net": None,                     # TODO: 옵션 데이터
        "put_net": None,                      # TODO: 옵션 데이터
    }

    history = load_history()
    save_data(history, today_entry)


if __name__ == "__main__":
    main()
