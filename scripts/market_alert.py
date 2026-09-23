"""
시장 지표 텔레그램 알림
======================
fetch_market_indicators.py 결과 → 텔레그램 발송.
아침(07:30) + 저녁(18:50) 2회 cron.

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os, sys, json
import urllib.request
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '')

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
INDICATORS_FILE = os.path.join(ROOT_DIR, 'data', 'market_indicators.json')
NEWS_FILE = os.path.join(ROOT_DIR, 'data', 'news.json')
NEWS_CATS = ['economy', 'stock', 'breaking']  # 경제, 증시, 속보


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print('  텔레그램 미설정')
        return False
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    body = json.dumps({
        'chat_id': TELEGRAM_CHAT,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
    })
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f'  텔레그램 전송 실패: {e}')
        return False


def fmt_num(val, decimals=2):
    """숫자 포맷 (천단위 콤마 + 소수점)."""
    if val is None:
        return '-'
    if abs(val) >= 1000:
        return f'{val:,.{decimals}f}'
    return f'{val:.{decimals}f}'


def fmt_change(change_pct):
    """변동률 포맷 (▲/▼ + 색상 없이 텍스트)."""
    if change_pct is None or change_pct == 0:
        return '→ 0.00%'
    arrow = '▲' if change_pct > 0 else '▼'
    return f'{arrow} {abs(change_pct):.2f}%'


def build_message(data, news_items=None):
    """market_indicators.json + news → 텔레그램 메시지 생성."""
    if news_items is None:
        news_items = []
    now = datetime.now(KST)
    hour = now.hour
    session = '🌅 아침' if hour < 12 else '🌙 저녁'

    lines = [f'<b>{session} 시장 브리핑 — {now.strftime("%m/%d %H:%M")}</b>\n']

    indicators = {ind['ticker']: ind for ind in data.get('indicators', [])}
    rates = data.get('rates', {})

    # ── 한국 지수 ──
    kr_tickers = ['^KS11', '^KQ11']
    kr_items = [indicators[t] for t in kr_tickers if t in indicators]
    if kr_items:
        lines.append('<b>🇰🇷 한국</b>')
        for ind in kr_items:
            lines.append(f"  {ind['name']}: {fmt_num(ind['price'], 2)} {fmt_change(ind['change_pct'])}")

    # ── 미국 지수 ──
    us_tickers = ['^GSPC', '^IXIC', '^DJI']
    us_items = [indicators[t] for t in us_tickers if t in indicators]
    if us_items:
        lines.append('<b>🇺🇸 미국</b>')
        for ind in us_items:
            lines.append(f"  {ind['name']}: {fmt_num(ind['price'], 2)} {fmt_change(ind['change_pct'])}")

    # ── VIX ──
    if '^VIX' in indicators:
        vix = indicators['^VIX']
        level = ''
        v = vix['price']
        if v < 15:
            level = '(안정)'
        elif v < 20:
            level = '(보통)'
        elif v < 30:
            level = '(경계)'
        else:
            level = '(공포)'
        lines.append(f'<b>😱 VIX</b>: {fmt_num(v, 2)} {fmt_change(vix["change_pct"])} {level}')

    # ── 환율 ──
    if rates.get('USD_KRW'):
        lines.append('<b>💱 환율</b>')
        lines.append(f"  원/달러: {fmt_num(rates['USD_KRW'], 2)}")
        if rates.get('JPY100_KRW'):
            lines.append(f"  원/엔(100): {fmt_num(rates['JPY100_KRW'], 2)}")
        if rates.get('CNY_KRW'):
            lines.append(f"  원/위안: {fmt_num(rates['CNY_KRW'], 2)}")

    # ── 금리 ──
    rate_tickers = ['^IRX', '^FVX', '^TNX', '^TYX']
    rate_items = [indicators[t] for t in rate_tickers if t in indicators]
    if rate_items:
        lines.append('<b>📊 미국 금리</b>')
        for ind in rate_items:
            lines.append(f"  {ind['name']}: {fmt_num(ind['price'], 3)}% {fmt_change(ind['change_pct'])}")

        # 장단기 스프레드 (10yr - IRX 또는 10yr 단독)
        tnx = indicators.get('^TNX')
        irx = indicators.get('^IRX')
        if tnx and irx:
            spread = round(tnx['price'] - irx['price'], 3)
            inv = ' ⚠역전' if spread < 0 else ''
            lines.append(f"  10yr-13w 스프레드: {spread:+.3f}%p{inv}")

    # ── 원유 ──
    if 'CL=F' in indicators:
        oil = indicators['CL=F']
        lines.append(f"<b>🛢️ WTI</b>: ${fmt_num(oil['price'], 2)} {fmt_change(oil['change_pct'])}")

    # ── 금시세 ──
    if rates.get('GOLD_KRW_G'):
        lines.append(f"<b>🥇 금</b>: {fmt_num(rates['GOLD_KRW_G'], 0)}원/g")

    # ── 뉴스 헤드라인 ──
    if news_items:
        lines.append('\n<b>📰 주요 뉴스</b>')
        for item in news_items[:5]:
            lines.append(f"  · {item['title']}")

    # 업데이트 시각
    lines.append(f"\n<i>데이터: {data.get('updated', '-')}</i>")

    return '\n'.join(lines)


def load_news():
    """news.json에서 경제/증시/속보 헤드라인 추출."""
    if not os.path.exists(NEWS_FILE):
        return []
    try:
        with open(NEWS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        items = []
        cats = data.get('categories', {})
        for cat in NEWS_CATS:
            cat_data = cats.get(cat, {})
            cat_items = cat_data.get('items', [])
            for item in cat_items[:3]:
                items.append({
                    'title': item.get('title', ''),
                    'cat': cat,
                    'pubDate': item.get('pubDate', ''),
                })
        # 최신순 정렬
        items.sort(key=lambda x: x.get('pubDate', ''), reverse=True)
        return items[:5]
    except Exception as e:
        print(f'  뉴스 로드 실패: {e}')
        return []


def main():
    if not os.path.exists(INDICATORS_FILE):
        print(f'❌ {INDICATORS_FILE} 없음 — fetch_market_indicators.py 먼저 실행')
        sys.exit(1)

    with open(INDICATORS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    news = load_news()
    msg = build_message(data, news)
    print(msg.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', ''))
    print(f'\n메시지 길이: {len(msg)}자')

    if send_telegram(msg):
        print('✅ 텔레그램 발송 완료')
    else:
        print('❌ 텔레그램 발송 실패')


if __name__ == '__main__':
    main()
