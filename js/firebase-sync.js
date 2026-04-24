/**
 * IncidentIQ — Firebase Sync Layer
 * Silently uploads videos to Firebase Storage and syncs reports/alerts to Firestore,
 * keyed by the signed-in user's email.
 *
 * Loaded as <script type="module"> — does NOT alter any existing UI, routing, or logic.
 */

import { db, storage } from "./firebase-config.js";
import {
    doc,
    setDoc,
    collection,
    addDoc,
    serverTimestamp,
} from "https://www.gstatic.com/firebasejs/11.4.0/firebase-firestore.js";
import {
    ref,
    uploadBytes,
    getDownloadURL,
} from "https://www.gstatic.com/firebasejs/11.4.0/firebase-storage.js";

// ── Helpers ────────────────────────────────────────────────────────────────

const SESSION_KEY = "iq_session";

/** Sanitise email for use as a Firestore document key (no dots allowed). */
function sanitizeEmail(email) {
    return email.replace(/\./g, ",");
}

/** Read session from localStorage (same key used by auth.js). */
function getSessionEmail() {
    try {
        const session = JSON.parse(localStorage.getItem(SESSION_KEY) || "{}");
        return session.email || null;
    } catch {
        return null;
    }
}

/** Read session display-name. */
function getSessionName() {
    try {
        const session = JSON.parse(localStorage.getItem(SESSION_KEY) || "{}");
        return session.name || session.email || "anonymous";
    } catch {
        return "anonymous";
    }
}

// ── 1. User Profile Sync ───────────────────────────────────────────────────

async function syncUserProfile() {
    const email = getSessionEmail();
    if (!email) return;

    const key = sanitizeEmail(email);
    try {
        await setDoc(
            doc(db, "users", key),
            {
                email: email,
                displayName: getSessionName(),
                lastLogin: serverTimestamp(),
            },
            { merge: true }
        );
        console.log("[FirebaseSync] ✅ User profile synced:", email);
    } catch (err) {
        console.warn("[FirebaseSync] ⚠️ Profile sync failed:", err.message);
    }
}

// Run immediately on module load
syncUserProfile();

// ── 2. Report Sync — upload videos + write report to Firestore ─────────────

/** Track which incident IDs we have already synced. */
const syncedReportIds = new Set();

/** Upload a base64 data-URL file to Firebase Storage, return download URL. */
async function uploadDataUrlToStorage(dataUrl, fileName, userKey) {
    const response = await fetch(dataUrl);
    const blob = await response.blob();
    const safeName = fileName.replace(/[^a-zA-Z0-9._-]/g, "_");
    const path = `users/${userKey}/videos/${Date.now()}_${safeName}`;
    const storageRef = ref(storage, path);
    const snapshot = await uploadBytes(storageRef, blob);
    return getDownloadURL(snapshot.ref);
}

async function syncReports() {
    const email = getSessionEmail();
    if (!email) return;

    const key = sanitizeEmail(email);
    const incidents = JSON.parse(localStorage.getItem("iq_incidents") || "[]");
    const media = JSON.parse(localStorage.getItem("iq_media") || "[]");

    for (const incident of incidents) {
        if (syncedReportIds.has(incident.id)) continue;
        syncedReportIds.add(incident.id); // mark early to prevent duplicates

        try {
            // Find media items belonging to this incident
            const incidentMedia = media.filter(
                (m) => m.incidentId === incident.id
            );

            // Upload video/image files to Firebase Storage
            const videoUrls = [];
            for (const item of incidentMedia) {
                if (item.data) {
                    try {
                        const url = await uploadDataUrlToStorage(
                            item.data,
                            item.name,
                            key
                        );
                        videoUrls.push({ name: item.name, url });
                        console.log(
                            `[FirebaseSync] 📤 Uploaded: ${item.name}`
                        );
                    } catch (uploadErr) {
                        console.warn(
                            `[FirebaseSync] ⚠️ Upload failed for ${item.name}:`,
                            uploadErr.message
                        );
                    }
                }
            }

            // Write report + video URLs to Firestore
            const reportRef = collection(db, "users", key, "reports");
            await addDoc(reportRef, {
                localId: incident.id,
                reporterId: incident.reporterId || "",
                reporterName: incident.reporterName || "",
                description: incident.description || "",
                latitude: incident.latitude,
                longitude: incident.longitude,
                mediaCount: incident.mediaCount || 0,
                mediaNames: incident.mediaNames || [],
                videoUrls: videoUrls,
                status: incident.status || "pending",
                localCreatedAt: incident.createdAt || null,
                syncedAt: serverTimestamp(),
            });

            console.log(
                `[FirebaseSync] ✅ Report synced: ${incident.id} (${videoUrls.length} files uploaded)`
            );
        } catch (err) {
            // Allow retry on next poll
            syncedReportIds.delete(incident.id);
            console.warn(
                `[FirebaseSync] ⚠️ Report sync failed for ${incident.id}:`,
                err.message
            );
        }
    }
}

// ── 3. Alert Sync — write YOLO detection alerts to Firestore ───────────────

const syncedAlertIds = new Set();

async function syncAlerts() {
    const email = getSessionEmail();
    if (!email) return;

    const key = sanitizeEmail(email);
    const alerts = JSON.parse(localStorage.getItem("iq_alerts") || "[]");

    for (const alert of alerts) {
        if (syncedAlertIds.has(alert.id)) continue;
        syncedAlertIds.add(alert.id);

        try {
            const alertRef = collection(db, "users", key, "alerts");
            await addDoc(alertRef, {
                localId: alert.id,
                location: alert.location || "",
                latitude: alert.latitude || 0,
                longitude: alert.longitude || 0,
                detectionType: alert.detectionType || "Accident",
                confidence: alert.confidence || "N/A",
                confidenceRaw: alert.confidenceRaw || 0,
                hospitalStatus: alert.hospitalStatus || "Pending",
                fileName: alert.fileName || "",
                framesProcessed: alert.framesProcessed || 0,
                localTimestamp: alert.timestamp || null,
                syncedAt: serverTimestamp(),
            });

            console.log(`[FirebaseSync] ✅ Alert synced: ${alert.id}`);
        } catch (err) {
            syncedAlertIds.delete(alert.id);
            console.warn(
                `[FirebaseSync] ⚠️ Alert sync failed for ${alert.id}:`,
                err.message
            );
        }
    }
}

// ── Polling Loop ───────────────────────────────────────────────────────────
// Poll localStorage every 5 seconds for new reports & alerts.
// This is the least-invasive way to detect new data without modifying
// any existing functions.

setInterval(() => {
    syncReports();
    syncAlerts();
}, 5000);

// Also run once immediately
syncReports();
syncAlerts();

console.log("[FirebaseSync] 🔄 Firebase sync layer active");
