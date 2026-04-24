/* =============================================================================
   cctv-alerts.js — IncidentIQ Real-time CCTV Alert System
   Connects to Flask-SocketIO, listens for live accident alerts from
   cctv_watcher.py, and renders dispatcher action cards.
   ============================================================================= */

const BACKEND_URL = 'http://localhost:5001';

// Tracks dispatched alert IDs so we can update them from `ambulance_dispatched` events
const _dispatchedAlerts = new Set();

/* ── Socket.IO Connection ─────────────────────────────────────────────────── */
let cctvSocket = null;

function initCCTVAlerts() {
    if (typeof io === 'undefined') {
        console.warn('[cctv-alerts] Socket.IO not loaded. CCTV alerts inactive.');
        updateCCTVConnectionBadge('error', 'Socket.IO not loaded');
        return;
    }

    cctvSocket = io(BACKEND_URL, {
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionDelay: 2000,
    });

    cctvSocket.on('connect', () => {
        console.log('[cctv-alerts] ✅ Connected to IncidentIQ WebSocket');
        updateCCTVConnectionBadge('online', 'Live — waiting for CCTV alerts');
    });

    cctvSocket.on('disconnect', (reason) => {
        console.warn('[cctv-alerts] ⚠️  Disconnected:', reason);
        updateCCTVConnectionBadge('offline', 'Disconnected — reconnecting…');
    });

    cctvSocket.on('connect_error', () => {
        updateCCTVConnectionBadge('error', 'Cannot reach server — start server.py');
    });

    // ── Core event: new CCTV accident detected ──────────────────────────────
    cctvSocket.on('cctv_alert', (payload) => {
        console.log('[cctv-alerts] 🚨 New CCTV alert received:', payload);
        renderCCTVAlertCard(payload);
        playCCTVAlertSound();
        bumpCCTVBadgeCount(1);
        // Also flash the sidebar badge
        flashSidebarBadge('cctv');
    });

    // ── Bidirectional event: ambulance was confirmed & dispatched ───────────
    cctvSocket.on('ambulance_dispatched', (payload) => {
        console.log('[cctv-alerts] 🚑 Ambulance dispatched event:', payload);
        _dispatchedAlerts.add(payload.alertId);
        markCardDispatched(payload.alertId);
    });
}


/* ── Connection Status Badge ─────────────────────────────────────────────── */
function updateCCTVConnectionBadge(status, text) {
    const dot = document.getElementById('cctv-ws-dot');
    const span = document.getElementById('cctv-ws-text');
    if (!dot || !span) return;

    const colors = { online: '#22C55E', offline: '#F59E0B', error: '#EF4444' };
    dot.style.background = colors[status] || '#94A3B8';
    span.textContent = text;
    span.style.color = status === 'online' ? '#166534' : '#B91C1C';
}


/* ── Render Alert Card ───────────────────────────────────────────────────── */
function renderCCTVAlertCard(alert) {
    const container = document.getElementById('cctv-live-alerts');
    if (!container) return;

    // Remove empty-state placeholder if present
    const empty = document.getElementById('cctv-empty-state');
    if (empty) empty.remove();

    const ts = new Date(alert.timestamp).toLocaleString();
    const mapsUrl = `https://www.google.com/maps?q=${alert.latitude},${alert.longitude}`;
    const alertId = alert.alertId;

    const snapshotHTML = alert.snapshotUrl
        ? `<div class="cctv-card__snapshot">
             <img src="${alert.snapshotUrl}"
                  alt="CCTV Snapshot — ${alert.cameraLabel || alert.cameraId}"
                  class="cctv-card__img"
                  onerror="this.style.display='none';this.nextElementSibling.style.display='block'"
             />
             <div class="cctv-card__no-img" style="display:none">
               📷 Snapshot unavailable
             </div>
             <p class="cctv-card__img-caption">
               📸 AI-annotated CCTV frame — click to expand
             </p>
           </div>`
        : `<div class="cctv-card__no-img">📷 No snapshot available</div>`;

    const card = document.createElement('div');
    card.className = 'cctv-alert-card';
    card.id = `cctv-card-${alertId}`;
    card.setAttribute('data-alert-id', alertId);
    card.setAttribute('data-lat', alert.latitude || 0);
    card.setAttribute('data-lng', alert.longitude || 0);
    card.setAttribute('data-type', alert.detectionType || 'Accident');
    card.setAttribute('data-conf', alert.confidence || 0);

    card.innerHTML = `
      <!-- Pulsing header bar -->
      <div class="cctv-card__header">
        <div class="cctv-card__header-left">
          <span class="cctv-live-badge">🔴 LIVE CCTV</span>
          <span class="cctv-card__camera">${alert.cameraLabel || alert.cameraId}</span>
        </div>
        <button class="cctv-card__dismiss"
                onclick="dismissCCTVCard('${alertId}')"
                title="Dismiss (mark as false alarm)">✕</button>
      </div>

      <!-- Alert details -->
      <div class="cctv-card__body">
        <div class="cctv-card__type">🚨 ${alert.detectionType}</div>
        <div class="cctv-card__meta">
          <span>📍 ${alert.cameraLabel || alert.location}</span>
          <span>🕐 ${ts}</span>
          <span>📊 Confidence: <strong>${alert.confidence}%</strong></span>
          <span>📡 Camera ID: ${alert.cameraId}</span>
        </div>

        <!-- Snapshot image -->
        ${snapshotHTML}

        <!-- Action buttons -->
        <div class="cctv-card__actions" id="cctv-actions-${alertId}">
          <button class="cctv-btn-dispatch"
                  id="cctv-dispatch-btn-${alertId}"
                  onclick="confirmAndDispatchAmbulance('${alertId}', this)">
            <span class="cctv-btn-icon">🚑</span>
            Confirm &amp; Dispatch Ambulance
          </button>
          <a href="${mapsUrl}" target="_blank" rel="noopener" class="cctv-btn-map">
            🗺️ View on Map
          </a>
          <button class="cctv-btn-false-alarm"
                  onclick="dismissCCTVCard('${alertId}')">
            ❌ False Alarm
          </button>
        </div>

        <!-- Dispatched state (hidden until confirmed) -->
        <div class="cctv-dispatched-badge hidden" id="cctv-dispatched-${alertId}">
          🚑 Ambulance Dispatched — Emergency Services Notified
        </div>
      </div>
    `;

    // Attach snapshot click-to-expand
    container.prepend(card);
    card.querySelector('.cctv-card__img')?.addEventListener('click', () => {
        openSnapshotModal(alert.snapshotUrl);
    });

    // Scroll into view
    container.scrollTo({ top: 0, behavior: 'smooth' });
}


/* ── Dispatch Button Handler ─────────────────────────────────────────────── */
async function confirmAndDispatchAmbulance(alertId, btnEl) {
    if (!confirm('⚠️ Confirm: dispatch an ambulance to this location?\n\nThis will notify emergency services.')) {
        return;
    }

    const card = document.getElementById(`cctv-card-${alertId}`);
    const payload = buildDispatchPayload(alertId);

    // Optimistic UI
    btnEl.disabled = true;
    btnEl.innerHTML = '⏳ Dispatching…';

    try {
        const resp = await fetch(`${BACKEND_URL}/api/dispatch-ambulance`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        const result = await resp.json();

        if (resp.ok && result.success) {
            markCardDispatched(alertId);
            showToast('🚑 Ambulance dispatched! Emergency services notified.', 'success');
            console.log('[cctv-alerts] Dispatch confirmed. Mock Twilio/SendGrid logged on server.');
        } else {
            throw new Error(result.error || 'Dispatch failed');
        }
    } catch (err) {
        console.error('[cctv-alerts] Dispatch error:', err);
        // Graceful fallback: still mark locally
        markCardDispatched(alertId);
        showToast('🚑 Dispatch logged locally (server unreachable — check console)', 'info');
    }
}


/* ── Build Dispatch Payload from Card Dataset ─────────────────────────────── */
function buildDispatchPayload(alertId) {
    const card = document.getElementById(`cctv-card-${alertId}`);

    // Read real GPS from data attributes stored at card creation time
    const lat = parseFloat(card?.getAttribute('data-lat') || 0);
    const lng = parseFloat(card?.getAttribute('data-lng') || 0);
    const detType = card?.getAttribute('data-type') ||
        card?.querySelector('.cctv-card__type')?.textContent?.replace('🚨 ', '').trim() ||
        'Accident';
    const cameraLabel = card?.querySelector('.cctv-card__camera')?.textContent?.trim() || 'UNKNOWN';

    return {
        alertId,
        cameraId: cameraLabel,
        cameraLabel: cameraLabel,
        timestamp: new Date().toISOString(),
        detectionType: detType,
        latitude: lat,
        longitude: lng,
        mapsUrl: `https://www.google.com/maps?q=${lat},${lng}`,
    };
}


/* ── Mark Card as Dispatched ─────────────────────────────────────────────── */
function markCardDispatched(alertId) {
    const actionsDiv = document.getElementById(`cctv-actions-${alertId}`);
    const dispatchedEl = document.getElementById(`cctv-dispatched-${alertId}`);
    const card = document.getElementById(`cctv-card-${alertId}`);

    if (actionsDiv) actionsDiv.style.display = 'none';
    if (dispatchedEl) dispatchedEl.classList.remove('hidden');
    if (card) card.classList.add('cctv-alert-card--dispatched');
}


/* ── Dismiss (False Alarm) ───────────────────────────────────────────────── */
function dismissCCTVCard(alertId) {
    const card = document.getElementById(`cctv-card-${alertId}`);
    if (!card) return;

    card.style.opacity = '0';
    card.style.transform = 'translateX(40px)';
    setTimeout(() => {
        card.remove();
        checkCCTVEmpty();
    }, 300);

    // Decrement badge
    bumpCCTVBadgeCount(-1);
    showToast('Alert dismissed — marked as false alarm', 'info');
}


/* ── Empty State ─────────────────────────────────────────────────────────── */
function checkCCTVEmpty() {
    const container = document.getElementById('cctv-live-alerts');
    if (!container) return;
    const cards = container.querySelectorAll('.cctv-alert-card');
    if (cards.length === 0) {
        const empty = document.createElement('div');
        empty.id = 'cctv-empty-state';
        empty.className = 'cctv-empty-state';
        empty.innerHTML = `
          <div class="empty-state__icon">🎥</div>
          <p class="empty-state__text">
            No live CCTV alerts.<br>
            <span style="font-size:0.82rem;opacity:0.7;">
              Alerts appear instantly when <code>cctv_watcher.py</code> detects an accident.
            </span>
          </p>
        `;
        container.appendChild(empty);
    }
}


/* ── Sidebar Badge Counter ───────────────────────────────────────────────── */
let _cctvAlertCount = 0;

function bumpCCTVBadgeCount(delta) {
    _cctvAlertCount = Math.max(0, _cctvAlertCount + delta);
    const badge = document.getElementById('cctv-nav-badge');
    if (!badge) return;
    if (_cctvAlertCount > 0) {
        badge.textContent = _cctvAlertCount;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

function flashSidebarBadge(section) {
    const link = document.querySelector(`.sidebar__link[data-section="${section}"]`);
    if (!link) return;
    link.classList.add('sidebar__link--alert');
    setTimeout(() => link.classList.remove('sidebar__link--alert'), 4000);
}


/* ── Alert Sound (Web Audio API — no external files) ─────────────────────── */
function playCCTVAlertSound() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();

        // Three descending beeps
        [880, 660, 440].forEach((freq, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = 'sine';
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0.18, ctx.currentTime + i * 0.18);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.18 + 0.15);
            osc.start(ctx.currentTime + i * 0.18);
            osc.stop(ctx.currentTime + i * 0.18 + 0.15);
        });
    } catch (_) {
        // Audio not supported or blocked — silent fallback
    }
}


/* ── Boot ────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    // Slight delay so socket.io CDN has time to parse
    setTimeout(initCCTVAlerts, 200);
    checkCCTVEmpty();
});
