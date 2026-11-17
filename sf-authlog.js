/**
 * sf-authlog.js v2 (110) — 로그인 풀림 원인 기록
 * 108·109에서 내장 브라우저(aichatetc)가 몇 초~수십 분 만에 로그아웃됨. 사이트 코드의 signOut은
 * auth-guard 2곳(🔓 버튼, 관리자 아닌 계정)뿐이라, 그 밖의 이유로 풀리면 'lost'로 남긴다.
 *
 * 보는 법: 아무 페이지에서 F12 → 콘솔 → sfAuthLog()   (지우기: sfAuthLog('clear'))
 *  - in           관리자 로그인 상태가 됨(직전이 로그아웃일 때만 기록)
 *  - out-btn      🔓 버튼으로 로그아웃
 *  - out-nonadmin 관리자 아닌 계정이라 사이트가 로그아웃시킴
 *  - lost         사이트가 signOut 안 했는데 풀림 ← 원인 추적 대상 (브라우저·Google 세션 쪽)
 *  - auth-err     Firebase 인증 오류(토큰 갱신 실패 등)
 *  - log-start    기록이 처음 생김. 'in' 기록이 있었는데 이게 또 보이면 = 브라우저 저장소가 통째로 지워진 것
 *  - lost의 tabs = 그 순간 살아 있던 다른 탭·창(같은 사이트). 다른 곳에서 로그아웃시키면 Firebase가 저장소를 통해 이 탭도 같이 풀어 버림
 *    (110 첫 기록: 네트워크 요청 없이 풀림 → 토큰 만료가 아니라 저장소 쪽). tabs가 비어 있으면 = 새 코드 안 도는 곳(옛 탭·브라우저 자체)
 * 저장: localStorage 'sf-auth-log'(최근 50개), 'sf-auth-state'(마지막 상태). 개인정보 없음(이메일 안 남김).
 */
const LOG = 'sf-auth-log', ST = 'sf-auth-state', MAX = 50;

function read(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }
function write(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

if (read(LOG, null) === null) write(LOG, [{ t: Date.now(), type: 'log-start', page: location.pathname }]);

/* 탭 생존 신호 — 5초마다. lost 때 다른 탭이 있었는지 본다 */
const TABS = 'sf-auth-tabs', TAB_ID = Math.random().toString(36).slice(2, 8), T0 = Date.now();
function beat() {
  const m = read(TABS, {}), now = Date.now();
  for (const k in m) if (now - m[k].t > 15000) delete m[k];
  m[TAB_ID] = { t: now, page: location.pathname, open_s: Math.round((now - T0) / 1000) };
  write(TABS, m);
}
beat(); setInterval(beat, 5000);
window.addEventListener('pagehide', () => { const m = read(TABS, {}); delete m[TAB_ID]; write(TABS, m); });
function otherTabs() {
  const m = read(TABS, {}), now = Date.now();
  return Object.keys(m).filter(k => k !== TAB_ID && now - m[k].t < 15000).map(k => m[k].page + ' (' + Math.round((now - m[k].t) / 1000) + 's 전)');
}

export function authLog(type, extra) {
  const log = read(LOG, []);
  log.push(Object.assign({ t: Date.now(), type, page: location.pathname, tab: TAB_ID }, extra || {}));
  write(LOG, log.slice(-MAX));
}
export function getState() { return read(ST, null); }          // {s:'in'|'out', t}
export function setState(s) { write(ST, { s, t: Date.now() }); }

/* 로그인 상태 변화 한 번 처리. kind: 'admin' | 'none' (auth-guard·private-loader 공통) */
let _first = true;
export async function onAuthChange(kind) {
  const prev = getState();
  const first = _first; _first = false;
  if (kind === 'admin') {
    if (!prev || prev.s !== 'in') authLog('in');
    setState('in');
    return;
  }
  if (prev && prev.s === 'in') {
    let idb = null;
    try { if (indexedDB.databases) idb = (await indexedDB.databases()).map(d => d.name).includes('firebaseLocalStorageDb'); } catch (e) {}
    authLog('lost', {
      since_in_min: Math.round((Date.now() - prev.t) / 60000),   // 마지막 로그인 확인 뒤 몇 분
      on_load: first,                                            // true = 페이지 열 때 이미 풀려 있음 / false = 보던 중에 풀림
      page_age_s: Math.round(performance.now() / 1000),
      visible: document.visibilityState,
      online: navigator.onLine,
      fb_idb: idb,                                               // Firebase 저장소(IndexedDB)가 남아 있는지
      tabs: otherTabs()                                          // 그때 살아 있던 다른 탭
    });
  }
  setState('out');
}

window.addEventListener('unhandledrejection', (e) => {
  const c = e.reason && e.reason.code;
  if (typeof c === 'string' && c.startsWith('auth/')) authLog('auth-err', { code: c });
});

window.sfAuthLog = function (cmd) {
  if (cmd === 'clear') { write(LOG, []); return '지움'; }
  const rows = read(LOG, []).map(r => Object.assign({ when: new Date(r.t).toLocaleString('ko-KR') }, r));
  console.table(rows);
  return rows;
};
