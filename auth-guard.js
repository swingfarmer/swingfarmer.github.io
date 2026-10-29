/**
 * auth-guard.js DEBUG — UID 확인용 임시 버전
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

/* ── 로그인 월 ── */
function createWall() {
  if (document.getElementById("sf-auth-wall")) return;
  const wall = document.createElement("div");
  wall.id = "sf-auth-wall";
  wall.innerHTML = `
    <div class="sf-aw-box">
      <div class="sf-aw-icon">🔒</div>
      <div class="sf-aw-title">스윙파머 금융도구</div>
      <div class="sf-aw-desc">개인 전용 공간입니다.<br>관리자 로그인이 필요합니다.</div>
      <button class="sf-aw-btn" id="sfAwBtn">
        <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="">
        Google 로그인
      </button>
      <div class="sf-aw-err" id="sfAwErr"></div>
    </div>`;
  document.body.prepend(wall);
  document.getElementById("sfAwBtn").addEventListener("click", async () => {
    try { await signInWithPopup(auth, provider); }
    catch (e) {
      document.getElementById("sfAwErr").textContent = e.message;
      document.getElementById("sfAwErr").style.display = "block";
    }
  });
}

function createLogoutBtn(user) {
  if (document.getElementById("sf-logout-btn")) return;
  const btn = document.createElement("button");
  btn.id = "sf-logout-btn";
  btn.title = user.email || "로그아웃";
  btn.textContent = "🔓";
  btn.addEventListener("click", () => signOut(auth));
  document.body.appendChild(btn);
}

/* ── Auth ── */
onAuthStateChanged(auth, (user) => {
  if (user && ADMIN_UIDS.includes(user.uid)) {
    const wall = document.getElementById("sf-auth-wall");
    if (wall) wall.remove();
    document.body.classList.add("sf-authed");
    createLogoutBtn(user);
  } else if (user) {
    /* ★ 비관리자 — alert로 UID 표시 ★ */
    const msg = "⚠️ 비관리자 감지!\n\n"
              + "이메일: " + user.email + "\n"
              + "UID: " + user.uid + "\n\n"
              + "이 UID를 복사해서 채팅에 붙여주세요.";
    alert(msg);
    document.title = "UID: " + user.uid;
    signOut(auth);
  } else {
    document.body.classList.remove("sf-authed");
    createWall();
  }
});
