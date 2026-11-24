"""
분기봉 양봉·음봉 알림 (131) — [봇1] 매월 말일 장마감 뒤
==========================================================
대상: 코스피(^KS11)·코스닥(^KQ11) 지수 (사용자 131: 지수만, 매달 말일)
- 분기봉: 분기 첫 거래일 시가 → 마지막 거래일 종가. 종가 > 시가 양봉(🔴), < 음봉(🔵), 같으면 보합
- 3·6·9·12월 말일 = 「확정」 → 이번 분기 색 + 몇 분기 연속인지
- 그 밖의 달 말일 = 「중간점검」 → 진행 중인 분기가 지금 양/음봉인지 + 이대로 끝나면 몇 분기 연속인지
- 최근 8분기 색 줄도 같이 (왼쪽이 오래된 것)
- 사이트 링크 넣지 않음 (130 규칙)

데이터: yfinance 월봉(period=max) → 분기로 묶음 (시가 = 분기 첫 달 시가, 종가 = 마지막 달 종가)
         마지막 거래일은 일봉으로 확인해 메시지에 「M/D 종가 기준」으로 적음

사용법:
  python3 scripts/quarter_candle.py          # 계산 + 텔레그램 발송
  python3 scripts/quarter_candle.py --dry    # 화면에만 출력 (발송 안 함)
  python3 scripts/quarter_candle.py --final  # 분기 마지막 달이 아니어도 「확정」 모양으로 (시험용)
"""

import os, sys, argparse
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

KST = timezone(timedelta(hours=9))
INDICES = [('^KS11', '코스피'), ('^KQ11', '코스닥')]
RECENT = 8      # 최근 몇 분기 색 줄
JUMP_WARN = 5.0  # 최근 2분기 시가가 직전 분기 종가와 이만큼(%) 넘게 벌어지면 로그 경고 (야후 시가 빠짐 의심 — 실제 갭일 수도 있음: 2026-04-01 +8% 상승일)


def color(o, c):
    if c > o: return 'up'
    if c < o: return 'down'
    return 'flat'


EMO = {'up': '🔴', 'down': '🔵', 'flat': '⚪'}
NAME = {'up': '양봉', 'down': '음봉', 'flat': '보합'}


def to_quarters(months):
    """months: [(datetime 월초, open, close)] 오래된 순 → [{'key':(y,q), 'open','close','n'}]"""
    qs = []
    for d, o, c in months:
        key = (d.year, (d.month - 1) // 3 + 1)
        if qs and qs[-1]['key'] == key:
            qs[-1]['close'] = c; qs[-1]['n'] += 1
        else:
            qs.append({'key': key, 'open': o, 'close': c, 'n': 1})
    for q in qs:
        q['color'] = color(q['open'], q['close'])
        q['pct'] = (q['close'] / q['open'] - 1) * 100 if q['open'] else 0.0
    return qs


def streak(qs, upto):
    """qs[upto] 를 포함해 거꾸로 같은 색이 몇 분기 이어졌나 (보합이면 1)"""
    col = qs[upto]['color']
    if col == 'flat': return 1
    n = 0
    for i in range(upto, -1, -1):
        if qs[i]['color'] != col: break
        n += 1
    return n


def jump_check(qs, label):
    for i in range(max(1, len(qs) - 2), len(qs)):  # 최근 2분기만 (131: 옛 분기 실제 갭(2026 2Q +5.5% 등)이 매달 로그에 반복되지 않게)
        prev, cur = qs[i - 1]['close'], qs[i]['open']
        if prev and abs(cur / prev - 1) * 100 > JUMP_WARN:
            y, q = qs[i]['key']
            print(f'  ⚠ {label} {y} {q}Q 시가 {cur:,.2f} vs 직전 분기 종가 {prev:,.2f} ({(cur/prev-1)*100:+.1f}%) — 야후 시가 확인 필요')


def index_lines(label, qs, final):
    cur = qs[-1]
    y, q = cur['key']
    s_now = streak(qs, len(qs) - 1)
    recent = ''.join(EMO[x['color']] for x in qs[-RECENT:])
    base = f"<b>{label}</b> {EMO[cur['color']]}{NAME[cur['color']]} {cur['pct']:+.2f}%  (시가 {cur['open']:,.2f} → {cur['close']:,.2f})"
    def run(n, col):  # 「3분기 연속 양봉」 / 1이면 「직전 분기 양봉」 모양
        return f"{n}분기 연속 {NAME[col]}" if n >= 2 else f"분기 {NAME[col]}"
    prev = f"직전 {run(streak(qs, len(qs) - 2), qs[-2]['color'])}" if len(qs) >= 2 and qs[-2]['color'] != 'flat' else '직전 분기 보합'
    if cur['color'] == 'flat':
        tail = ('보합 — 연속 끊김' if final else '지금 보합') + f" ({prev})"
    elif s_now >= 2:
        tail = ('' if final else '이대로 끝나면 ') + f"<b>{s_now}분기 연속 {NAME[cur['color']]}</b>"
    else:
        tail = ('' if final else '이대로 끝나면 ') + f"<b>{NAME[cur['color']]} 전환</b> ({prev}{' 끝' if final else ''})"
    return [base, f"   {tail}", f"   최근 {min(RECENT, len(qs))}분기 {recent}{'' if final else '(진행)'}"]


def build_message(data, today, final, last_trade):
    """data: [(label, quarters)]"""
    y, q = data[0][1][-1]['key']
    m_in_q = (today.month - 1) % 3 + 1
    lt = f'{last_trade.month}/{last_trade.day} 종가 기준' if last_trade else '종가 기준'
    if final:
        head = f'🕯 <b>분기봉 확정</b> {y} {q}Q ({lt})'
    else:
        head = f'🕯 <b>분기봉 중간점검</b> {y} {q}Q {m_in_q}/3개월째 ({lt})'
    lines = [head, '']
    for label, qs in data:
        lines += index_lines(label, qs, final)
    lines += ['', '🔴 양봉 = 분기 첫 거래일 시가보다 종가가 높음 / 🔵 음봉 = 낮음']
    return '\n'.join(lines)


def fetch(sym):
    import yfinance as yf  # 월 1번만 돌아서 무거운 import 괜찮음
    t = yf.Ticker(sym)
    m = t.history(period='max', interval='1mo', auto_adjust=False)
    d = t.history(period='10d', interval='1d', auto_adjust=False)
    months = []
    for idx, row in m.iterrows():
        o, c = float(row['Open']), float(row['Close'])
        if o > 0 and c > 0:  # 0·빈 값(휴장·결측)은 버림 (107 규칙)
            months.append((datetime(idx.year, idx.month, 1), o, c))
    last_trade = None
    if not d.empty:
        li = d.index[-1]; last_trade = datetime(li.year, li.month, li.day)
        # 월봉 마지막 칸 종가를 일봉 마지막 종가로 맞춤 (월봉 갱신이 늦을 때 대비)
        lc = float(d['Close'].iloc[-1])
        if months and lc > 0 and (months[-1][0].year, months[-1][0].month) == (li.year, li.month):
            months[-1] = (months[-1][0], months[-1][1], lc)
    return months, last_trade


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true', help='출력만, 발송 안 함')
    ap.add_argument('--final', action='store_true', help='확정 모양으로 (시험용)')
    a = ap.parse_args()
    today = datetime.now(KST)
    final = a.final or today.month % 3 == 0
    print(f'🕯 분기봉 {"확정" if final else "중간점검"} 시작 {today:%Y-%m-%d %H:%M}')
    data, last_trade = [], None
    for sym, label in INDICES:
        try:
            months, lt = fetch(sym)
        except Exception as e:
            print(f'  ❌ {label} 받기 실패: {e}'); continue
        if len(months) < 6:
            print(f'  ❌ {label} 월봉 {len(months)}개뿐 — 건너뜀'); continue
        qs = to_quarters(months)
        jump_check(qs, label)
        if (qs[-1]['key'][0], qs[-1]['key'][1]) != (today.year, (today.month - 1) // 3 + 1):
            print(f'  ⚠ {label} 마지막 분기 {qs[-1]["key"]} ≠ 이번 분기 — 야후 갱신 늦음?')
        print(f'  {label}: 월봉 {len(months)}개 ({months[0][0]:%Y-%m}~{months[-1][0]:%Y-%m}), 마지막 거래일 {lt:%Y-%m-%d}' if lt else f'  {label}: 월봉 {len(months)}개')
        data.append((label, qs)); last_trade = last_trade or lt
    if not data:
        print('  ❌ 받은 지수 없음 — 발송 안 함'); sys.exit(1)
    msg = build_message(data, today, final, last_trade)
    print(msg)
    if a.dry:
        print('  (--dry: 발송 안 함)'); return
    from telegram_helper import send_dm
    send_dm(msg)
    print('  [봇1] 분기봉 메시지 발송')


if __name__ == '__main__':
    main()
