"""
버핏지수 자동 계산 — ECOS(GDP) + 네이버 증권(시가총액)
=====================================================
ECOS API: 명목 GDP (분기별, 연환산)
네이버 증권 API: KOSPI+KOSDAQ 전체 시가총액 (종목별 합산)

출력:
  data/buffett.json          — 최신 값 (프론트 로드용)
  data/buffett_history.json  — 일별 누적 (차트용)

사용법:
  python3 scripts/fetch_buffett.py
  python3 scripts/fetch_buffett.py --test-ecos

크론: 평일 18:35 KST

환경변수:
  ECOS_API_KEY — 한국은행 ECOS Open API 키
"""
import os, sys, json
import urllib.request
import ssl
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
OUT_FILE = os.path.join(ROOT_DIR, "data", "buffett.json")
HIST_FILE = os.path.join(ROOT_DIR, "data", "buffett_history.json")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://m.stock.naver.com/',
}


# ── 환경변수 로드 ──
def load_env():
    f = os.path.expanduser('~/.env_secrets')
    if os.path.exists(f):
        for line in open(f):
            line = line.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('export '): line = line[7:]
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
load_env()

ECOS_API_KEY = os.environ.get('ECOS_API_KEY', '')


# ═══════════════════════════════════════════
# 1. ECOS — 명목 GDP (KeyStatisticList 방식)
# ═══════════════════════════════════════════
def get_gdp():
    """ECOS KeyStatisticList에서 최신 분기 GDP → 연환산 (조원)."""
    url = f"https://ecos.bok.or.kr/api/KeyStatisticList/{ECOS_API_KEY}/json/kr/1/100"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            raw = resp.read().decode('utf-8')
        data = json.loads(raw)
        rows = data.get('KeyStatisticList', {}).get('row', [])

        for row in rows:
            nm = row.get('KEYSTAT_NAME', '')
            if 'GDP' in nm and '명목' in nm:
                val_str = row.get('DATA_VALUE', '')
                unit = row.get('UNIT_NAME', '')
                period = row.get('CYCLE', '')
                try:
                    quarterly = float(val_str)
                except:
                    print(f"  ⚠ GDP 파싱 실패: {val_str}")
                    return None, None

                if '십억' in unit:
                    annual_tril = quarterly / 1000 * 4
                elif '조' in unit:
                    annual_tril = quarterly * 4
                else:
                    annual_tril = quarterly / 1000 * 4

                print(f"  GDP: 분기 {quarterly:,.1f}{unit} ({period}) → 연환산 {annual_tril:,.1f}조원")
                return round(annual_tril, 1), period

        print("  ❌ KeyStatisticList에서 GDP 항목 못 찾음")
        return None, None
    except Exception as e:
        print(f"  ⚠ ECOS 호출 실패: {e}")
        return None, None


# ═══════════════════════════════════════════
# 2. 네이버 증권 — KOSPI/KOSDAQ 전체 시가총액
# ═══════════════════════════════════════════
def fetch_naver_total_mktcap(market, page_size=3000):
    """네이버 증권 marketValue API로 시장 전체 종목 시총 합산."""
    url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page=1&pageSize={page_size}"
    try:
        req = urllib.request.Request(url, headers=NAVER_HEADERS)
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            raw = resp.read().decode('utf-8')
        data = json.loads(raw)
        stocks = data.get('stocks', [])
        total_count = data.get('totalCount', 0)

        total_won = 0
        valid = 0
        for s in stocks:
            mv = s.get('marketValueRaw')
            if mv:
                try:
                    total_won += int(mv)
                    valid += 1
                except:
                    pass

        total_조 = round(total_won / 1_000_000_000_000, 1)
        print(f"  {market}: {valid}/{total_count}종목 합산 = {total_조:,.1f}조원")

        if valid < total_count:
            print(f"  ⚠ {total_count - valid}종목 누락 (pageSize 부족 가능)")

        return total_조, valid
    except Exception as e:
        print(f"  ⚠ 네이버 {market} 호출 실패: {e}")
        return None, 0


def get_market_caps():
    """KOSPI + KOSDAQ 시가총액."""
    print("📊 시가총액 조회 (네이버 증권 API)...")

    kospi_조, kospi_cnt = fetch_naver_total_mktcap('KOSPI')
    kosdaq_조, kosdaq_cnt = fetch_naver_total_mktcap('KOSDAQ')

    if kospi_조 is None and kosdaq_조 is None:
        return None

    kospi_조 = kospi_조 or 0
    kosdaq_조 = kosdaq_조 or 0
    total_조 = round(kospi_조 + kosdaq_조, 1)

    print(f"  합계: {total_조:,.1f}조원")

    return {
        'kospi': kospi_조,
        'kosdaq': kosdaq_조,
        'total': total_조,
        'kospi_count': kospi_cnt,
        'kosdaq_count': kosdaq_cnt,
        'date': datetime.now(KST).strftime('%Y-%m-%d'),
        'source': '네이버 증권 (전 종목 합산)',
    }


# ═══════════════════════════════════════════
# 3. 역대 기록 (하드코딩)
# ═══════════════════════════════════════════
HISTORICAL = {
    "korea": {
        "all_time_high": {"value": 261, "date": "2026-05", "note": "코스피 7500선, 반도체 슈퍼사이클"},
        "all_time_low": {"value": 48, "date": "2008-10", "note": "글로벌 금융위기"},
        "covid_high": {"value": 135, "date": "2021-08", "note": "동학개미 강세장"},
        "avg_10yr": {"value": 95, "note": "2014~2024 평균"}
    },
    "us": {
        "all_time_high": {"value": 237, "date": "2026-05", "note": "AI 슈퍼사이클"},
        "all_time_low": {"value": 36, "date": "1982-04", "note": "볼커 긴축"},
        "dotcom_peak": {"value": 163, "date": "2000-03", "note": "닷컴 버블"},
        "gfc_low": {"value": 69, "date": "2009-03", "note": "글로벌 금융위기"},
        "avg_historical": {"value": 85, "note": "1970~2024 평균"}
    }
}


# ═══════════════════════════════════════════
# 4. 히스토리 누적
# ═══════════════════════════════════════════
def save_history(date_str, buffett_index, kospi, kosdaq, total, gdp):
    """일별 버핏지수 누적 저장."""
    history = []
    if os.path.exists(HIST_FILE):
        try:
            with open(HIST_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except:
            history = []

    # 같은 날짜 → 덮어쓰기
    history = [h for h in history if h.get('date') != date_str]
    history.append({
        'date': date_str,
        'buffett': buffett_index,
        'kospi': kospi,
        'kosdaq': kosdaq,
        'total': total,
        'gdp': gdp,
    })

    history.sort(key=lambda x: x['date'])

    with open(HIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    print(f"  📈 히스토리: {len(history)}일치 누적")


# ═══════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════
def main():
    now = datetime.now(KST)
    today = now.strftime('%Y-%m-%d')
    print(f"🐂 버핏지수 자동 계산: {now.strftime('%Y-%m-%d %H:%M KST')}")

    if '--test-ecos' in sys.argv:
        print("\nKeyStatisticList GDP 테스트:")
        gdp, period = get_gdp()
        if gdp:
            print(f"  ✅ 연환산 GDP: {gdp:,.1f}조원 ({period})")
        else:
            print("  ❌ 실패")
        return

    if not ECOS_API_KEY:
        print("❌ ECOS_API_KEY 없음")
        sys.exit(1)

    # 기존 데이터
    existing = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, 'r', encoding='utf-8') as f:
            existing = json.load(f)

    # 1. GDP
    print("\n📈 ECOS 명목 GDP 조회...")
    gdp, gdp_period = get_gdp()

    # 2. 시가총액
    mktcap = get_market_caps()

    # 3. 결과 조립
    result = {
        "updated": now.strftime("%Y-%m-%d %H:%M KST"),
        "gdp": {
            "value": gdp,
            "unit": "조원",
            "period": gdp_period,
            "source": "한국은행 ECOS"
        } if gdp else existing.get("gdp"),
        "mktcap": mktcap if mktcap else existing.get("mktcap"),
        "historical": HISTORICAL
    }

    # 4. 버핏지수 계산
    gdp_val = result.get("gdp", {}).get("value") if result.get("gdp") else None
    mktcap_data = result.get("mktcap", {})
    total_cap = mktcap_data.get("total") if mktcap_data else None
    kospi_cap = mktcap_data.get("kospi", 0) if mktcap_data else 0
    kosdaq_cap = mktcap_data.get("kosdaq", 0) if mktcap_data else 0

    if gdp_val and total_cap and gdp_val > 0:
        buffett = round(total_cap / gdp_val * 100, 1)
        result["buffett_index"] = buffett
        print(f"\n🐂 버핏지수: {buffett}% = {total_cap:,.1f}조 / {gdp_val:,.1f}조 × 100")
        print(f"   (KOSPI {kospi_cap:,.1f}조 + KOSDAQ {kosdaq_cap:,.1f}조)")

        # 히스토리 누적
        save_history(today, buffett, kospi_cap, kosdaq_cap, total_cap, gdp_val)
    else:
        result["buffett_index"] = existing.get("buffett_index")
        print("\n⚠ 버핏지수 계산 불가 (데이터 부족)")

    # 저장
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"✅ 저장: {OUT_FILE}")


if __name__ == '__main__':
    main()
