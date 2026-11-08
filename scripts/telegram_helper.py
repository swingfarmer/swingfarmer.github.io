"""
텔레그램 발송 공용 모듈
======================
봇1 (TELEGRAM_BOT_TOKEN)  — 기술 알림: 스크리너·시그널·수급·마켓 브리핑
봇2 (TELEGRAM_BOT2_TOKEN) — 뉴스 알림: 매시간 뉴스 헤드라인

- DM: TELEGRAM_CHAT_ID (봇 주인만)
- 채널: TELEGRAM_CHANNEL_ID (@swingfarmer) — 현재 미사용
"""
import os, json, urllib.request

BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '')
BOT2_TOKEN = os.environ.get('TELEGRAM_BOT2_TOKEN', '')
CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '')        # DM (주인)
CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID', '')     # 채널

# 봇 DM 화이트리스트 (이 chat_id만 봇 응답)
ALLOWED_CHAT_IDS = {int(CHAT_ID)} if CHAT_ID else set()


def _send(chat_id, text, parse_mode='HTML', bot_token=None):
    """단일 대상 발송. bot_token 지정 시 해당 봇으로 발송."""
    token = bot_token or BOT_TOKEN
    if not token or not chat_id:
        return False
    url = f'https://api.telegram.org/bot{token}/sendMessage'
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


# ── 봇1 (기술 알림) ──

def send_dm(text, parse_mode='HTML'):
    """봇1 → 봇 주인 DM으로만 발송."""
    return _send(CHAT_ID, text, parse_mode)


def send_channel(text, parse_mode='HTML'):
    """봇1 → 채널로만 발송."""
    return _send(CHANNEL_ID, text, parse_mode)


def send_all(text, parse_mode='HTML'):
    """봇1 → DM + 채널 둘 다 발송."""
    r1 = _send(CHAT_ID, text, parse_mode)
    r2 = _send(CHANNEL_ID, text, parse_mode)
    return r1 or r2


# ── 봇2 (뉴스) ──

def send_dm_bot2(text, parse_mode='HTML'):
    """봇2 → 봇 주인 DM으로만 발송."""
    return _send(CHAT_ID, text, parse_mode, bot_token=BOT2_TOKEN)


# ── 공통 ──

def is_allowed(chat_id):
    """봇 DM 화이트리스트 체크."""
    return int(chat_id) in ALLOWED_CHAT_IDS
