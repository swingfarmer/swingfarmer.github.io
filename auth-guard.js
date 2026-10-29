/**
 * auth-guard.js v6 — 전 페이지 로그인 필수 가드
 * 3중 차단: CSS ::before + DOM 커버 + visibility
 * 비관리자 차단 시 실제 UID 크게 표시
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

  const uidBlock = rejectedUid
    ? `<div class="sf-aw-uid">UID: ${rejectedUid}</div>`
    : '';

  wall.innerHTML = `
    <div class="sf-aw-box">
      <div class="sf-aw-icon">🔒</div>
      <div class="sf-aw-title">비공개 페이지</div>
      <div class="sf-aw-desc">이 사이트는 관리자 전용입니다.<br>Google 계정으로 인증해주세요.</div>
      <button class="sf-aw-btn" id="sfAwBtn">
        <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="">
        Google 로그인
      </button>
      <div class="sf-aw-err" id="sfAwErr">${
        rejectedEmail
          ? `관리자 계정이 아닙니다. (${rejectedEmail})`
          : ''
      }</div>
      ${uidBlock}
    </div>`;
  if (rejectedEmail) document.getElementById("sfAwErr").style.display = "block";
  document.getElementById("sfAwBtn").addEventListener("click", async () => {
    const errEl = document.getElementById("sfAwErr");
    const uidEl = wall.querySelector(".sf-aw-uid");
    if (errEl) { errEl.style.display = "none"; errEl.textContent = ""; }
    if (uidEl) uidEl.remove();
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
  btn.addEventListener("click", () => signOut(auth));
  document.body.appendChild(btn);
}

function removeLogoutBtn() {
  const btn = document.getElementById("sf-logout-btn");
  if (btn) btn.remove();
}

/* ── Auth 상태 감시 ── */
onAuthStateChanged(auth, (user) => {
  if (user && ADMIN_UIDS.includes(user.uid)) {
    /* ✅ 허용 */
    const wall = document.getElementById("sf-auth-wall");
    if (wall) wall.remove();
    removeCover();
    document.body.classList.add("sf-authed");
    createLogoutBtn(user);
  } else {
    /* ❌ 미인증 또는 비허용 */
    document.body.classList.remove("sf-authed");
    removeLogoutBtn();
    if (user && !ADMIN_UIDS.includes(user.uid)) {
      const email = user.email;
      const uid = user.uid;
      signOut(auth).then(() => createWall(email, uid));
      return;
    }
    createWall();
  }
});
