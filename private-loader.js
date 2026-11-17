/**
 * private-loader.js v1 (109) — 🔒 개인 문서(자산·리서치 노트, 종목 시뮬레이터, 포트폴리오)는
 * 공개 레포에 원본이 없다. 원본은 비공개 레포 swingfarmer/sf-private → VM이 받아 둠 →
 * /api/private?path=… 가 관리자 토큰이 있을 때만 내준다.
 * 공개 레포의 같은 주소에는 이 파일을 부르는 껍데기만 둔다(주소·링크는 그대로).
 * 껍데기는 common.js·auth-guard.js를 읽지 않는다 — 원본을 그린 뒤 원본이 처음 읽어야 정상 동작.
 */
import { initializeApp, getApps } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-auth.js";

const API = 'https://swingfarmer.duckdns.org/api/private?path=';
const app = getApps().length ? getApps()[0] : initializeApp({
  apiKey: "AIzaSyB-Ynu-KdYL4sqPers2XnPt5dEEsKsXvMY",
  authDomain: "swingfarmer-board01.firebaseapp.com",
  projectId: "swingfarmer-board01"
});
const auth = getAuth(app);

// 원본 페이지 안에서도 비공개 파일(json 등)을 받을 때 쓴다: sfPrivateFetch('portfolio/current.json')
window.sfPrivateFetch = async function (path) {
  const u = auth.currentUser;
  if (!u) throw new Error('로그인 필요');
  const t = await u.getIdToken();
  return fetch(API + encodeURIComponent(path), { headers: { Authorization: 'Bearer ' + t }, cache: 'no-store' });
};

function pagePath() {
  let p = decodeURIComponent(location.pathname).replace(/^\/+/, '');
  if (p === '' || p.endsWith('/')) p += 'index.html';
  return p;
}

const box = () => document.getElementById('sfPrivMsg');
function msg(html, btn) {
  const b = box(); if (!b) return;
  b.innerHTML = html + (btn ? '<br><br><button id="sfPrivLogin" style="padding:10px 18px;border:1px solid #ddd;border-radius:8px;background:#fff;font-size:15px;cursor:pointer">Google 로그인</button>' : '');
  const l = document.getElementById('sfPrivLogin');
  if (l) l.onclick = () => { const p = new GoogleAuthProvider(); p.setCustomParameters({ prompt: 'select_account' }); signInWithPopup(auth, p).catch(e => msg('로그인 실패: ' + e.message, true)); };
}

let done = false;
onAuthStateChanged(auth, async (user) => {
  if (done) return;
  if (!user) { msg('🔒 개인 전용 문서입니다.<br>관리자 로그인이 필요합니다.', true); return; }
  msg('불러오는 중…');
  try {
    const r = await window.sfPrivateFetch(pagePath());
    if (r.status === 401 || r.status === 403) { msg('관리자 계정이 아닙니다. (' + (user.email || '') + ')', true); return; }
    if (r.status === 404) { msg('문서를 찾을 수 없습니다: ' + pagePath()); return; }
    if (!r.ok) { msg('서버 오류 (' + r.status + ') — VM이 꺼져 있을 수 있습니다.'); return; }
    const html = await r.text();
    done = true;
    document.open(); document.write(html); document.close();
  } catch (e) {
    msg('서버에 연결하지 못했습니다 — VM(swingfarmer.duckdns.org)이 꺼져 있을 수 있습니다.<br><small>' + e.message + '</small>');
  }
});
