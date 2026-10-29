/**
 * auth-guard.js v8 — display:none 차단 + UID 에러텍스트 직접 삽입
 */
import { initializeApp, getApps } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-auth.js";

const ADMIN_UIDS = [
  "1JrHgD2bpTRjrS2jw7MbpHciBph1",
  "Ydd8v6LCN2TPjkqKD4DejLSWwaL2"
];
const firebaseConfig = {
  apiKey: "AIzaSyB-Ynu-KdYL4sqPers2XnPt5dEEsKsXvMY",
  authDomain: "swingfarmer-board01.firebaseapp.com",
  projectId: "swingfarmer-board01",
  storageBucket: "swingfarmer-board01.firebasestorage.app",
  messagingSenderId: "312575044644",
  appId: "1:312575044644:web:81d754eb1d90f25454fcb1"
};

const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);
const auth = getAuth(app);
const provider = new GoogleAuthProvider();
provider.setCustomParameters({ prompt: "select_account" });

let _rejected = null;

/* ── DOM 커버 ── */
function ensureCover() {
  if (document.getElementById("sf-auth-cover")) return;
  const cover = document.createElement("div");
  cover.id = "sf-auth-cover";
  document.body.prepend(cover);
}
function removeCover() {
  const c = document.getElementById("sf-auth-cover");
  if (c) c.remove();
}

/* ── 로그인 월 UI ── */
function createWall(rejectedEmail, rejectedUid) {
  let wall = document.getElementById("sf-auth-wall");
  if (!wall) {
    wall = document.createElement("div");
    wall.id = "sf-auth-wall";
    document.body.prepend(wall);
  }

  /* UID를 에러 텍스트 안에 직접 넣음 — 별도 div 아님 */
  let errMsg = '';
  if (rejectedEmail) {
    errMsg = `관리자 계정이 아닙니다. (${rejectedEmail})<br><br>`
           + `<span style="background:#f1f5f9;padding:6px 10px;border-radius:6px;`
           + `font-size:13px;color:#333;display:inline-block;user-select:all;`
           + `word-break:break-all;font-family:monospace">`
           + `UID: ${rejectedUid}</span>`;
  }

  wall.innerHTML = `
    <div class="sf-aw-box">
      <div class="sf-aw-icon">🔒</div>
      <div class="sf-aw-title">스윙파머 금융도구</div>
      <div class="sf-aw-desc">개인 전용 공간입니다.<br>관리자 로그인이 필요합니다.</div>
      <button class="sf-aw-btn" id="sfAwBtn">
        <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="">
        Google 로그인
      </button>
      <div class="sf-aw-err" id="sfAwErr">${errMsg}</div>
    </div>`;
  if (rejectedEmail) document.getElementById("sfAwErr").style.display = "block";
  document.getElementById("sfAwBtn").addEventListener("click", async () => {
    const errEl = document.getElementById("sfAwErr");
    if (errEl) { errEl.style.display = "none"; errEl.innerHTML = ""; }
    _rejected = null;
    try {
      await signInWithPopup(auth, provider);
    } catch (e) {
      if (errEl) {
        errEl.textContent = "로그인 실패: " + e.message;
        errEl.style.display = "block";
      }
    }
  });
  ensureCover();
}

/* ── 로그아웃 버튼 ── */
function createLogoutBtn(user) {
  if (document.getElementById("sf-logout-btn")) return;
  const btn = document.createElement("button");
  btn.id = "sf-logout-btn";
  btn.title = user.email || "로그아웃";
  btn.textContent = "🔓";
  btn.addEventListener("click", () => { _rejected = null; signOut(auth); });
  document.body.appendChild(btn);
}

function removeLogoutBtn() {
  const btn = document.getElementById("sf-logout-btn");
  if (btn) btn.remove();
}

/* ── Auth 상태 감시 ── */
onAuthStateChanged(auth, (user) => {
  if (user && ADMIN_UIDS.includes(user.uid)) {
    _rejected = null;
    const wall = document.getElementById("sf-auth-wall");
    if (wall) wall.remove();
    removeCover();
    document.body.classList.add("sf-authed");
    createLogoutBtn(user);
  } else {
    document.body.classList.remove("sf-authed");
    removeLogoutBtn();
    if (user && !ADMIN_UIDS.includes(user.uid)) {
      _rejected = { email: user.email, uid: user.uid };
      signOut(auth);
      return;
    }
    if (_rejected) {
      createWall(_rejected.email, _rejected.uid);
    } else {
      createWall();
    }
  }
});
