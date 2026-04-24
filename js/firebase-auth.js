/**
 * IncidentIQ — Firebase Authentication Utilities
 * Provides register, login, logout, and auth-state helpers.
 *
 * Usage:
 *   import { registerUser, loginUser, logoutUser, onAuthChange, getCurrentUser }
 *     from './firebase-auth.js';
 */

import { auth } from "./firebase-config.js";
import {
    createUserWithEmailAndPassword,
    signInWithEmailAndPassword,
    signOut,
    onAuthStateChanged,
    updateProfile,
} from "https://www.gstatic.com/firebasejs/11.4.0/firebase-auth.js";

/**
 * Register a new user with email + password, then set their display name.
 * @param {string} email
 * @param {string} password
 * @param {string} displayName
 * @returns {Promise<import("firebase/auth").UserCredential>}
 */
export async function registerUser(email, password, displayName) {
    const credential = await createUserWithEmailAndPassword(auth, email, password);
    if (displayName) {
        await updateProfile(credential.user, { displayName });
    }
    return credential;
}

/**
 * Sign in an existing user.
 * @param {string} email
 * @param {string} password
 * @returns {Promise<import("firebase/auth").UserCredential>}
 */
export async function loginUser(email, password) {
    return signInWithEmailAndPassword(auth, email, password);
}

/**
 * Sign out the current user.
 * @returns {Promise<void>}
 */
export async function logoutUser() {
    return signOut(auth);
}

/**
 * Subscribe to auth-state changes.
 * @param {(user: import("firebase/auth").User | null) => void} callback
 * @returns {import("firebase/auth").Unsubscribe}
 */
export function onAuthChange(callback) {
    return onAuthStateChanged(auth, callback);
}

/**
 * Get the currently signed-in user (or null).
 * @returns {import("firebase/auth").User | null}
 */
export function getCurrentUser() {
    return auth.currentUser;
}
