"""
국토부 실거래 API 공통 호출 (082)
- 정상 응답인지 resultCode로 확인 (한도 초과·키 오류도 HTTP 200으로 옴 → 예전엔 0건으로 오인)
- totalCount가 한 페이지(9,999)를 넘으면 다음 페이지까지 받음
- 반환: XML 문자열 리스트(페이지별) / 실패 시 None
"""
import time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET

CALL_DELAY = 0.3
ROWS = 9999
OK_CODES = ('000', '00')


def _get(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=20) as resp:
                data = resp.read().decode('utf-8')
            time.sleep(CALL_DELAY)
            return data
        except Exception:
            if attempt < 2:
                print(f' ⏳재시도({attempt+2}/3)...', end='', flush=True)
                time.sleep(2)
    time.sleep(CALL_DELAY)
    return None


def _check(xml):
    """(성공여부, totalCount, 메시지)"""
    try:
        root = ET.fromstring(xml)
    except Exception:
        return False, 0, 'XML 파싱 실패'
    if root.tag == 'OpenAPI_ServiceResponse':          # 게이트웨이 에러(한도 초과·키 오류)
        msg = root.findtext('.//returnAuthMsg') or root.findtext('.//errMsg') or '게이트웨이 에러'
        return False, 0, msg
    code = (root.findtext('.//resultCode') or '').strip()
    if code and code not in OK_CODES:
        return False, 0, f'resultCode {code} {root.findtext(".//resultMsg") or ""}'.strip()
    try:
        total = int(root.findtext('.//totalCount') or 0)
    except Exception:
        total = 0
    return True, total, ''


def api_call(endpoint, api_key, lawd_cd, deal_ymd):
    pages, page = [], 1
    while True:
        params = {'serviceKey': api_key, 'LAWD_CD': lawd_cd, 'DEAL_YMD': deal_ymd,
                  'pageNo': str(page), 'numOfRows': str(ROWS)}
        xml = _get(endpoint + '?' + urllib.parse.urlencode(params))
        if xml is None:
            print(' ❌실패(접속)', end='', flush=True)
            return None
        ok, total, msg = _check(xml)
        if not ok:
            print(f' ❌실패({msg[:40]})', end='', flush=True)
            return None
        pages.append(xml)
        if total <= page * ROWS or page >= 5:
            return pages
        page += 1
