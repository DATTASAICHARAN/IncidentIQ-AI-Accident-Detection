/**
 * IncidentIQ — Firestore Database Utilities
 * CRUD helpers for the "accidentReports" collection.
 *
 * Usage:
 *   import { pushAccidentReport, fetchActiveReports, updateReportStatus }
 *     from './firebase-db.js';
 */

import { db } from "./firebase-config.js";
import {
    collection,
    addDoc,
    getDocs,
    doc,
    updateDoc,
    query,
    orderBy,
    where,
    serverTimestamp,
} from "https://www.gstatic.com/firebasejs/11.4.0/firebase-firestore.js";

const REPORTS_COLLECTION = "accidentReports";

/**
 * Push a new accident report to Firestore.
 * @param {Object} report
 * @param {number}  report.latitude
 * @param {number}  report.longitude
 * @param {string}  [report.description]
 * @param {string}  [report.imageUrl]      — download URL from Storage
 * @param {string}  [report.reportedBy]    — user display name or UID
 * @param {string}  [report.detectionType] — e.g. "Vehicle Collision"
 * @param {number}  [report.confidence]    — raw confidence %
 * @returns {Promise<string>} The auto-generated document ID
 */
export async function pushAccidentReport({
    latitude,
    longitude,
    description = "",
    imageUrl = "",
    reportedBy = "anonymous",
    detectionType = "",
    confidence = 0,
} = {}) {
    const docRef = await addDoc(collection(db, REPORTS_COLLECTION), {
        latitude,
        longitude,
        description,
        imageUrl,
        reportedBy,
        detectionType,
        confidence,
        status: "active",
        createdAt: serverTimestamp(),
    });
    return docRef.id;
}

/**
 * Fetch all active accident reports, newest first.
 * @returns {Promise<Array<Object>>}
 */
export async function fetchActiveReports() {
    const q = query(
        collection(db, REPORTS_COLLECTION),
        where("status", "==", "active"),
        orderBy("createdAt", "desc")
    );

    const snapshot = await getDocs(q);
    return snapshot.docs.map((d) => ({
        id: d.id,
        ...d.data(),
        // Convert Firestore Timestamp to JS Date string for convenience
        createdAt: d.data().createdAt?.toDate?.()?.toISOString() ?? null,
    }));
}

/**
 * Update the status of an existing report.
 * @param {string} reportId — Firestore document ID
 * @param {string} status   — e.g. "resolved", "dismissed", "active"
 * @returns {Promise<void>}
 */
export async function updateReportStatus(reportId, status) {
    const docRef = doc(db, REPORTS_COLLECTION, reportId);
    await updateDoc(docRef, { status });
}
