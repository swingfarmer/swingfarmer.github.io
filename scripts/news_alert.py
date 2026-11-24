"""
뉴스 텔레그램 알림 — 품질 필터링 + 중요도 스코어링
=============================================
봇2 (TELEGRAM_BOT2_TOKEN) 로 DM 발송.

오라클 VM crontab:
  매시간 :05분 — 증권/해외증시/경제 (봇2 DM, 24시간)
  07:30, 19:30 — 정치 (봇2 DM)
  12:00 KST   — 부동산/하남감북 (봇2 DM)
  :20·:50     — 주요기업(엔비디아·테슬라·스페이스X·앤트로픽·구글 AI) (봇2 DM, 128)
  07:35, 21:15 — 코인 (봇2 DM)

사용법:
  python3 news_alert.py                     # 전체 카테고리
  python3 news_alert.py --cats 증권 해외증시  # 지정 카테고리만
  python3 news_alert.py --cats 부동산 "하남 감북" --hours 24
  python3 news_alert.py --cats 코인 --hours 12
  python3 news_alert.py --cats 증권 --dry    # 보내지 않고 무엇을 왜 뺐는지만 출력 (보낸 기록도 안 바꿈)

(113) 중복 제거 — 매시간 「최근 2시간」을 모으니 같은 기사가 두 번씩 갔음. 아래를 겹쳐서 뺌:
  ① 보낸 기록 ~/news_data/news_sent.json — 주소·제목이 같으면 48시간, 같은 사건이면 12시간 안에 다시 안 보냄
  ② 같은 회차 다른 분야(증권→해외증시→경제 순서)에 이미 넣은 기사는 뺌
  ③ 같은 사건 판정: 제목 글자 조각(트라이그램) 유사도 + 핵심 단어 겹침(언론사마다 제목을 바꿔 쓴 기사)
     + 핵심 숫자(1조달러·9조) 같음. 방향(상승↔하락)·단계(장중↔마감)가 다르면 다른 소식
  ⑤ 같은 주제(같은 고유명사)는 메시지당 2개, 회차 전체 3개까지
  ④ 주소 정리(http·www·utm 꼬리 뺌) + 네이버 주소·원문 주소 둘 다 비교
  기록은 텔레그램 보내기에 성공한 것만 남김(실패하면 다음 회차에 다시 시도)

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
SENT_PATH = NEWS_DATA_DIR / "news_sent.json"   # (113) 보낸 기록
SENT_KEEP_H = 48      # 주소·같은 제목: 이 시간 안에 보낸 건 다시 안 보냄
STORY_KEEP_H = 12     # 같은 사건(제목만 다름): 이 시간 안에 보낸 건 다시 안 보냄 — 길면 다음 날 새 소식까지 막힘

# ──────────────────────────────────────────────
# 카테고리별 검색어
# ──────────────────────────────────────────────
CATEGORIES = {
    "부동산": ["부동산", "아파트 분양", "재건축 재개발"],
    "증권": ["증권 주식", "코스피 코스닥", "공매도 기관 외국인"],
    "해외증시": ["미국 증시", "나스닥 S&P500", "뉴욕 증시 마감"],
    "하남 감북": ["하남 감북동 그린벨트", "하남 그린벨트 해제", "하남 감북 개발", "하남 감북지구", "하남 개발제한구역 해제"],
    "코인": ["비트코인 암호화폐", "이더리움 알트코인", "가상자산 거래소"],
    "경제": ["경제 금리", "물가 환율", "수출 무역수지"],
    "정치": ["정치 국회", "대통령 총리", "정당 여야"],
    # (128) 주요 기업 — 30분마다(:20·:50). 표기가 갈리는 이름은 둘 다 검색(스페이스X/스페이스엑스, 앤트로픽/앤스로픽).
    #       구글은 기사량이 너무 많아 AI 쪽(제미나이·TPU)만. 「클로드」만으로는 안 찾음(앤트로픽 기사에 거의 같이 나옴)
    "주요기업": ["엔비디아", "테슬라", "스페이스X", "스페이스엑스", "앤트로픽", "앤스로픽", "구글 제미나이", "구글 TPU"],
}

# (128) 카테고리별 검색 개수(기본 15) / 제목에 꼭 들어가야 하는 이름(본문에만 스친 기사 빼기)
CAT_DISPLAY = {"주요기업": 30}
CAT_TITLE_MUST = {
    "주요기업": ["엔비디아", "NVIDIA", "젠슨", "테슬라", "머스크", "스페이스X", "스페이스엑스", "SpaceX", "스타십",
               "앤트로픽", "앤스로픽", "Anthropic", "클로드", "구글", "알파벳", "제미나이", "TPU"],
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
    "경제": ["금리", "기준금리", "한국은행", "CPI", "물가", "환율", "달러",
            "수출", "무역수지", "GDP", "경기", "경상수지", "고용",
            "실업률", "소비자심리", "PMI", "국채"],
    "주요기업": ["실적", "매출", "가이던스", "CEO", "상장", "IPO", "인수", "합병", "투자", "계약", "수주",
             "소송", "규제", "리콜", "출시", "공개", "발사", "증자", "지분", "공급", "칩", "모델"],
    "정치": ["국회", "대통령", "총리", "법안", "탄핵", "인사청문",
            "예산", "정당", "선거", "여야", "국정감사", "개각",
            "외교", "정상회담", "한미", "한중"],
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
                    "orig": it.get("originallink", "") or "",
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
    """비교용 제목 정규화 — 괄호 묶음([속보]·(종합2보) 등), 따옴표·문장부호, 공백 제거"""
    title = re.sub(r'[\[\(【《<〈]\s*[^\]\)】》>〉]+[\]\)】》>〉]\s*', '', title)
    title = re.sub(r'(속보|단독|종합|\d+보)\s*[:：]?', '', title)
    title = re.sub(r'[^0-9A-Za-z가-힣]', '', title)   # (113) …·ㅡ·쉼표·% 같은 부호까지 뺌
    return title.lower()


# (113) 같은 사건 판정용 핵심 단어 — 줄임말 통일, 끝 조사 뗌, 두 자리 이상 숫자(2.50·5000)도 단어로 봄
_JOSA = ("에서", "으로", "에게", "까지", "부터", "보다", "은", "는", "이", "가", "을", "를",
         "에", "의", "도", "로", "와", "과", "만")
_STOP = {"속보", "단독", "종합", "오늘", "이번", "관련", "기자", "뉴스", "올해", "지난", "대한"}


_ALIAS = {"한은": "한국은행", "美": "미국 ", "中": "중국 ", "日": "일본 ", "韓": "한국 ", "北": "북한 ",
          "與": "여당 ", "野": "야당 ", "靑": "청와대 ", "銀": "은행 ", "株": "주식 ", "↑": " 상승 ", "↓": " 하락 ", "IPO": " 상장 ", "ipo": " 상장 "}
# 방향·단계가 다르면 제목 단어가 많이 겹쳐도 다른 소식 (「코스피 상승 출발」 vs 「코스피 하락 출발」, 「~출발」 vs 「~마감」)
_SIDES = [
    ({"상승", "급등", "강세", "반등", "오름", "올라", "랠리", "최고"}, {"하락", "급락", "약세", "내림", "내려", "떨어", "추락", "최저"}),
    ({"순매수", "매수"}, {"순매도", "매도"}),
    ({"출발", "개장", "장중", "장초반", "오전"}, {"마감", "장마감", "종가"}),
    ({"인상", "올려", "올린"}, {"인하", "내려", "내린"}),
    ({"회복", "탈환", "넘어", "넘었", "넘겨"}, {"붕괴", "밑돌", "이탈", "무너", "털렸", "깨졌"}),
]
# 주제 세기에서 빼는 흔한 말 (어디에나 나와서 주제가 아님)
_GENERIC = {"코스피", "코스닥", "증시", "주식", "시장", "투자", "투자자", "외국인", "개인", "기관", "미국", "한국",
            "중국", "일본", "글로벌", "세계", "국내", "해외", "상승", "하락", "급등", "급락", "마감", "출발", "전망",
            "기대", "우려", "달러", "금리", "환율", "경제", "정부", "기업", "종목", "주가", "증권", "올해", "역대",
            "최대", "사상", "돌파", "발표", "결정", "추진", "확대", "만에", "이유", "시대", "오늘", "내일", "nbsp",
            # 검색어·분야 단어 — 그 분야 기사 대부분에 들어가서 주제가 아님 (회사·인물 이름은 넣지 않음 → 주제로 셈)
            "수출", "수입", "무역", "무역수지", "물가", "소비", "고용", "경기", "성장", "실적", "공시", "상장", "첫날",
            "나스닥", "다우", "뉴욕", "뉴욕증시", "월가", "etf", "지수", "선물", "매수", "매도", "순매수", "순매도",
            "개미", "주주", "배당", "자사주", "기준금리", "인상", "인하", "동결", "국채", "채권", "유가", "원유",
            "반도체", "부동산", "아파트", "가상자산", "코인", "국회", "대통령", "정당", "여야", "자금", "가치",
            # 자주 나오는 기관·인물 — 주제가 아니라 주어(「한은 금리 전망」과 「한은 생활비 보고서」는 다른 소식)
            "한국은행", "연준", "fed", "금통위", "파월", "일본은행", "boj", "ecb", "트럼프", "정부", "기재부",
            "금융위", "금감원", "국세청", "총재", "장관"}
TOPIC_MAX_MSG = 2     # (113) 한 메시지에 같은 주제(같은 고유명사·핵심 숫자) 기사는 2개까지
TOPIC_MAX_RUN = 3     #        한 회차(증권+해외증시+경제) 전체로는 3개까지


def _fold(title):
    t = re.sub(r'[\[\(【《<〈]\s*[^\]\)】》>〉]+[\]\)】》>〉]', ' ', title)
    for k, v in _ALIAS.items():
        t = t.replace(k, v)
    return t


_UNIT = "조억만천"
_NUM_RE = re.compile(r'\d+(?:\.\d+)?(?:\s*[조억만천](?:\d+(?:\.\d+)?)?)*(?:\s*(?:달러|원|%|배|bp|p))?')   # 16만5000원·9조3000억원을 한 덩어리로


_UVAL = {"조": 1e12, "억": 1e8, "만": 1e4, "천": 1e3}


def _num_value(raw):
    """「16만5000원」·「16.5만원」→ 같은 값(유효숫자 2자리) + 통화. 「9조3000억원」≈「9조2825억원」.
    조·억·만이 있고 통화가 없으면 원으로 봄(「9조 넘었다」)"""
    cur = ""
    for u in ("달러", "원", "%", "배", "bp", "p"):
        if raw.endswith(u):
            cur, raw = u, raw[:-len(u)]
            break
    parts = re.findall(r'(\d+(?:\.\d+)?)([조억만천]?)', raw)
    if not parts:
        return raw + cur
    if any(u for _, u in parts) and not cur:
        cur = "원"
    val = sum(float(n) * _UVAL.get(u, 1) for n, u in parts)
    if not any(u for _, u in parts) and cur in ("", "%", "p", "bp"):
        return f"{float(parts[0][0]):g}{cur}"          # 단위 없는 숫자·퍼센트는 그대로(5000·2.50%)
    return f"{float('%.2g' % val):g}{cur}"


def _num_close(a, b):
    """강한 숫자 두 개가 같은 통화이고 값 차이 10% 이내면 같은 숫자(84조원≈85조원, 9조≈9조3000억)"""
    ma, mb = re.match(r'([\d.e+]+)(.*)', a), re.match(r'([\d.e+]+)(.*)', b)
    if not ma or not mb or ma.group(2) != mb.group(2):
        return a == b
    try:
        x, y = float(ma.group(1)), float(mb.group(1))
    except ValueError:
        return a == b
    return max(x, y) > 0 and abs(x - y) / max(x, y) <= 0.10


def num_tokens(title):
    """숫자+단위 덩어리: 「1조 달러」→1조달러, 「5,000선」→5000, 「16만5000원」→16만5000원.
    (핵심 숫자, 강한 숫자) — 강한 숫자 = 금액 단위(조억만천·달러·원)가 붙었거나 세 자리 이상(연도 19xx·20xx 제외)"""
    t = re.sub(r'(?<=\d),(?=\d{3})', '', title)
    t = re.sub(r'(?<=[\d조억만천])\s+(?=[\d]|달러|원)', '', t)
    toks, strong = set(), set()
    for m in _NUM_RE.finditer(t):
        raw = re.sub(r'\s+', '', m.group(0)).lower()
        k = _num_value(raw)
        digits = re.sub(r'\D', '', raw)
        unit = any(c in raw for c in _UNIT) or any(u in raw for u in ("달러", "원", "%", "배"))
        if len(digits) >= 2 or unit:
            toks.add(k)
            money = any(c in raw for c in _UNIT) or any(u in raw for u in ("달러", "원"))   # %·배는 흔해서 강한 숫자 아님(「20%」끼리 엉뚱하게 묶였음)
            if money or (len(digits) >= 3 and not re.fullmatch(r'(19|20)\d\d', raw)):
                strong.add(k)
    return toks, strong


def _match_count(ta, tb):
    """작은 쪽 단어 중 다른 쪽에 같은 단어가 있거나, 두 글자 이상이 서로 들어 있는(미래↔미래에셋운용) 것의 수"""
    if len(ta) > len(tb):
        ta, tb = tb, ta
    n = 0.0
    for a in ta:
        if a in tb or any(a == x + y for x in tb for y in tb if x != y):   # 「연중최저」=「연중」+「최저」(띄어쓰기만 다름)
            n += 1
        elif any(len(a) >= 2 and len(b) >= 2 and (a in b or b in a) and not a[0].isdigit() and not b[0].isdigit()
                 for b in tb):
            n += 0.6     # 「상장」↔「상장인데」처럼 어미만 붙은 것까지 1로 세면 다른 기사가 묶임(113 앤트로픽)
    return n


def _side(words, side_set):
    return any(any(x in w for x in side_set) for w in words)


def story_tokens(title):
    t = _fold(title)
    out = set(num_tokens(t)[0])
    t = _NUM_RE.sub(' ', re.sub(r'(?<=\d),(?=\d{3})', '', t))
    for w in re.findall(r'[가-힣A-Za-z]{2,}', t):
        w = w.lower()
        for j in _JOSA:
            if len(w) > len(j) + 1 and w.endswith(j):
                w = w[:-len(j)]
                break
        if len(w) >= 2 and w not in _STOP:
            out.add(w)
    return out


def same_story(a, b):
    """같은 기사·같은 사건이면 True. a, b = 제목 문자열"""
    # 방향·단계 검사를 먼저 (글자가 거의 같아도 「급등」↔「급락」은 다른 소식)
    wa, wb = re.findall(r'[가-힣]+', _fold(a)), re.findall(r'[가-힣]+', _fold(b))
    for s1, s2 in _SIDES:       # 한쪽은 상승만, 다른 쪽은 하락만 → 다른 소식
        a1, a2, b1, b2 = _side(wa, s1), _side(wa, s2), _side(wb, s1), _side(wb, s2)
        if (a1 and not a2 and b2 and not b1) or (a2 and not a1 and b1 and not b2):
            return False
    if _side(wa, _SIDES[2][1]) != _side(wb, _SIDES[2][1]):   # 「마감」은 한쪽에만 있어도 새 소식(장중 기사 → 마감 기사)
        return False
    if trigram_similarity(a, b) > 0.5:
        return True
    ta, tb = story_tokens(a), story_tokens(b)
    if not ta or not tb:
        return False
    shared = _match_count(ta, tb)
    if shared >= 3 and shared / min(len(ta), len(tb)) >= 0.6:
        return True
    # 핵심 숫자(1조달러·9조·16만5000원)가 같고 다른 단어도 2개 이상 겹치면 같은 사건
    sa, sb = num_tokens(_fold(a))[1], num_tokens(_fold(b))[1]
    return any(_num_close(x, y) for x in sa for y in sb) and shared >= 3


def topic_words(title):
    """주제 세기용 — 흔한 말 뺀 단어 + 핵심 숫자(1조달러 등)"""
    ws = {w for w in story_tokens(title) if w not in _GENERIC and not re.match(r'\d', w) and len(w) >= 2}
    return ws | num_tokens(_fold(title))[1]


def topic_cap(items, run_kept, dropped=None):
    """같은 주제(같은 고유명사·핵심 숫자)가 메시지에 TOPIC_MAX_MSG개, 회차 전체에 TOPIC_MAX_RUN개를 넘으면 뺌
    (점수 높은 순으로 남기고 빈자리는 아래 순위 기사로 채움). 흔한 말은 _GENERIC에서 빼고 셈"""
    run_cnt = {}
    for k in run_kept:
        for w in topic_words(k["title"]):
            run_cnt[w] = run_cnt.get(w, 0) + 1
    msg_cnt, out = {}, []
    for it in items:
        ws = topic_words(it["title"])
        over = [w for w in ws if msg_cnt.get(w, 0) >= TOPIC_MAX_MSG or run_cnt.get(w, 0) >= TOPIC_MAX_RUN]
        if over:
            if dropped is not None:
                dropped.append(("같은주제", it["title"], over[0]))
            continue
        for w in ws:
            msg_cnt[w] = msg_cnt.get(w, 0) + 1
            run_cnt[w] = run_cnt.get(w, 0) + 1
        out.append(it)
    return out


def norm_url(u):
    """주소 비교용 — http/https·www·끝 / ·#·utm 꼬리 뺌 (기사 번호가 든 ?id= 는 남김)"""
    if not u:
        return ""
    u = u.strip().lower()
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'^(www\.|m\.)', '', u)
    u = u.split('#')[0]
    if '?' in u:
        base, q = u.split('?', 1)
        q = '&'.join(p for p in q.split('&') if p and not p.startswith('utm_'))
        u = base + ('?' + q if q else '')
    return u.rstrip('/')


def item_urls(it):
    return {x for x in (norm_url(it.get("link")), norm_url(it.get("orig"))) if x}


def load_sent():
    """보낸 기록 — [{t: epoch초, title, key, urls}]. 48시간 지난 건 버림"""
    try:
        with open(SENT_PATH, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        rows = []
    cut = time.time() - SENT_KEEP_H * 3600
    return [r for r in rows if r.get("t", 0) >= cut]


def save_sent(rows):
    tmp = str(SENT_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    os.replace(tmp, SENT_PATH)


def drop_reason(item, sent, run_kept):
    """빼야 하면 (이유, 겹친 제목), 아니면 None"""
    urls, key, title = item_urls(item), normalize_title(item["title"]), item["title"]
    story_cut = time.time() - STORY_KEEP_H * 3600
    for r in sent:
        if urls & set(r.get("urls", [])) or (key and key == r.get("key")):
            return ("보낸기록", r["title"])
    for r in sent:
        if r.get("t", 0) >= story_cut and same_story(title, r["title"]):
            return ("보낸기록", r["title"])
    for k in run_kept:
        if urls & item_urls(k) or same_story(title, k["title"]):
            return ("다른분야", k["title"])
    return None


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


def smart_dedupe(items, dropped=None):
    """같은 기사·같은 사건 중복 제거(same_story + 같은 주소). 스코어 높은 것 우선 보존."""
    items.sort(key=lambda x: x.get("_score", 0), reverse=True)
    kept = []
    for item in items:
        hit = None
        for existing in kept:
            if item_urls(item) & item_urls(existing) or same_story(item["title"], existing["title"]):
                hit = existing
                break
        if hit is None:
            kept.append(item)
        elif dropped is not None:
            dropped.append(("같은기사", item["title"], hit["title"]))
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


def quality_filter(all_items, category, n=TOP_N, sent=None, run_kept=None, dropped=None):
    """품질 필터링 파이프라인: 스코어링 → 스마트 중복제거 → 보낸 기록·다른 분야 제거 → 컷오프"""
    # 스코어링
    for item in all_items:
        score_item(item, category)

    # 스마트 중복 제거
    unique = smart_dedupe(all_items, dropped)

    # (113) 이미 보낸 것 / 같은 회차 다른 분야에 넣은 것 빼기
    if sent is not None or run_kept is not None:
        rest = []
        for it in unique:
            why = drop_reason(it, sent or [], run_kept or [])
            if why:
                if dropped is not None:
                    dropped.append((why[0], it["title"], why[1]))
            else:
                rest.append(it)
        unique = rest

    # 최소 점수 컷오프
    filtered = [it for it in unique if it.get("_score", 0) >= MIN_SCORE]

    # 스코어 내림차순 → 같은 주제 제한 → 상위 N개
    filtered.sort(key=lambda x: (-x.get("_score", 0), x.get("pubDate", "")), reverse=False)
    filtered.sort(key=lambda x: x.get("_score", 0), reverse=True)
    filtered = topic_cap(filtered, run_kept or [], dropped)

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


def parse_dry():
    return '--dry' in sys.argv[1:]


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
    dry = parse_dry()
    print(f"뉴스 알림 시작: {now.strftime('%Y-%m-%d %H:%M')} — {run_cats} (최근 {filter_hours}시간){' — 🧪 dry: 안 보냄·기록 안 바꿈' if dry else ''}")

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
    sent = load_sent()      # (113) 보낸 기록
    run_kept = []           # (113) 이번 회차에 이미 넣은 기사(다른 분야 중복 제거용)
    print(f"  보낸 기록 {len(sent)}건 (최근 {SENT_KEEP_H}시간)")

    for cat in run_cats:
        queries = CATEGORIES[cat]
        all_items = []
        errors = []

        for q in queries:
            items, err = search_news(q, display=CAT_DISPLAY.get(cat, 15))
            if err:
                errors.append(f"{q}: {err}")
            else:
                all_items.extend(items)
            time.sleep(0.3)

        total_searched += len(all_items)

        # 시간 필터
        all_items = filter_recent(all_items, hours=filter_hours)
        must = CAT_TITLE_MUST.get(cat)
        if must:   # (128) 제목에 기업 이름이 없는 기사는 뺌
            all_items = [it for it in all_items if any(m.lower() in it["title"].lower() for m in must)]

        # 품질 필터링 (스코어링 + 스마트 중복제거 + 보낸 기록·다른 분야 제거 + 컷오프)
        dropped = []
        top = quality_filter(all_items, cat, TOP_N, sent=sent, run_kept=run_kept, dropped=dropped)
        cnt = {}
        for d in dropped:
            cnt[d[0]] = cnt.get(d[0], 0) + 1
        if dropped:
            print(f"  {cat}: 중복 뺌 " + " · ".join(f"{k} {v}" for k, v in cnt.items()))
        if dry:
            for why, t, hit in dropped:
                print(f"     ✂ [{why}] {t[:45]}\n        ≈ {hit[:45]}")

        # 아카이브에 저장 (스코어 필드 제거)
        archive_items = [{k: v for k, v in it.items() if not k.startswith("_")} for it in top]
        archive["categories"][cat] = {"items": archive_items, "count": len(archive_items)}

        if top and dry:
            print(f"  {cat}: 🧪 보낼 것 {len(top)}개")
            for it in top:
                print(f"     → ({it.get('_score', 0)}) {it['title'][:60]} [{it.get('source', '')}]")
            run_kept.extend(top)
        elif top:
            msg = format_telegram(cat, top)
            ok = send_telegram(msg, category=cat)
            run_kept.extend(top)
            if ok:
                ts = time.time()
                for it in top:
                    sent.append({"t": ts, "title": it["title"], "key": normalize_title(it["title"]),
                                 "urls": sorted(item_urls(it))})
            total_sent += len(top)
            scores = [it.get("_score", 0) for it in top]
            print(f"  {cat}: {len(top)}개 → 봇2 DM {'✅' if ok else '❌'} (점수 {min(scores)}~{max(scores)})")
        else:
            print(f"  {cat}: 0개 ({filter_hours}시간 이내 품질 기사 없음)")
            if cat == "하남 감북" and not dry:
                now_str = datetime.now(KST).strftime('%m/%d %H:%M')
                send_telegram(f"📰 <b>{cat} 뉴스</b>  ({now_str})\n\n오늘 관련 뉴스 없음", category=cat)

        time.sleep(1)

    if dry:
        print("\n🧪 dry — 텔레그램·보낸 기록·아카이브 안 바꿈")
        return
    save_sent(sent)
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=1)

    print(f"\n✅ 완료: {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"   검색 {total_searched}개 → 품질 통과 {total_sent}개")
    print(f"   아카이브: {archive_path}")


if __name__ == "__main__":
    main()
