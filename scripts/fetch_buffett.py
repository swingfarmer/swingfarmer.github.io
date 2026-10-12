"""
버핏지수 자동 계산 — ECOS(GDP) + prices.json(시가총액)
=====================================================
ECOS API: 명목 GDP (분기별)
prices.json: KOSPI+KOSDAQ 시가총액 (market 필드 기준 분리)

출력: data/buffett.json (프론트 로드용)

사용법:
  python3 fetch_buffett.py              # 최신 데이터 수집
  python3 fetch_buffett.py --test-ecos  # ECOS 통계표코드 탐색

크론:
  평일 18:50 KST (fetch_prices.py 이후)

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

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

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
# KeyStatisticList: 주요 경제지표 최신값 API
# "GDP(명목, 계절조정)" → 분기 GDP (십억원) → ×4 연환산

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
                period = row.get('CYCLE', '')  # e.g. "2026Q2"
                try:
                    quarterly = float(val_str)
                except:
                    print(f"  ⚠ GDP 파싱 실패: {val_str}")
                    return None, None

                # 십억원 → 조원, ×4 연환산 (계절조정이라 ×4 가능)
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
# 2. 시가총액 — prices.json (market 필드 기준 분리)
# ═══════════════════════════════════════════
# fetch_prices.py가 KOSPI+KOSDAQ 모두 수집, market 필드로 구분
# market_cap 단위: 억원

PRICES_FILE = os.path.join(ROOT_DIR, "data", "kr", "prices.json")

def get_market_caps():
    """prices.json에서 KOSPI/KOSDAQ 시가총액 각각 합산."""
    print("📊 시가총액 조회 (prices.json)...")
    if not os.path.exists(PRICES_FILE):
        print(f"  ❌ {PRICES_FILE} 없음")
        return None

    with open(PRICES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    prices = data.get('prices', {})
    updated = data.get('updated', '')

    kospi_억 = 0
    kosdaq_억 = 0
    kospi_cnt = 0
    kosdaq_cnt = 0

    for code, info in prices.items():
        cap = info.get('market_cap', 0)
        mkt = info.get('market', 'KOSPI')  # 하위 호환: market 없으면 KOSPI
        if cap and cap > 0:
            if mkt == 'KOSDAQ':
                kosdaq_억 += cap
                kosdaq_cnt += 1
            else:
                kospi_억 += cap
                kospi_cnt += 1

    kospi_조 = round(kospi_억 / 10000, 1)
    kosdaq_조 = round(kosdaq_억 / 10000, 1)
    total_조 = round((kospi_억 + kosdaq_억) / 10000, 1)

    print(f"  KOSPI: {kospi_cnt}종목 {kospi_조:,.1f}조원")
    print(f"  KOSDAQ: {kosdaq_cnt}종목 {kosdaq_조:,.1f}조원")
    print(f"  합계: {total_조:,.1f}조원 (기준일: {updated})")

    if kosdaq_cnt == 0:
        print(f"  ⚠ KOSDAQ 데이터 없음 — prices.json에 market 필드 없을 수 있음")
        note = 'KOSPI만 포함(KOSDAQ 미수집). 수동 보정 가능.'
    else:
        note = f'KOSPI {kospi_cnt}종목(시총 1조↑) + KOSDAQ {kosdaq_cnt}종목(시총 5천억↑). 소형주 일부 미포함.'

    return {
        'kospi': kospi_조,
        'kosdaq': kosdaq_조,
        'total': total_조,
        'kospi_count': kospi_cnt,
        'kosdaq_count': kosdaq_cnt,
        'date': updated,
        'source': 'prices.json (KIS Open API)',
        'note': note,
    }


# ═══════════════════════════════════════════
# 3. 역대 기록 (하드코딩 — 리서치 기반)
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
# 메인
# ═══════════════════════════════════════════
def main():
    now = datetime.now(KST)
    print(f"🐂 버핏지수 자동 계산: {now.strftime('%Y-%m-%d %H:%M KST')}")

    if '--test-ecos' in sys.argv:
        # KeyStatisticList GDP 테스트
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

    # 기존 데이터 로드 (실패 시 새로 생성)
    existing = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, 'r', encoding='utf-8') as f:
            existing = json.load(f)

    # 1. GDP
    print("\n📈 ECOS 명목 GDP 조회...")
    gdp, gdp_period = get_gdp()

    # 2. 시가총액
    mktcap = get_market_caps()

    # 3. 버핏지수 계산
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

    # 버핏지수 계산
    gdp_val = result.get("gdp", {}).get("value") if result.get("gdp") else None
    total_cap = result.get("mktcap", {}).get("total") if result.get("mktcap") else None

    if gdp_val and total_cap and gdp_val > 0:
        buffett = round(total_cap / gdp_val * 100, 1)
        result["buffett_index"] = buffett
        print(f"\n🐂 버핏지수: {buffett}% = {total_cap:.1f}조 / {gdp_val:.1f}조 × 100")
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
