/**
 * IncidentIQ — Auth Controller (auth.js)
 * Loaded by login.html, user-portal.html, and manager-dashboard.html.
 *
 * Responsibilities:
 *   - On the LOGIN page: handle sign-in / sign-up forms, then redirect.
 *   - On PORTAL / DASHBOARD pages: provide requireAuth(), getSession(),
 *     generateId(), and logout() helpers.
 */

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */
const SESSION_KEY = "iq_session";

// Detect which page we're on
const _currentPage = window.location.pathname.split("/").pop() || "index.html";
const _isLoginPage = _currentPage === "login.html";
const _isPortalPage =
    _currentPage === "user-portal.html" ||
    _currentPage === "manager-dashboard.html";

// Role from query string (only relevant on login page)
const _params = new URLSearchParams(window.location.search);
const _role = _params.get("role") || "user";

/* ------------------------------------------------------------------ */
/*  Firebase Compat SDK — dynamic loader                              */
/* ------------------------------------------------------------------ */
let firebaseAuth = null;
let _firebaseReady = false;
const _firebaseReadyCallbacks = [];

(function loadFirebaseCompat() {
    const v = "11.4.0";
    const srcs = [
        `https://www.gstatic.com/firebasejs/${v}/firebase-app-compat.js`,
        `https://www.gstatic.com/firebasejs/${v}/firebase-auth-compat.js`,
    ];

    let loaded = 0;
    srcs.forEach((src) => {
        const s = document.createElement("script");
        s.src = src;
        s.onload = () => {
            loaded++;
            if (loaded === srcs.length) _initFirebase();
        };
        s.onerror = () => console.error("Failed to load Firebase SDK:", src);
        document.head.appendChild(s);
    });
})();

async function _initFirebase() {
    let cfg = {
        apiKey: "AIzaSyCyK_XmqN2FKKsmj_8RH3cDkhGb5459L08",
        authDomain: "accident-detection-5d0e6.firebaseapp.com",
        projectId: "accident-detection-5d0e6",
        storageBucket: "accident-detection-5d0e6.firebasestorage.app",
        messagingSenderId: "505018896595",
        appId: "1:505018896595:web:9a3ce5e45fdf441d6f0426",
        measurementId: "G-3RWDVHJM5D",
    };

    try {
        const response = await fetch('/api/config');
        if (response.ok) {
            const remoteConfig = await response.json();
            if (remoteConfig.apiKey) {
                cfg = remoteConfig;
                console.log("[IncidentIQ] 🔥 Firebase Auth config loaded from backend .env");
            }
        }
    } catch (e) {
        console.warn("[IncidentIQ] ⚠️ Using hardcoded auth fallback.", e);
    }

    if (!firebase.apps.length) firebase.initializeApp(cfg);
    firebaseAuth = firebase.auth();

    // Listen for auth state changes
    firebaseAuth.onAuthStateChanged((user) => {
        if (user) {
            // Persist session info to localStorage so portal pages can use it
            const session = {
                id: user.uid,
                email: user.email,
                name: user.displayName || "",
                role: _role,
            };
            localStorage.setItem(SESSION_KEY, JSON.stringify(session));

            // Only redirect if we are on the LOGIN page
            if (_isLoginPage) {
                _redirectForRole();
            }
        } else {
            // User signed out — if on a protected page, go back to login
            if (_isPortalPage) {
                window.location.href = "login.html";
            }
        }
    });

    // Fire any waiting callbacks
    _firebaseReady = true;
    _firebaseReadyCallbacks.forEach((cb) => cb());
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */
function _saveSession(user, displayName) {
    const session = {
        id: user.uid,
        email: user.email,
        name: displayName || user.displayName || "",
        role: _role,
    };
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

function _redirectForRole() {
    if (_role === "manager") {
        window.location.replace("manager-dashboard.html");
    } else {
        window.location.replace("user-portal.html");
    }
}

/* ================================================================== */
/*  PUBLIC API — used by login.html forms                             */
/* ================================================================== */

/**
 * Toggle between Sign In / Sign Up forms (called from login.html).
 */
function switchMode(mode) {
    const loginForm = document.getElementById("login-form");
    const signupForm = document.getElementById("signup-form");
    const toggleLogin = document.getElementById("toggle-login");
    const toggleSignup = document.getElementById("toggle-signup");
    const title = document.getElementById("auth-title");
    const subtitle = document.getElementById("auth-subtitle");
    const errorEl = document.getElementById("auth-error");

    if (errorEl) {
        errorEl.style.display = "none";
        errorEl.textContent = "";
    }

    if (mode === "signup") {
        loginForm.classList.add("hidden");
        signupForm.classList.remove("hidden");
        toggleLogin.classList.remove("active");
        toggleSignup.classList.add("active");
        title.textContent = "Create Account";
        subtitle.textContent = "Sign up to get started";
    } else {
        signupForm.classList.add("hidden");
        loginForm.classList.remove("hidden");
        toggleSignup.classList.remove("active");
        toggleLogin.classList.add("active");
        title.textContent = "Welcome Back";
        subtitle.textContent = "Sign in to continue";
    }
}

/**
 * Handle form submission (called from login.html).
 */
async function handleAuth(event, mode) {
    event.preventDefault();

    if (!firebaseAuth) {
        _showAuthError("Firebase is still loading. Please wait a moment and try again.");
        return;
    }

    const errorEl = document.getElementById("auth-error");
    if (errorEl) errorEl.style.display = "none";

    try {
        if (mode === "login") {
            const email = document.getElementById("login-email").value.trim();
            const password = document.getElementById("login-password").value;
            const btn = document.getElementById("login-btn");
            btn.disabled = true;
            btn.textContent = "Signing in…";
            const cred = await firebaseAuth.signInWithEmailAndPassword(email, password);
            // Save session and redirect directly
            _saveSession(cred.user);
            _redirectForRole();
            return;
        } else {
            const name = document.getElementById("signup-name").value.trim();
            const email = document.getElementById("signup-email").value.trim();
            const password = document.getElementById("signup-password").value;
            const confirm = document.getElementById("signup-confirm").value;

            if (password !== confirm) {
                _showAuthError("Passwords do not match.");
                return;
            }

            const btn = document.getElementById("signup-btn");
            btn.disabled = true;
            btn.textContent = "Creating account…";

            const cred = await firebaseAuth.createUserWithEmailAndPassword(email, password);
            if (name) await cred.user.updateProfile({ displayName: name });
            // Save session and redirect directly
            _saveSession(cred.user, name);
            _redirectForRole();
            return;
        }
    } catch (err) {
        // Re-enable buttons
        const lb = document.getElementById("login-btn");
        const sb = document.getElementById("signup-btn");
        if (lb) { lb.disabled = false; lb.textContent = "Sign In"; }
        if (sb) { sb.disabled = false; sb.textContent = "Create Account"; }

        const msg = {
            "auth/user-not-found": "No account found with this email.",
            "auth/wrong-password": "Incorrect password.",
            "auth/invalid-credential": "Invalid email or password.",
            "auth/email-already-in-use": "An account with this email already exists.",
            "auth/weak-password": "Password should be at least 6 characters.",
            "auth/invalid-email": "Please enter a valid email address.",
            "auth/too-many-requests": "Too many attempts. Please try again later.",
        }[err.code] || err.message;

        _showAuthError(msg);
    }
}

function _showAuthError(msg) {
    const el = document.getElementById("auth-error");
    if (!el) return;
    el.textContent = msg;
    el.style.display = "block";
}

/* ================================================================== */
/*  PUBLIC API — used by portal / dashboard pages                     */
/* ================================================================== */

/**
 * Auth guard. Returns session object or null (and redirects to login).
 * @param {string} expectedRole — 'user' | 'manager' (informational)
 */
function requireAuth(expectedRole) {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) {
        window.location.href = `login.html?role=${expectedRole || "user"}`;
        return null;
    }
    try {
        return JSON.parse(raw);
    } catch {
        localStorage.removeItem(SESSION_KEY);
        window.location.href = `login.html?role=${expectedRole || "user"}`;
        return null;
    }
}

/**
 * Get the current session (no redirect).
 */
function getSession() {
    try {
        return JSON.parse(localStorage.getItem(SESSION_KEY)) || {};
    } catch {
        return {};
    }
}

/**
 * Sign out and redirect to login page.
 */
function logout() {
    localStorage.removeItem(SESSION_KEY);
    if (firebaseAuth) {
        firebaseAuth.signOut().finally(() => {
            window.location.href = "login.html";
        });
    } else {
        window.location.href = "login.html";
    }
}

/**
 * Generate a short unique ID (for incidents / alerts).
 */
function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}
