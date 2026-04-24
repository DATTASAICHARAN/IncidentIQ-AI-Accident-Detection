/**
 * RescueLink — SOS Emergency Alert
 * Saves a new document to the `emergency_alerts` Firestore collection
 * when the user presses the SOS button.
 *
 * Stored fields:
 *   - latitude / longitude  (live GPS)
 *   - bloodGroup            (user-selected)
 *   - triggeredBy           (user name / email from session)
 *   - status                ("active")
 *   - createdAt             (server-side Firestore timestamp)
 */

import { db } from "./firebase-config.js";
import {
    collection,
    addDoc,
    serverTimestamp,
} from "https://www.gstatic.com/firebasejs/11.4.0/firebase-firestore.js";

const ALERTS_COLLECTION = "emergency_alerts";

/**
 * Get the device's current GPS coordinates.
 * @returns {Promise<{latitude: number, longitude: number}>}
 */
function getCurrentPosition() {
    return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject(new Error("Geolocation is not supported by this browser."));
            return;
        }
        navigator.geolocation.getCurrentPosition(
            (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
            (err) => reject(new Error("Location access denied: " + err.message)),
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
    });
}

/**
 * Trigger an SOS emergency alert.
 * Fetches live GPS, then writes a new document to `emergency_alerts`.
 *
 * @param {string} bloodGroup  - Blood group string, e.g. "A+", "O-"
 * @param {string} triggeredBy - Display name or email of the user
 * @returns {Promise<string>}  - The Firestore document ID of the new alert
 */
export async function triggerSosAlert({ bloodGroup = "Unknown", triggeredBy = "anonymous" } = {}) {
    // 1. Get live GPS
    const { latitude, longitude } = await getCurrentPosition();

    // 2. Write alert to Firestore
    const docRef = await addDoc(collection(db, ALERTS_COLLECTION), {
        latitude,
        longitude,
        bloodGroup,
        triggeredBy,
        status: "active",
        createdAt: serverTimestamp(),
    });

    console.log(`[RescueLink] 🆘 SOS alert saved! Doc ID: ${docRef.id}`, {
        latitude,
        longitude,
        bloodGroup,
        triggeredBy,
    });

    return docRef.id;
}
