"""
텔레그램 발송 공용 모듈
======================
- DM: TELEGRAM_CHAT_ID (봇 주인만)
- 채널: TELEGRAM_CHANNEL_ID (@swingfarmer)
둘 다 발송. 하나 실패해도 다른 쪽은 발송.
"""
import os, json, urllib.request

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')        # DM (주인)
CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID', '')   # 채널

# 봇 DM 화이트리스트 (이 chat_id만 봇 응답)
ALLOWED_CHAT_IDS = {int(CHAT_ID)} if CHAT_ID else set()


def _send(chat_id, text, parse_mode='HTML'):
    """단일 대상 발송."""
    if not BOT_TOKEN or not chat_id:
        return False
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    body = json.dumps({
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
        'disable_web_page_preview': True,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
    })
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f'  ⚠ 텔레그램 전송 실패 ({chat_id}): {e}')
        return False


def send_dm(text, parse_mode='HTML'):
    """봇 주인 DM으로만 발송."""
    return _send(CHAT_ID, text, parse_mode)


def send_channel(text, parse_mode='HTML'):
    """채널로만 발송."""
    return _send(CHANNEL_ID, text, parse_mode)


def send_all(text, parse_mode='HTML'):
    """DM + 채널 둘 다 발송."""
    r1 = _send(CHAT_ID, text, parse_mode)
    r2 = _send(CHANNEL_ID, text, parse_mode)
    return r1 or r2


def is_allowed(chat_id):
    """봇 DM 화이트리스트 체크."""
    return int(chat_id) in ALLOWED_CHAT_IDS
