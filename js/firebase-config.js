/**
 * IncidentIQ — Firebase Configuration
 * Initializes the Firebase app and exports shared service instances.
 * 
 * Usage (from other ES modules):
 *   import { auth, db, storage } from './firebase-config.js';
 */

import { initializeApp } from "https://www.gstatic.com/firebasejs/11.4.0/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/11.4.0/firebase-auth.js";
import { getFirestore } from "https://www.gstatic.com/firebasejs/11.4.0/firebase-firestore.js";
import { getStorage } from "https://www.gstatic.com/firebasejs/11.4.0/firebase-storage.js";

// Fetch config from backend or fallback to hardcoded (for static hosting)
// RescueLink — chesss-app Firebase project
let firebaseConfig = {
    apiKey: "AIzaSyBCI0Kf34eiekipXbpkFG7jGP6UKMelIUw",
    authDomain: "chesss-app.firebaseapp.com",
    projectId: "chesss-app",
    storageBucket: "chesss-app.firebasestorage.app",
    messagingSenderId: "295776997074",
    appId: "1:295776997074:web:96ccdd4b347b441cf6270b",
    measurementId: "G-9MSSN82XPW"
};

try {
    const response = await fetch('/api/config');
    if (response.ok) {
        const remoteConfig = await response.json();
        // Only override if the remote config is actually populated
        if (remoteConfig.apiKey) {
            firebaseConfig = remoteConfig;
            console.log("[IncidentIQ] 🔥 Firebase config loaded from backend .env");
        }
    }
} catch (e) {
    console.warn("[IncidentIQ] ⚠️ Could not fetch config from backend, using hardcoded fallback.", e);
}

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);
const storage = getStorage(app);

export { app, auth, db, storage };
