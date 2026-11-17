/**
 * sf-authlog.js v1 (110) — 로그인 풀림 원인 기록
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
 * 저장: localStorage 'sf-auth-log'(최근 50개), 'sf-auth-state'(마지막 상태). 개인정보 없음(이메일 안 남김).
 */
const LOG = 'sf-auth-log', ST = 'sf-auth-state', MAX = 50;

function read(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }
function write(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

if (read(LOG, null) === null) write(LOG, [{ t: Date.now(), type: 'log-start', page: location.pathname }]);

export function authLog(type, extra) {
  const log = read(LOG, []);
  log.push(Object.assign({ t: Date.now(), type, page: location.pathname }, extra || {}));
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
      fb_idb: idb                                                // Firebase 저장소(IndexedDB)가 남아 있는지
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
