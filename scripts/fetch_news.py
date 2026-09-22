"""
뉴스 수집 → data/news.json + data/news/아카이브
네이버 클라우드 API HUB 뉴스 검색 기반
GitHub Actions 1시간마다 자동 실행

환경변수:
  NAVER_CLIENT_ID      — 네이버 클라우드 API HUB Client ID
  NAVER_CLIENT_SECRET  — 네이버 클라우드 API HUB Client Secret
"""
import json
import os
import re
import glob
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
OUTPUT = "data/news.json"
ARCHIVE_DIR = os.path.join("data", "news")
TIMEOUT = 10
DISPLAY = 100        # 카테고리당 100개씩
ARCHIVE_KEEP = 90    # 90일 보관

# 네이버 API HUB
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
NAVER_API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

# 카테고리별 검색어 (여러 쿼리 → 합쳐서 중복 제거)
CATEGORIES = {
    "breaking": {
        "label": "속보",
        "queries": ["속보 뉴스"],
    },
    "economy": {
        "label": "경제",
        "queries": ["경제", "금리 물가 환율"],
    },
    "stock": {
        "label": "증권",
        "queries": ["증권 주식", "코스피 코스닥"],
    },
    "realestate": {
        "label": "부동산",
        "queries": ["부동산", "아파트 분양 재건축"],
    },
    "politics": {
        "label": "정치",
        "queries": ["정치 국회"],
    },
    "international": {
        "label": "국제",
        "queries": ["국제 해외", "미국 중국"],
    },
    "tech": {
        "label": "IT·테크",
        "queries": ["IT 기술 AI", "반도체"],
    },
    "industry": {
        "label": "산업",
        "queries": ["산업 제조 수출"],
    },
}

# 도메인 → 언론사명 매핑
DOMAIN_MAP = {
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
    "news.sbs.co.kr": "SBS",
    "news.kbs.co.kr": "KBS",
    "imnews.imbc.com": "MBC",
    "newsis.com": "뉴시스",
    "news1.kr": "뉴스1",
    "ytn.co.kr": "YTN",
    "biz.heraldcorp.com": "헤럴드경제",
    "asiae.co.kr": "아시아경제",
    "etnews.com": "전자신문",
    "zdnet.co.kr": "ZDNet",
    "bloter.net": "블로터",
    "ajunews.com": "아주경제",
    "dt.co.kr": "디지털타임스",
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
    for domain, name in DOMAIN_MAP.items():
        if domain in url:
            return name
    # 매핑 없으면 도메인 자체 반환
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        host = host.replace("www.", "").replace("news.", "").replace("m.", "")
        return host.split(".")[0] if host else "기타"
    except:
        return "기타"


def search_news(query, display=DISPLAY):
    """네이버 API HUB 뉴스 검색 (urllib — requests 미설치 환경 대응)"""
    params = urllib.parse.urlencode({
        "query": query,
        "display": display,
        "start": 1,
        "sort": "date",
    })
    url = f"{NAVER_API_URL}?{params}"
    req = urllib.request.Request(url, headers={
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = []
        for it in data.get("items", []):
            title = clean_html(it.get("title", ""))
            link = it.get("link", "") or it.get("originallink", "")
            pub = it.get("pubDate", "")
            if title and link:
                # pubDate를 ISO로 변환 시도
                iso = ""
                if pub:
                    try:
                        from email.utils import parsedate_to_datetime
                        iso = parsedate_to_datetime(pub).isoformat()
                    except:
                        iso = pub
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": iso,
                    "source": extract_source(link),
                })
        return items, None
    except Exception as e:
        return [], str(e)[:100]


def dedupe(items, max_items=100):
    """제목 기준 중복 제거 + 최신순 정렬"""
    seen = set()
    unique = []
    for it in items:
        key = it["title"].replace(" ", "").lower()[:40]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    unique.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
    return unique[:max_items]


def main():
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("❌ NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 필요")
        import sys
        sys.exit(1)

    now = datetime.now(KST)
    today_str = now.strftime("%Y-%m-%d")
    result = {"updated": now.strftime("%Y-%m-%d %H:%M KST"), "categories": {}}
    total_articles = 0
    total_calls = 0

    for cat_key, cat_info in CATEGORIES.items():
        label = cat_info["label"]
        queries = cat_info["queries"]
        all_items = []
        errors = []
        successes = []

        for q in queries:
            items, err = search_news(q)
            total_calls += 1
            if err:
                errors.append(f"{q}: {err}")
            else:
                all_items.extend(items)
                successes.append(q)
            time.sleep(0.1)  # rate limit 방지

        unique = dedupe(all_items)
        total_articles += len(unique)

        result["categories"][cat_key] = {
            "items": unique,
            "count": len(unique),
            "sources_ok": successes,
            "sources_fail": [e.split(":")[0] for e in errors],
        }

        status = f"  {label}({cat_key}): {len(unique)}개"
        if errors:
            status += f" — 실패: {', '.join(errors)}"
        print(status)

    # ── 최신 news.json 저장 ──
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    # ── 날짜별 아카이브 저장 (머지) ──
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    archive_file = os.path.join(ARCHIVE_DIR, f"{today_str}.json")

    existing = {}
    if os.path.exists(archive_file):
        try:
            with open(archive_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except:
            existing = {}

    merged = {"date": today_str, "updated": result["updated"], "categories": {}}
    for cat in result["categories"]:
        new_items = result["categories"][cat]["items"]
        old_items = existing.get("categories", {}).get(cat, {}).get("items", [])
        all_items = new_items + old_items
        seen = set()
        unique = []
        for it in all_items:
            key = it["title"].replace(" ", "").lower()[:40]
            if key not in seen:
                seen.add(key)
                unique.append(it)
        unique.sort(key=lambda x: x.get("pubDate", ""), reverse=True)
        merged["categories"][cat] = {
            "items": unique[:300],
            "count": min(len(unique), 300),
        }

    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)

    # ── 아카이브 인덱스 갱신 ──
    archive_files = glob.glob(os.path.join(ARCHIVE_DIR, "20??-??-??.json"))
    dates = sorted(
        [os.path.splitext(os.path.basename(f))[0] for f in archive_files],
        reverse=True
    )
    if len(dates) > ARCHIVE_KEEP:
        for old_d in dates[ARCHIVE_KEEP:]:
            old_f = os.path.join(ARCHIVE_DIR, f"{old_d}.json")
            if os.path.exists(old_f):
                os.remove(old_f)
        dates = dates[:ARCHIVE_KEEP]

    index = {"dates": dates, "latest": dates[0] if dates else None}
    with open(os.path.join(ARCHIVE_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    print(f"\n✅ 완료: {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"   API 호출: {total_calls}회, 기사: {total_articles}개")
    print(f"   아카이브: {archive_file} ({len(dates)}일치 보관)")


if __name__ == "__main__":
    main()
