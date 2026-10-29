/**
 * auth-guard.js — 전 페이지 로그인 필수 가드
 * <link rel="stylesheet" href="/auth-guard.css?v=1">  ← <head>에
 * <script type="module" src="/auth-guard.js?v=1"></script>
 *
 * 동작: CSS가 body를 숨김 → 이 스크립트가 Firebase Auth 확인
 *       → ADMIN_UID 일치 시 body 표시 / 아니면 로그인 월 표시
 */
import { initializeApp, getApps } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-auth.js";

const ADMIN_UID = "1JrHgD2bpTRjrS2jw7MbpHciBph1";
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

/* ── 로그인 월 UI 생성 ── */
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
  if (user && user.uid === ADMIN_UID) {
    /* ✅ 관리자 인증 완료 — 콘텐츠 표시 */
    const wall = document.getElementById("sf-auth-wall");
    if (wall) wall.remove();
    /* CSS !important 를 이기려면 setProperty 필수 */
    document.body.style.setProperty("visibility", "visible", "important");
  } else {
    /* ❌ 미인증 또는 다른 계정 — 로그인 월 표시 */
    if (user && user.uid !== ADMIN_UID) {
      signOut(auth);  // 다른 계정이면 로그아웃
    }
    createWall();
    // wall 자체는 CSS에서 visibility:visible 처리
  }
});
