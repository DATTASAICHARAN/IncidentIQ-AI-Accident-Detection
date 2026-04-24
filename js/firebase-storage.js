/**
 * IncidentIQ — Firebase Cloud Storage Utilities
 * Upload accident photos and retrieve download URLs.
 *
 * Usage:
 *   import { uploadAccidentImage } from './firebase-storage.js';
 *   const url = await uploadAccidentImage(fileInput.files[0]);
 */

import { storage } from "./firebase-config.js";
import {
    ref,
    uploadBytes,
    getDownloadURL,
} from "https://www.gstatic.com/firebasejs/11.4.0/firebase-storage.js";

/**
 * Upload an image file to Firebase Cloud Storage and return its download URL.
 * Files are stored under: accident-photos/{timestamp}_{originalFilename}
 *
 * @param {File} file — a File object (e.g. from an <input type="file">)
 * @returns {Promise<string>} The public download URL
 */
export async function uploadAccidentImage(file) {
    const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
    const path = `accident-photos/${Date.now()}_${safeName}`;
    const storageRef = ref(storage, path);

    const snapshot = await uploadBytes(storageRef, file);
    const downloadURL = await getDownloadURL(snapshot.ref);

    return downloadURL;
}
