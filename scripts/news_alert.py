"""
뉴스 텔레그램 알림 — 품질 필터링 + 중요도 스코어링
=============================================
봇2 (TELEGRAM_BOT2_TOKEN) 로 DM 발송.

오라클 VM crontab:
  매시간 :05분 — 증권/해외증시 (봇2 DM, 24시간)
  12:00 KST   — 부동산/하남감북 (봇2 DM)
  07:35, 21:15 — 코인 (봇2 DM)

사용법:
  python3 news_alert.py                     # 전체 카테고리
  python3 news_alert.py --cats 증권 해외증시  # 지정 카테고리만
  python3 news_alert.py --cats 부동산 "하남 감북" --hours 24
  python3 news_alert.py --cats 코인 --hours 12

환경변수:
  NAVER_CLIENT_ID      — 네이버 클라우드 NAVER API HUB Client ID
  NAVER_CLIENT_SECRET  — 네이버 클라우드 NAVER API HUB Client Secret
  TELEGRAM_BOT2_TOKEN  — 텔레그램 봇2 토큰
  TELEGRAM_CHAT_ID     — 텔레그램 채팅 ID
"""
import requests
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
TOP_N = 10
MIN_SCORE = 2      # 이 점수 미만은 발송 제외

# 네이버 API HUB
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
NAVER_API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

# 텔레그램 — 봇2
from telegram_helper import send_dm_bot2 as _send_dm

# 아카이브 경로 — VM 로컬 (fetch_news.py와 동일)
NEWS_DATA_DIR = Path(os.path.expanduser("~/news_data"))
ARCHIVE_DIR = NEWS_DATA_DIR / "archive"

# ──────────────────────────────────────────────
# 카테고리별 검색어
# ──────────────────────────────────────────────
CATEGORIES = {
    "부동산": ["부동산", "아파트 분양", "재건축 재개발"],
    "증권": ["증권 주식", "코스피 코스닥", "공매도 기관 외국인"],
    "해외증시": ["미국 증시", "나스닥 S&P500", "뉴욕 증시 마감"],
    "하남 감북": ["하남 감북동 그린벨트", "하남 그린벨트 해제", "하남 감북 개발", "하남 감북지구", "하남 개발제한구역 해제"],
    "코인": ["비트코인 암호화폐", "이더리움 알트코인", "가상자산 거래소"],
}

# ──────────────────────────────────────────────
# 중요도 스코어링
# ──────────────────────────────────────────────
TIER1_SOURCES = {
    "연합뉴스", "한국경제", "매일경제", "서울경제",
    "이데일리", "파이낸셜뉴스", "머니투데이",
}
TIER2_SOURCES = {
    "조선일보", "중앙일보", "동아일보", "한겨레", "경향신문",
    "SBS", "KBS", "YTN", "MBC",
    "헤럴드경제", "아시아경제", "뉴시스", "뉴스1",
}

# 카테고리별 부스트 키워드 (해당 키워드 포함 시 +2)
BOOST_KEYWORDS = {
    "증권": ["실적", "공시", "상장", "IPO", "배당", "자사주", "유상증자",
             "공매도", "외국인", "기관", "M&A", "인수", "합병", "액면분할",
             "상한가", "하한가", "서킷브레이커", "사이드카"],
    "해외증시": ["연준", "Fed", "금리", "CPI", "고용", "GDP", "PCE",
               "나스닥", "S&P", "다우", "엔비디아", "테슬라", "애플",
               "BOJ", "ECB", "관세", "무역"],
    "부동산": ["재건축", "재개발", "분양", "청약", "공시지가", "전세",
             "규제", "대출", "DSR", "LTV", "토지거래허가"],
    "하남 감북": ["감북", "그린벨트", "해제", "하남", "개발제한"],
    "코인": ["비트코인", "이더리움", "SEC", "규제", "ETF", "스테이블코인",
            "CBDC", "거래소", "업비트", "빗썸", "코인베이스", "바이낸스",
            "반감기", "채굴", "디파이", "NFT"],
}

# 재탕·낚시 기사 감점 패턴
PENALIZE_PATTERNS = [
    "에 따르면", "것으로 알려", "것으로 전해", "것으로 나타나",
    "관련주 급등", "관련주 상승", "테마주",
    "전문가들은", "시장에서는", "업계에 따르면",
]

HEADERS = {
    "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
    "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
}


def clean_html(text):
    """HTML 태그·엔티티 제거"""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&apos;", "'")
    return text.strip()


def extract_source(url):
    """URL에서 언론사명 추출"""
    domain_map = {
        "hankyung.com": "한국경제",
        "mk.co.kr": "매일경제",
        "yna.co.kr": "연합뉴스",
        "fnnews.com": "파이낸셜뉴스",
        "chosun.com": "조선일보",
        "donga.com": "동아일보",
        "joongang.co.kr": "중앙일보",
        "hani.co.kr": "한겨레",
        "khan.co.kr": "경향신문",
        "sedaily.com": "서울경제",
        "edaily.co.kr": "이데일리",
        "mt.co.kr": "머니투데이",
        "newsis.com": "뉴시스",
        "news1.kr": "뉴스1",
        "ytn.co.kr": "YTN",
        "sbs.co.kr": "SBS",
        "kbs.co.kr": "KBS",
        "mbc.co.kr": "MBC",
        "asiae.co.kr": "아시아경제",
        "biz.heraldcorp.com": "헤럴드경제",
        "heraldcorp.com": "헤럴드경제",
        "nocutnews.co.kr": "노컷뉴스",
        "hankookilbo.com": "한국일보",
        "etnews.com": "전자신문",
        "zdnet.co.kr": "ZDNet",
        "bloter.net": "블로터",
        "ajunews.com": "아주경제",
        "dt.co.kr": "디지털타임스",
        "coindesk.com": "코인데스크",
        "blockmedia.co.kr": "블록미디어",
        "tokenpost.kr": "토큰포스트",
        "decenter.kr": "디센터",
    }
    for domain, name in domain_map.items():
        if domain in url:
            return name
    return ""


def search_news(query, display=15):
    """네이버 API HUB 뉴스 검색"""
    params = {
        "query": query,
        "display": display,
        "start": 1,
        "sort": "date",
    }
    try:
        r = requests.get(NAVER_API_URL, headers=HEADERS, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = []
        for it in data.get("items", []):
            title = clean_html(it.get("title", ""))
            link = it.get("link", "") or it.get("originallink", "")
            pub = it.get("pubDate", "")
            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": pub,
                    "source": extract_source(it.get("originallink", link)),
                })
        return items, None
    except Exception as e:
        return [], str(e)[:100]


# ──────────────────────────────────────────────
# 품질 필터링
# ──────────────────────────────────────────────

def normalize_title(title):
    """비교용 제목 정규화 — 괄호 접두사, 따옴표, 공백 제거"""
    title = re.sub(r'[\[\(【《]\s*[^\]\)】》]+[\]\)】》]\s*', '', title)
    title = re.sub(r'[""\'\'`「」『』]', '', title)
    title = re.sub(r'\s+', '', title)
    return title.lower()


def trigram_similarity(a, b):
    """트라이그램 유사도 (0~1). 0.5 이상이면 사실상 같은 기사."""
    a = normalize_title(a)
    b = normalize_title(b)
    if len(a) < 3 or len(b) < 3:
        return 0
    a_tri = set(a[i:i+3] for i in range(len(a) - 2))
    b_tri = set(b[i:i+3] for i in range(len(b) - 2))
    overlap = len(a_tri & b_tri)
    return overlap / min(len(a_tri), len(b_tri))


def score_item(item, category=""):
    """중요도 스코어링. 높을수록 좋은 기사."""
    score = 0
    title = item.get("title", "")
    source = item.get("source", "")

    # 1) 언론사 등급
    if source in TIER1_SOURCES:
        score += 3
    elif source in TIER2_SOURCES:
        score += 2
    elif source:
        score += 1

    # 2) 카테고리별 키워드 부스트 (최대 1회)
    keywords = BOOST_KEYWORDS.get(category, [])
    for kw in keywords:
        if kw in title:
            score += 2
            break

    # 3) 재탕·낚시 감점
    for pat in PENALIZE_PATTERNS:
        if pat in title:
            score -= 2
            break

    # 4) 최신성 보너스
    try:
        pub = parsedate_to_datetime(item["pubDate"])
        age_min = (datetime.now(KST) - pub).total_seconds() / 60
        if age_min < 30:
            score += 2
        elif age_min < 60:
            score += 1
    except Exception:
        pass

    # 5) 제목 길이 이상치 감점
    title_len = len(title)
    if title_len < 10:
        score -= 1   # 너무 짧으면 불완전
    elif title_len > 80:
        score -= 1   # 너무 길면 낚시성

    item["_score"] = score
    return score


def smart_dedupe(items, threshold=0.5):
    """트라이그램 유사도 기반 중복 제거. 스코어 높은 것 우선 보존."""
    items.sort(key=lambda x: x.get("_score", 0), reverse=True)
    kept = []
    for item in items:
        is_dup = False
        for existing in kept:
            if trigram_similarity(item["title"], existing["title"]) > threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(item)
    return kept


def filter_recent(items, hours=2):
    """pubDate 기준 N시간 이내 기사만 남김."""
    cutoff = datetime.now(KST) - timedelta(hours=hours)
    recent = []
    for it in items:
        try:
            pub = parsedate_to_datetime(it["pubDate"])
            if pub >= cutoff:
                recent.append(it)
        except Exception:
            pass
    return recent


def quality_filter(all_items, category, n=TOP_N):
    """품질 필터링 파이프라인: 스코어링 → 스마트 중복제거 → 컷오프"""
    # 스코어링
    for item in all_items:
        score_item(item, category)

    # 스마트 중복 제거
    unique = smart_dedupe(all_items)

    # 최소 점수 컷오프
    filtered = [it for it in unique if it.get("_score", 0) >= MIN_SCORE]

    # 스코어 내림차순 → 상위 N개
    filtered.sort(key=lambda x: (-x.get("_score", 0), x.get("pubDate", "")), reverse=False)
    filtered.sort(key=lambda x: x.get("_score", 0), reverse=True)

    return filtered[:n]


# ──────────────────────────────────────────────
# 텔레그램 발송
# ──────────────────────────────────────────────

def send_telegram(text, category=""):
    return _send_dm(text)


def format_telegram(category, items):
    now = datetime.now(KST)
    lines = [f"📰 <b>{category} 뉴스 Top {len(items)}</b>  ({now.strftime('%m/%d %H:%M')})"]
    lines.append("")
    for i, it in enumerate(items, 1):
        score = it.get("_score", 0)
        source = it.get("source", "")
        src_tag = f" [{source}]" if source else ""
        lines.append(f"{i}. {it['title']}{src_tag}")
        lines.append(it["link"])
        lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# CLI 파싱
# ──────────────────────────────────────────────

def parse_cats():
    """--cats 뒤의 카테고리명 파싱. 없으면 전체."""
    args = sys.argv[1:]
    if '--cats' not in args:
        return list(CATEGORIES.keys())
    idx = args.index('--cats')
    cats = []
    for a in args[idx+1:]:
        if a.startswith('--'):
            break
        cats.append(a)
    valid = [c for c in cats if c in CATEGORIES]
    if not valid:
        print(f"⚠️ 유효한 카테고리 없음: {cats}")
        print(f"   사용 가능: {list(CATEGORIES.keys())}")
        sys.exit(1)
    return valid


def parse_hours():
    """--hours N 으로 필터 시간 지정. 기본 2시간."""
    args = sys.argv[1:]
    if '--hours' in args:
        idx = args.index('--hours')
        if idx + 1 < len(args):
            try:
                return int(args[idx + 1])
            except ValueError:
                pass
    return 2


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    run_cats = parse_cats()
    filter_hours = parse_hours()
    print(f"뉴스 알림 시작: {now.strftime('%Y-%m-%d %H:%M')} — {run_cats} (최근 {filter_hours}시간)")

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("❌ NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 없음")
        return

    # 기존 아카이브 로드 (VM 로컬)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{today}.json"
    if archive_path.exists():
        try:
            with open(archive_path, "r", encoding="utf-8") as f:
                archive = json.load(f)
        except Exception:
            archive = {"date": today, "categories": {}}
    else:
        archive = {"date": today, "categories": {}}
    archive["updated"] = now.strftime("%Y-%m-%d %H:%M KST")

    total_searched = 0
    total_sent = 0

    for cat in run_cats:
        queries = CATEGORIES[cat]
        all_items = []
        errors = []

        for q in queries:
            items, err = search_news(q, display=15)
            if err:
                errors.append(f"{q}: {err}")
            else:
                all_items.extend(items)
            time.sleep(0.3)

        total_searched += len(all_items)

        # 시간 필터
        all_items = filter_recent(all_items, hours=filter_hours)

        # 품질 필터링 (스코어링 + 스마트 중복제거 + 컷오프)
        top = quality_filter(all_items, cat, TOP_N)

        # 아카이브에 저장 (스코어 필드 제거)
        archive_items = [{k: v for k, v in it.items() if not k.startswith("_")} for it in top]
        archive["categories"][cat] = {"items": archive_items, "count": len(archive_items)}

        if top:
            msg = format_telegram(cat, top)
            ok = send_telegram(msg, category=cat)
            total_sent += len(top)
            scores = [it.get("_score", 0) for it in top]
            print(f"  {cat}: {len(top)}개 → 봇2 DM {'✅' if ok else '❌'} (점수 {min(scores)}~{max(scores)})")
        else:
            print(f"  {cat}: 0개 ({filter_hours}시간 이내 품질 기사 없음)")
            if cat == "하남 감북":
                now_str = datetime.now(KST).strftime('%m/%d %H:%M')
                send_telegram(f"📰 <b>{cat} 뉴스</b>  ({now_str})\n\n오늘 관련 뉴스 없음", category=cat)

        time.sleep(1)

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=1)

    print(f"\n✅ 완료: {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"   검색 {total_searched}개 → 품질 통과 {total_sent}개")
    print(f"   아카이브: {archive_path}")


if __name__ == "__main__":
    main()
