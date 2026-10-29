/**
 * auth-guard.js v2 — 전 페이지 로그인 필수 가드
 *
 * CSS가 body 자식 전부 display:none → 로그인 월만 보임
 * 인증 성공 시 body.sf-authed 클래스 추가 → 콘텐츠 복원
 */
import { initializeApp, getApps } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-auth.js";

const ADMIN_UIDS = [
  "1JrHgD2bpTRjrS2jw7MbpHciBph1"
  // 추가 계정 UID를 여기에 추가
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

/* ── 로그인 월 UI ── */
function createWall() {
  if (document.getElementById("sf-auth-wall")) return;
  const wall = document.createElement("div");
  wall.id = "sf-auth-wall";
  wall.innerHTML = `
    <div class="sf-aw-box">
      <div class="sf-aw-icon">🔒</div>
      <div class="sf-aw-title">비공개 페이지</div>
      <div class="sf-aw-desc">이 사이트는 관리자 전용입니다.<br>Google 계정으로 인증해주세요.</div>
      <button class="sf-aw-btn" id="sfAwBtn">
        <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="">
        Google 로그인
      </button>
      <div class="sf-aw-err" id="sfAwErr"></div>
    </div>`;
  document.body.prepend(wall);
  document.getElementById("sfAwBtn").addEventListener("click", async () => {
    try {
      await signInWithPopup(auth, provider);
    } catch (e) {
      const errEl = document.getElementById("sfAwErr");
      errEl.textContent = "로그인 실패: " + e.message;
      errEl.style.display = "block";
    }
  });
}

/* ── Auth 상태 감시 ── */
onAuthStateChanged(auth, (user) => {
  if (user && ADMIN_UIDS.includes(user.uid)) {
    /* ✅ 허용된 계정 — 콘텐츠 표시 */
    const wall = document.getElementById("sf-auth-wall");
    if (wall) wall.remove();
    document.body.classList.add("sf-authed");
  } else {
    /* ❌ 미인증 또는 비허용 계정 */
    document.body.classList.remove("sf-authed");
    if (user && !ADMIN_UIDS.includes(user.uid)) {
      signOut(auth);
    }
    createWall();
  }
});
