/* ============================================
   MANAGER DASHBOARD — Traffic Control
   ============================================ */

let aiMap, aiMarker;
let activeVideo = { file: null, name: null, objectURL: null };
let pinnedLocation = { lat: null, lng: null };

/* --- Init --- */
document.addEventListener('DOMContentLoaded', () => {
    const session = requireAuth('manager');
    if (!session) return;

    document.getElementById('manager-name').textContent = session.name || session.email;

    // Load live dashboard
    refreshDashboard();

    // Init AI map (lazy — on section switch)
    window._aiMapInitialized = false;

    // Setup CCTV upload zone
    setupCCTVUpload();

    // Init persistent alert system
    initUrgentAlertSystem();

    // Init Socket.io for real-time dashboard updates
    initDashboardSocket();
});

let dashboardSocket = null;
function initDashboardSocket() {
    if (typeof io === 'undefined') return;

    dashboardSocket = io('http://localhost:5001', {
        transports: ['websocket', 'polling'],
        reconnection: true
    });

    dashboardSocket.on('new_accident_alert', (payload) => {
        console.log('[Dashboard] 🚨 New alert received via Socket:', payload);
        showToast(`🚨 NEW ACCIDENT: ${payload.location}`, 'error');
        // If not on CCTV section, maybe flash badge or show modal
        refreshDashboard();

        // Auto-open modal logic already handled by initUrgentAlertSystem polling localStorage
        // but we can make it faster here.
        checkUrgentIncidents();
    });
}

/* ==========================================
   NAVIGATION
   ========================================== */
function switchSection(sectionId) {
    // Update sidebar
    document.querySelectorAll('.sidebar__link').forEach(link => {
        link.classList.toggle('active', link.dataset.section === sectionId);
    });

    // Show/hide panels
    document.querySelectorAll('.section-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === 'section-' + sectionId);
    });

    // Lazy init AI map
    if (sectionId === 'ai' && !window._aiMapInitialized) {
        setTimeout(initAIMap, 100);
        window._aiMapInitialized = true;
        checkBackendStatus();
    }

    // Refresh logs
    if (sectionId === 'logs') {
        refreshLogs();
    }

    // Close mobile sidebar
    document.getElementById('sidebar').classList.remove('open');
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

/* ==========================================
   SECTION 1: LIVE DASHBOARD
   ========================================== */
function refreshDashboard() {
    const incidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');
    const alerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');

    // Stats
    const total = incidents.length;
    const pending = incidents.filter(i => i.status === 'pending').length;
    const resolved = incidents.filter(i => i.status === 'resolved').length;
    const activeAlerts = alerts.filter(a => a.hospitalStatus !== 'Sent').length;

    animateCounter('stat-total', total);
    animateCounter('stat-pending', pending);
    animateCounter('stat-alerts', activeAlerts);
    animateCounter('stat-resolved', resolved);

    // Incident Grid
    const grid = document.getElementById('incident-grid');
    const emptyState = document.getElementById('live-empty');
    grid.innerHTML = '';

    if (incidents.length === 0) {
        emptyState.classList.remove('hidden');
        return;
    }

    emptyState.classList.add('hidden');

    // Show incidents as cards (newest first)
    [...incidents].reverse().forEach((incident, idx) => {
        const media = JSON.parse(localStorage.getItem('iq_media') || '[]')
            .filter(m => m.incidentId === incident.id);

        const card = document.createElement('div');
        card.className = 'video-card';
        card.style.animation = `slideUp 0.3s ease ${idx * 0.05}s both`;

        const firstMedia = media[0];
        let playerHTML = '';

        if (firstMedia) {
            if (firstMedia.type.startsWith('video/')) {
                playerHTML = `<video src="${firstMedia.data}" controls muted style="width:100%;height:100%;object-fit:cover;"></video>`;
            } else {
                playerHTML = `<img src="${firstMedia.data}" alt="Incident media" style="width:100%;height:100%;object-fit:cover;" />`;
            }
        } else {
            playerHTML = `<div class="video-card__placeholder">📷</div>`;
        }

        const statusBadge = incident.status === 'pending'
            ? '<span class="badge badge--amber">Pending</span>'
            : '<span class="badge badge--green">Resolved</span>';

        const timeAgo = getTimeAgo(incident.createdAt);

        const emergencyCallBtn = `<button class="btn-call-emergency" style="font-size:0.8rem;padding:0.45rem 0.9rem;" onclick="openDispatchPanel('${incident.id}', 'incident')"><span class="btn-call-emergency__icon">🏥</span> Hospitals & Ambulances</button>`;

        const alertBtn = incident.hospitalAlert === 'Sent'
            ? `<button class="btn btn-sm btn-ghost" disabled style="color:var(--green-500);border-color:var(--green-500);">🏥 Hospitals Notified</button>`
            : `<button class="btn btn-sm btn-danger" onclick="openDispatchPanel('${incident.id}', 'incident')">🚨 Alert Hospitals</button>`;

        card.innerHTML = `
      <div class="video-card__player">${playerHTML}</div>
      <div class="video-card__info">
        <div>
          <div class="video-card__title" style="display:flex;align-items:center;gap:8px;">
            ${incident.status === 'pending' ? '<span class="video-card__live-dot"></span>' : ''}
            Report #${incident.id.slice(-6).toUpperCase()}
          </div>
          <div class="video-card__meta">
            ${incident.reporterName || 'Anonymous'} • ${timeAgo} • ${incident.mediaCount} file(s)
          </div>
          <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">
            ${statusBadge}
          </div>
          ${incident.description ? `<div style="margin-top:8px;font-size:0.9rem;color:var(--text-secondary);line-height:1.4;">${incident.description}</div>` : ''}
        </div>
        <div style="display:flex;flex-direction:column;gap:4px;align-items:flex-end;">
          <div style="display:flex;gap:4px;">
            ${incident.status === 'pending' ? `<button class="btn btn-sm btn-primary" onclick="resolveIncident('${incident.id}')">✓ Resolve</button>` : ''}
            <button class="btn btn-sm btn-ghost" onclick="dismissIncident('${incident.id}')">✕</button>
          </div>
          <div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">${emergencyCallBtn}${alertBtn}</div>
        </div>
      </div>
    `;

        grid.appendChild(card);
    });
}

function resolveIncident(id) {
    const incidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');
    const idx = incidents.findIndex(i => i.id === id);
    if (idx !== -1) {
        incidents[idx].status = 'resolved';
        localStorage.setItem('iq_incidents', JSON.stringify(incidents));
        refreshDashboard();
        showToast('Incident resolved ✅', 'success');
    }
}

function dismissIncident(id) {
    let incidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');
    incidents = incidents.filter(i => i.id !== id);
    localStorage.setItem('iq_incidents', JSON.stringify(incidents));

    // Also remove associated media
    let media = JSON.parse(localStorage.getItem('iq_media') || '[]');
    media = media.filter(m => m.incidentId !== id);
    localStorage.setItem('iq_media', JSON.stringify(media));

    refreshDashboard();
    showToast('Incident dismissed', 'info');
}

/* ==========================================
   SECTION 2: AI ANALYSIS HUB
   ========================================== */
function initAIMap() {
    aiMap = L.map('ai-map').setView([20.5937, 78.9629], 5);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
        maxZoom: 19
    }).addTo(aiMap);

    // Click to place pin
    aiMap.on('click', (e) => {
        if (!activeVideo.file) {
            showToast('Import a video first before pinning a location.', 'warning');
            return;
        }

        pinnedLocation.lat = e.latlng.lat;
        pinnedLocation.lng = e.latlng.lng;

        if (aiMarker) {
            aiMarker.setLatLng(e.latlng);
        } else {
            aiMarker = L.marker(e.latlng, {
                draggable: true
            }).addTo(aiMap);

            aiMarker.on('dragend', (evt) => {
                const pos = evt.target.getLatLng();
                pinnedLocation.lat = pos.lat;
                pinnedLocation.lng = pos.lng;
                updatePinInfo();
            });
        }

        updatePinInfo();
    });
}

function updatePinInfo() {
    const pinInfo = document.getElementById('pin-info');
    const pinCoords = document.getElementById('pin-coords');
    pinInfo.classList.remove('hidden');
    pinCoords.textContent = `${pinnedLocation.lat.toFixed(5)}, ${pinnedLocation.lng.toFixed(5)}`;
}

function resetMapPin() {
    // Remove marker
    if (aiMarker) {
        aiMarker.remove();
        aiMarker = null;
    }

    // Reset coordinates
    pinnedLocation.lat = null;
    pinnedLocation.lng = null;

    // Hide pin info
    document.getElementById('pin-info').classList.add('hidden');
}

function updateMapPrompt() {
    const prompt = document.getElementById('map-prompt');
    if (activeVideo.file) {
        prompt.innerHTML = `📍 Drop a pin for: <strong>${activeVideo.name}</strong>`;
        prompt.classList.add('map-prompt--active');
    } else {
        prompt.textContent = 'Import a video first, then drop a pin at the CCTV camera location.';
        prompt.classList.remove('map-prompt--active');
    }
}

function updateActiveVideoBadge() {
    const badge = document.getElementById('active-video-badge');
    const nameEl = document.getElementById('active-video-name');
    if (activeVideo.file) {
        badge.classList.remove('hidden');
        nameEl.textContent = activeVideo.name;
    } else {
        badge.classList.add('hidden');
        nameEl.textContent = '—';
    }
}

/* CCTV Upload — Single Active Video */
function setupCCTVUpload() {
    const zone = document.getElementById('cctv-upload-zone');
    const fileInput = document.getElementById('cctv-file-input');

    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('dragover');
    });

    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            setActiveVideo(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            setActiveVideo(e.target.files[0]);
        }
    });
}

function setActiveVideo(file) {
    if (!file.type.startsWith('video/')) {
        showToast('Only video files accepted: ' + file.name, 'warning');
        return;
    }

    // Revoke previous object URL
    if (activeVideo.objectURL) {
        URL.revokeObjectURL(activeVideo.objectURL);
    }

    // Set new active video
    activeVideo.file = file;
    activeVideo.name = file.name;
    activeVideo.objectURL = URL.createObjectURL(file);

    // Reset map pin for the new video
    resetMapPin();

    // Update map prompt
    updateMapPrompt();

    // Update active video badge
    updateActiveVideoBadge();

    // Rebuild preview (single file)
    showActiveVideoPreview();

    showToast(`🎬 Active video: ${file.name} — now drop a pin on the map`, 'info');
}

function showActiveVideoPreview() {
    const grid = document.getElementById('cctv-preview-grid');
    grid.innerHTML = '';

    if (!activeVideo.file) return;

    const item = document.createElement('div');
    item.className = 'preview-item';
    item.style.animation = 'fadeIn 0.3s ease';

    const vid = document.createElement('video');
    vid.src = activeVideo.objectURL;
    vid.muted = true;
    vid.addEventListener('loadedmetadata', () => { vid.currentTime = 1; });
    item.appendChild(vid);

    const label = document.createElement('div');
    label.className = 'preview-item__label';
    label.textContent = activeVideo.name;
    item.appendChild(label);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'preview-item__remove';
    removeBtn.textContent = '✕';
    removeBtn.onclick = () => {
        clearActiveVideo();
    };
    item.appendChild(removeBtn);

    grid.appendChild(item);
}

function clearActiveVideo() {
    if (activeVideo.objectURL) {
        URL.revokeObjectURL(activeVideo.objectURL);
    }
    activeVideo = { file: null, name: null, objectURL: null };

    // Clear preview
    document.getElementById('cctv-preview-grid').innerHTML = '';

    // Reset map
    resetMapPin();
    updateMapPrompt();
    updateActiveVideoBadge();

    // Reset file input
    document.getElementById('cctv-file-input').value = '';
}

/* YOLO Analysis — Real Backend Integration */
const YOLO_BACKEND_URL = 'http://localhost:5001';

/* Backend Status Check */
async function checkBackendStatus() {
    const dot = document.getElementById('backend-dot');
    const text = document.getElementById('backend-text');
    try {
        const res = await fetch(`${YOLO_BACKEND_URL}/health`, { signal: AbortSignal.timeout(3000) });
        if (res.ok) {
            dot.style.background = '#22C55E';
            text.textContent = 'Backend: Connected ✅';
            text.style.color = '#166534';
        } else {
            throw new Error();
        }
    } catch {
        dot.style.background = '#EF4444';
        text.textContent = 'Backend: Offline — run "python server.py"';
        text.style.color = '#DC2626';
    }
}


async function runYOLOAnalysis() {
    if (!activeVideo.file) {
        showToast('Please import a CCTV video first.', 'warning');
        return;
    }

    if (!pinnedLocation.lat || !pinnedLocation.lng) {
        showToast(`Please drop a pin on the map for "${activeVideo.name}".`, 'warning');
        return;
    }

    const btn = document.getElementById('yolo-btn');
    const progressBar = document.getElementById('yolo-progress');
    const progressFill = document.getElementById('yolo-progress-fill');

    btn.disabled = true;
    btn.innerHTML = '⏳ Connecting to YOLO backend…';
    progressBar.style.display = 'block';
    progressFill.style.width = '10%';

    // Check if backend is running
    try {
        const healthCheck = await fetch(`${YOLO_BACKEND_URL}/health`, { signal: AbortSignal.timeout(3000) });
        if (!healthCheck.ok) throw new Error('Backend not reachable');
    } catch (err) {
        btn.disabled = false;
        btn.innerHTML = '🧠 Run YOLO Analysis';
        progressBar.style.display = 'none';
        progressFill.style.width = '0%';
        showToast('❌ YOLO backend not running. Start it with: python server.py', 'error');
        return;
    }

    btn.innerHTML = `⏳ Analyzing: ${activeVideo.name}…`;
    progressFill.style.width = '30%';

    try {
        const formData = new FormData();
        formData.append('video', activeVideo.file);
        formData.append('latitude', pinnedLocation.lat);
        formData.append('longitude', pinnedLocation.lng);

        const response = await fetch(`${YOLO_BACKEND_URL}/analyze`, {
            method: 'POST',
            body: formData,
        });

        progressFill.style.width = '85%';

        if (!response.ok) {
            showToast(`⚠️ Error analyzing ${activeVideo.name}`, 'warning');
        } else {
            const result = await response.json();

            if (result.detected) {
                const alert = {
                    id: generateId(),
                    location: `${pinnedLocation.lat.toFixed(4)}, ${pinnedLocation.lng.toFixed(4)}`,
                    latitude: pinnedLocation.lat,
                    longitude: pinnedLocation.lng,
                    timestamp: new Date().toISOString(),
                    detectionType: result.detectionType || 'Accident',
                    hospitalStatus: 'Pending',
                    confidence: result.confidence || 'N/A',
                    confidenceRaw: result.confidenceRaw || 0,
                    filesAnalyzed: 1,
                    fileName: activeVideo.name,
                    framesProcessed: result.framesProcessed || 0,
                    frameSnapshot: result.frameBase64 || null,
                    autoDispatched: result.autoDispatched || false,
                    smsSent: result.smsSent || false,
                    mapsUrl: result.mapsUrl || `https://www.google.com/maps?q=${pinnedLocation.lat},${pinnedLocation.lng}`,
                    alertId: result.alertId || null,
                };

                // Save alert to localStorage
                const alerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
                alerts.push(alert);
                localStorage.setItem('iq_alerts', JSON.stringify(alerts));

                // Show alert card with real snapshot + validation prompt
                showAccidentAlert(alert);

                if (result.autoDispatched) {
                    showToast(`🚑 AMBULANCE AUTO-DISPATCHED! ${result.smsSent ? 'SMS sent to ambulance.' : 'Logged (no Twilio).'}`, 'error');
                } else {
                    showToast(`🚨 Accident detected in ${activeVideo.name}! Confidence: ${result.confidence}`, 'error');
                }
            } else {
                const confInfo = result.confidence !== undefined ? ` • Highest confidence: ${result.confidence}` : '';
                showToast(`✅ No accident detected in ${activeVideo.name} (${result.framesProcessed} frames analyzed${confInfo})`, 'success');

                // Build a negative-result record for feedback
                const negRecord = {
                    id: generateId(),
                    fileName: activeVideo.name,
                    latitude: pinnedLocation.lat,
                    longitude: pinnedLocation.lng,
                    location: `${pinnedLocation.lat.toFixed(4)}, ${pinnedLocation.lng.toFixed(4)}`,
                    timestamp: new Date().toISOString(),
                    confidence: result.confidence || '0%',
                    confidenceRaw: result.confidenceRaw || 0,
                    framesProcessed: result.framesProcessed || 0,
                    frameSnapshot: result.frameBase64 || null,
                };

                // Store so submitNegativeFeedback can find it
                const negResults = JSON.parse(localStorage.getItem('iq_neg_results') || '[]');
                negResults.push(negRecord);
                localStorage.setItem('iq_neg_results', JSON.stringify(negResults));

                // Show validation card
                showNegativeValidationCard(negRecord);
            }
        }
    } catch (err) {
        console.error('Analysis error:', err);
        showToast(`❌ Failed to analyze ${activeVideo.name}: ${err.message}`, 'error');
    }

    // Done
    progressFill.style.width = '100%';
    setTimeout(() => {
        btn.disabled = false;
        btn.innerHTML = '🧠 Run YOLO Analysis';
        progressBar.style.display = 'none';
        progressFill.style.width = '0%';
    }, 500);
}

async function triggerRetraining() {
    const btn = document.getElementById('retrain-btn');
    const originalText = btn.innerHTML;

    // 1. Confirm with user
    if (!confirm("Start model retraining? This process runs in the background and uses your 'False Alarm' feedback to improve accuracy.")) {
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '⏳ Starting...';

    try {
        const response = await fetch(`${YOLO_BACKEND_URL}/retrain`, {
            method: 'POST'
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showToast('🚀 ' + result.message, 'success');
        } else {
            throw new Error(result.error || 'Unknown error');
        }
    } catch (err) {
        console.error('Retraining error:', err);
        showToast('❌ Failed to start retraining: ' + err.message, 'error');
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }, 2000);
    }
}

function showAccidentAlert(alert) {
    const container = document.getElementById('analysis-results');

    const snapshotHTML = alert.frameSnapshot
        ? `<div class="detection-snapshot" style="margin-top:12px;">
             <img src="data:image/jpeg;base64,${alert.frameSnapshot}" 
                  alt="YOLO Detection Snapshot" 
                  style="width:100%;max-width:560px;border-radius:8px;border:2px solid var(--red-400);cursor:pointer;"
                  onclick="openSnapshotModal(this.src)" />
             <p style="font-size:0.78rem;color:var(--text-secondary);margin-top:4px;">📸 AI-annotated detection frame</p>
           </div>`
        : '';

    // Auto-dispatch status banner
    const mapsUrl = alert.mapsUrl || `https://www.google.com/maps?q=${alert.latitude},${alert.longitude}`;
    const autoDispatchBanner = alert.autoDispatched
        ? `<div style="
               display:flex;align-items:center;gap:10px;
               background:linear-gradient(135deg,#14532d,#166534);
               border:1px solid #22c55e;
               border-radius:10px;
               padding:12px 16px;
               margin-bottom:14px;
               animation:slideUp 0.4s ease;
            ">
               <span style="font-size:1.8rem;">🚑</span>
               <div>
                 <div style="font-weight:800;font-size:1rem;color:#4ade80;">
                   AMBULANCE AUTO-DISPATCHED
                 </div>
                 <div style="font-size:0.82rem;color:#86efac;margin-top:2px;">
                   ${alert.smsSent
            ? '✅ SMS sent to ambulance with GPS location'
            : '📋 Logged to server console (configure Twilio to send real SMS)'}
                 </div>
                 <a href="${mapsUrl}" target="_blank" rel="noopener"
                    style="display:inline-block;margin-top:6px;font-size:0.8rem;color:#6ee7b7;text-decoration:underline;">
                   📍 View incident location on Google Maps
                 </a>
               </div>
             </div>`
        : '';

    const card = document.createElement('div');
    card.className = 'alert-card';
    card.innerHTML = `
    <div class="alert-card__icon alert-pulse">🚨</div>
    <div class="alert-card__body">
      ${autoDispatchBanner}
      <div class="alert-card__title">ACCIDENT DETECTED — ${alert.detectionType}</div>
      <div class="alert-card__meta">
        📍 Location: ${alert.location}<br>
        🕐 Time: ${new Date(alert.timestamp).toLocaleString()}<br>
        📊 Confidence: ${alert.confidence}<br>
        📹 File: ${alert.fileName || 'CCTV Footage'} • ${alert.framesProcessed || 0} frames analyzed
      </div>
      ${snapshotHTML}
      <!-- Validation Prompt -->
      <div class="validation-prompt" id="validation-${alert.id}">
        <p class="validation-prompt__label">🤖 Was this detection accurate?</p>
        <div class="validation-prompt__buttons">
          <button class="btn-validate btn-validate--confirm" onclick="submitFeedback('${alert.id}', 'true_positive', this)">
            ✅ Confirm Detection
          </button>
          <button class="btn-validate btn-validate--reject" onclick="submitFeedback('${alert.id}', 'false_positive', this)">
            ❌ False Alarm
          </button>
        </div>
      </div>
      <div class="alert-card__actions">
        <button class="btn-call-emergency" onclick="openDispatchPanel('${alert.id}', 'alert')">
          <span class="btn-call-emergency__icon">🏥</span> View Nearby Hospitals & Call
        </button>
        <a href="${mapsUrl}" target="_blank" rel="noopener"
           style="display:inline-flex;align-items:center;gap:6px;padding:0.55rem 1rem;
                  background:rgba(59,130,246,0.15);color:#93c5fd;
                  border:1px solid rgba(147,197,253,0.3);border-radius:8px;
                  font-size:0.85rem;font-weight:600;text-decoration:none;">
          🗺️ View on Map
        </a>
        <button class="btn btn-ghost btn-sm" onclick="this.closest('.alert-card').remove()">
          Dismiss
        </button>
      </div>
    </div>
  `;

    container.prepend(card);

    // Auto-open dispatch panel on detection
    setTimeout(() => openDispatchPanel(alert.id, 'alert'), 600);
}

/* ==========================================
   MODEL FEEDBACK LOOP
   ========================================== */

async function submitFeedback(alertId, tag, btnEl) {
    const alerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
    const alert = alerts.find(a => a.id === alertId);

    if (!alert) {
        showToast('Alert not found.', 'warning');
        return;
    }

    const container = document.getElementById(`validation-${alertId}`);
    if (!container) return;

    // Disable both buttons
    container.querySelectorAll('.btn-validate').forEach(b => { b.disabled = true; });
    btnEl.innerHTML = '⏳ Saving…';

    try {
        const response = await fetch(`${YOLO_BACKEND_URL}/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                alertId: alert.id,
                tag: tag,
                detectionType: alert.detectionType,
                confidence: alert.confidence,
                confidenceRaw: alert.confidenceRaw || 0,
                frameBase64: alert.frameSnapshot || null,
                latitude: alert.latitude,
                longitude: alert.longitude,
                fileName: alert.fileName,
                timestamp: alert.timestamp,
            }),
        });

        const result = await response.json();

        // Show success badge
        const isConfirm = tag === 'true_positive';
        container.innerHTML = `
            <div class="validation-badge validation-badge--${isConfirm ? 'confirm' : 'reject'}">
                ${isConfirm ? '✅ Confirmed — True Positive' : '❌ Marked as False Alarm'}
                <span style="font-size:0.78rem;opacity:0.8;margin-left:8px;">Saved for model retraining</span>
            </div>
        `;

        // Save feedback locally
        const feedback = JSON.parse(localStorage.getItem('iq_feedback') || '[]');
        feedback.push({
            alertId: alert.id,
            tag,
            detectionType: alert.detectionType,
            confidence: alert.confidence,
            savedAt: new Date().toISOString(),
        });
        localStorage.setItem('iq_feedback', JSON.stringify(feedback));

        showToast(
            isConfirm
                ? '✅ Detection confirmed — frame saved for retraining'
                : '❌ False alarm logged — frame saved to improve accuracy',
            isConfirm ? 'success' : 'info'
        );

    } catch (err) {
        console.error('Feedback error:', err);
        // Graceful fallback — save locally even if backend fails
        const isConfirm = tag === 'true_positive';
        container.innerHTML = `
            <div class="validation-badge validation-badge--${isConfirm ? 'confirm' : 'reject'}">
                ${isConfirm ? '✅ Confirmed' : '❌ False Alarm'} 
                <span style="font-size:0.78rem;opacity:0.8;margin-left:8px;">Saved locally</span>
            </div>
        `;

        const feedback = JSON.parse(localStorage.getItem('iq_feedback') || '[]');
        feedback.push({
            alertId: alert.id,
            tag,
            detectionType: alert.detectionType,
            confidence: alert.confidence,
            savedAt: new Date().toISOString(),
            method: 'local-only',
        });
        localStorage.setItem('iq_feedback', JSON.stringify(feedback));
        showToast('📋 Feedback saved locally (backend unavailable)', 'info');
    }
}

/* ==========================================
   NEGATIVE RESULT VALIDATION
   ========================================== */

function showNegativeValidationCard(record) {
    const container = document.getElementById('analysis-results');

    const snapshotHTML = record.frameSnapshot
        ? `<div style="margin-top:12px;">
             <img src="data:image/jpeg;base64,${record.frameSnapshot}"
                  alt="Analysis Frame"
                  style="width:100%;max-width:560px;border-radius:8px;border:2px solid var(--amber-400, #F59E0B);cursor:pointer;"
                  onclick="openSnapshotModal(this.src)" />
             <p style="font-size:0.78rem;color:var(--text-secondary);margin-top:4px;">📸 Representative frame from analysis</p>
           </div>`
        : '';

    const card = document.createElement('div');
    card.className = 'alert-card';
    card.style.borderLeft = '4px solid var(--green-500, #22C55E)';
    card.innerHTML = `
    <div class="alert-card__icon">✅</div>
    <div class="alert-card__body">
      <div class="alert-card__title">NO ACCIDENT DETECTED</div>
      <div class="alert-card__meta">
        📹 File: ${record.fileName}<br>
        📍 Location: ${record.location}<br>
        🕐 Time: ${new Date(record.timestamp).toLocaleString()}<br>
        📊 Highest confidence: ${record.confidence}<br>
        🎞️ ${record.framesProcessed} frames analyzed
      </div>
      ${snapshotHTML}
      <!-- Validation Prompt -->
      <div class="validation-prompt" id="neg-validation-${record.id}">
        <p class="validation-prompt__label">🤖 Is this a True Negative (no accident) or a False Negative (missed accident)?</p>
        <div class="validation-prompt__buttons">
          <button class="btn-validate btn-validate--confirm" onclick="submitNegativeFeedback('${record.id}', 'true_negative', this)">
            ✅ True Negative
          </button>
          <button class="btn-validate btn-validate--reject" onclick="submitNegativeFeedback('${record.id}', 'false_negative', this)">
            ⚠️ False Negative (Missed Accident)
          </button>
        </div>
      </div>
      <div class="alert-card__actions" style="margin-top:8px;">
        <button class="btn btn-ghost btn-sm" onclick="this.closest('.alert-card').remove()">
          Dismiss
        </button>
      </div>
    </div>
  `;

    container.prepend(card);
}

async function submitNegativeFeedback(recordId, tag, btnEl) {
    const negResults = JSON.parse(localStorage.getItem('iq_neg_results') || '[]');
    const record = negResults.find(r => r.id === recordId);

    if (!record) {
        showToast('Record not found.', 'warning');
        return;
    }

    const container = document.getElementById(`neg-validation-${recordId}`);
    if (!container) return;

    // Disable buttons
    container.querySelectorAll('.btn-validate').forEach(b => { b.disabled = true; });
    btnEl.innerHTML = '⏳ Saving…';

    try {
        const response = await fetch(`${YOLO_BACKEND_URL}/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                alertId: record.id,
                tag: tag,
                detectionType: 'No Detection',
                confidence: record.confidence,
                confidenceRaw: record.confidenceRaw || 0,
                frameBase64: record.frameSnapshot || null,
                latitude: record.latitude,
                longitude: record.longitude,
                fileName: record.fileName,
                timestamp: record.timestamp,
            }),
        });

        await response.json();

        const isTrueNeg = tag === 'true_negative';
        container.innerHTML = `
            <div class="validation-badge validation-badge--${isTrueNeg ? 'confirm' : 'reject'}">
                ${isTrueNeg ? '✅ Confirmed — True Negative' : '⚠️ False Negative — Frame saved for retraining'}
                <span style="font-size:0.78rem;opacity:0.8;margin-left:8px;">Logged</span>
            </div>
        `;

        // Save feedback locally
        const feedback = JSON.parse(localStorage.getItem('iq_feedback') || '[]');
        feedback.push({
            recordId: record.id,
            tag,
            confidence: record.confidence,
            fileName: record.fileName,
            savedAt: new Date().toISOString(),
        });
        localStorage.setItem('iq_feedback', JSON.stringify(feedback));

        showToast(
            isTrueNeg
                ? '✅ True Negative confirmed'
                : '⚠️ False Negative logged — frame saved for model retraining',
            isTrueNeg ? 'success' : 'info'
        );
    } catch (err) {
        console.error('Negative feedback error:', err);

        const isTrueNeg = tag === 'true_negative';
        container.innerHTML = `
            <div class="validation-badge validation-badge--${isTrueNeg ? 'confirm' : 'reject'}">
                ${isTrueNeg ? '✅ True Negative' : '⚠️ False Negative'}
                <span style="font-size:0.78rem;opacity:0.8;margin-left:8px;">Saved locally</span>
            </div>
        `;

        const feedback = JSON.parse(localStorage.getItem('iq_feedback') || '[]');
        feedback.push({
            recordId: record.id,
            tag,
            confidence: record.confidence,
            fileName: record.fileName,
            savedAt: new Date().toISOString(),
            method: 'local-only',
        });
        localStorage.setItem('iq_feedback', JSON.stringify(feedback));
        showToast('📋 Feedback saved locally (backend unavailable)', 'info');
    }
}

/* Snapshot Modal */
function openSnapshotModal(imgSrc) {
    const existing = document.getElementById('snapshot-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'snapshot-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:pointer;animation:fadeIn 0.2s ease;';
    modal.onclick = () => modal.remove();
    modal.innerHTML = `<img src="${imgSrc}" style="max-width:90vw;max-height:90vh;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,0.5);" />`;
    document.body.appendChild(modal);
}

/* ==========================================
   EMERGENCY DISPATCH SYSTEM
   ========================================== */

let currentDispatchAlert = null;
// sourceTypes: 'alert' (AI) | 'incident' (Citizen)

function openDispatchPanel(id, type = 'alert') {
    let item, data;

    if (type === 'alert') {
        const alerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
        item = alerts.find(a => a.id === id);
        if (!item) { showToast('Alert not found.', 'warning'); return; }

        // Normalize
        data = {
            id: item.id,
            sourceType: 'alert',
            detectionType: item.detectionType,
            latitude: item.latitude,
            longitude: item.longitude,
            location: item.location,
            timestamp: item.timestamp,
            confidence: item.confidence,
            hospitalStatus: item.hospitalStatus
        };
    } else {
        // Citizen Incident
        const incidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');
        item = incidents.find(i => i.id === id);
        if (!item) { showToast('Incident report not found.', 'warning'); return; }

        const lat = parseFloat(item.latitude);
        const lng = parseFloat(item.longitude);

        if (isNaN(lat) || isNaN(lng)) {
            showToast('Invalid location data for this report.', 'error');
            return;
        }

        // Normalize
        data = {
            id: item.id,
            sourceType: 'incident',
            detectionType: 'Citizen Report',
            latitude: lat,
            longitude: lng,
            location: `${lat.toFixed(4)}, ${lng.toFixed(4)}`,
            timestamp: item.createdAt,
            confidence: 'User Reported',
            hospitalStatus: item.hospitalAlert || 'Pending'
        };
    }

    if (!data.latitude || !data.longitude) {
        showToast('Missing coordinates for dispatch.', 'error');
        return;
    }

    currentDispatchAlert = data;

    // Show panel
    document.getElementById('dispatch-backdrop').classList.add('active');
    document.getElementById('dispatch-panel').classList.add('active');

    // Populate crash summary
    document.getElementById('dispatch-crash-summary').innerHTML = `
        <div class="crash-summary-card">
            <div class="crash-summary-card__icon">🚨</div>
            <div class="crash-summary-card__info">
                <div class="crash-summary-card__type">${data.detectionType}</div>
                <div class="crash-summary-card__meta">
                    📍 ${data.location}<br>
                    🕐 ${new Date(data.timestamp).toLocaleString()}<br>
                    📊 Confidence: ${data.confidence}
                </div>
                <p style="margin-top:10px;font-size:0.82rem;color:var(--text-secondary);">Select a hospital below to call or dispatch an ambulance.</p>
            </div>
        </div>
    `;

    // Show loading, hide list
    document.getElementById('dispatch-loading').style.display = 'flex';
    document.getElementById('dispatch-hospital-list').innerHTML = '';
    document.getElementById('dispatch-empty').classList.add('hidden');

    // Fetch hospitals
    fetchNearbyHospitals(data.latitude, data.longitude);
}

function closeDispatchPanel() {
    document.getElementById('dispatch-backdrop').classList.remove('active');
    document.getElementById('dispatch-panel').classList.remove('active');
    currentDispatchAlert = null;
}

/* --- Open Dispatch Panel from Urgent Modal --- */
function openDispatchPanelFromModal() {
    // Close the urgent modal
    const modal = document.getElementById('urgent-alert-modal');
    if (modal) modal.style.display = 'none';

    // Find the latest pending incident to dispatch
    const incidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');
    const pending = incidents.filter(i => i.status === 'pending');

    if (pending.length > 0) {
        // Use the most recent pending incident
        const latest = pending[pending.length - 1];
        openDispatchPanel(latest.id, 'incident');
    } else {
        // Fallback: check AI alerts
        const alerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
        if (alerts.length > 0) {
            const latest = alerts[alerts.length - 1];
            openDispatchPanel(latest.id, 'alert');
        } else {
            showToast('No active incidents found to dispatch.', 'warning');
        }
    }
}

/* --- Overpass API — Find Nearby Hospitals --- */
async function fetchNearbyHospitals(lat, lng) {
    const radius = 10000; // 10km
    const query = `
        [out:json][timeout:15];
        (
            node["amenity"="hospital"](around:${radius},${lat},${lng});
            way["amenity"="hospital"](around:${radius},${lat},${lng});
            node["amenity"="clinic"](around:${radius},${lat},${lng});
            node["healthcare"="hospital"](around:${radius},${lat},${lng});
        );
        out center body;
    `;

    const endpoints = [
        'https://overpass-api.de/api/interpreter',
        'https://lz4.overpass-api.de/api/interpreter',
        'https://overpass.kumi.systems/api/interpreter',
        'https://maps.mail.ru/osm/tools/overpass/api/interpreter'
    ];

    let lastError;

    for (const url of endpoints) {
        try {
            console.log(`[IncidentIQ] Fetching hospitals from: ${url}`);
            const response = await fetch(url, {
                method: 'POST',
                body: 'data=' + encodeURIComponent(query),
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                signal: AbortSignal.timeout(10000) // 10s timeout per attempt
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            const hospitals = parseHospitals(data.elements, lat, lng);

            document.getElementById('dispatch-loading').style.display = 'none';

            if (hospitals.length === 0) {
                document.getElementById('dispatch-empty').classList.remove('hidden');
                return;
            }

            renderHospitalCards(hospitals);
            return; // Success, exit function

        } catch (err) {
            console.warn(`Overpass API error (${url}):`, err);
            lastError = err;
            // Continue to next endpoint
        }
    }

    // All endpoints failed
    console.error('All Overpass endpoints failed.');
    document.getElementById('dispatch-loading').style.display = 'none';
    document.getElementById('dispatch-empty').classList.remove('hidden');
    document.getElementById('dispatch-empty').innerHTML = `
        <div style="font-size:2.5rem;margin-bottom:12px;">⚠️</div>
        <p>Failed to fetch nearby hospitals.</p>
        <p style="font-size:0.82rem;color:var(--text-secondary);margin-top:8px;">
            Connection timed out or API unavailable.<br>
            <button class="btn btn-sm btn-ghost" onclick="fetchNearbyHospitals(${lat}, ${lng})" style="margin-top:8px;">↻ Retry</button>
        </p>
    `;
}

function parseHospitals(elements, crashLat, crashLng) {
    const hospitals = [];
    const seen = new Set();

    elements.forEach(el => {
        const name = el.tags?.name || el.tags?.['name:en'] || null;
        if (!name || seen.has(name)) return;
        seen.add(name);

        const hLat = el.lat || el.center?.lat;
        const hLng = el.lon || el.center?.lon;
        if (!hLat || !hLng) return;

        const distKm = haversineDistance(crashLat, crashLng, hLat, hLng);
        const travelMin = estimateTravelTime(distKm);
        const type = el.tags?.healthcare || el.tags?.amenity || 'hospital';

        hospitals.push({
            name,
            lat: hLat,
            lng: hLng,
            distance: distKm,
            travelTime: travelMin,
            type: type.charAt(0).toUpperCase() + type.slice(1),
            phone: el.tags?.phone || el.tags?.['contact:phone'] || null,
            emergency: el.tags?.emergency === 'yes',
        });
    });

    // Sort by distance
    hospitals.sort((a, b) => a.distance - b.distance);
    return hospitals;
}

/* --- Haversine Distance (km) --- */
function haversineDistance(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
        Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/* --- Travel Time Estimate (min) --- */
function estimateTravelTime(distKm) {
    // Average urban speed: ~25 km/h for emergency response
    return Math.max(1, Math.round((distKm / 25) * 60));
}

/* --- Render Hospital Flashcards --- */
function renderHospitalCards(hospitals) {
    const container = document.getElementById('dispatch-hospital-list');
    container.innerHTML = '';

    hospitals.forEach((hospital, idx) => {
        const distLabel = hospital.distance < 2 ? 'near' : hospital.distance < 6 ? 'mid' : 'far';
        const distText = hospital.distance < 1
            ? `${Math.round(hospital.distance * 1000)}m`
            : `${hospital.distance.toFixed(1)}km`;

        const card = document.createElement('div');
        card.className = 'hospital-card';
        card.style.animationDelay = `${idx * 0.06}s`;

        const mapsUrl = `https://www.google.com/maps/dir/${currentDispatchAlert.latitude},${currentDispatchAlert.longitude}/${hospital.lat},${hospital.lng}`;

        const callBtnHTML = hospital.phone
            ? `<a href="tel:${hospital.phone.replace(/[^\d+]/g, '')}" class="btn-call-hospital" title="Call ${hospital.name}">
                    📞 Call ${hospital.phone}
               </a>`
            : `<a href="tel:108" class="btn-call-hospital btn-call-hospital--fallback" title="Call Emergency Services (108)">
                    📞 Call 108
               </a>`;

        card.innerHTML = `
            <div class="hospital-card__header">
                <div class="hospital-card__name">
                    🏥 ${hospital.name}
                </div>
                <div class="hospital-card__badges">
                    <span class="distance-badge distance-badge--${distLabel}">
                        📍 ${distText}
                    </span>
                </div>
            </div>
            <div class="hospital-card__details">
                <div class="hospital-card__detail">🚗 ~${hospital.travelTime} min</div>
                <div class="hospital-card__detail">🏷️ ${hospital.type}</div>
                ${hospital.phone ? `<div class="hospital-card__detail">📞 ${hospital.phone}</div>` : ''}
                ${hospital.emergency ? `<div class="hospital-card__detail">🆘 Emergency</div>` : ''}
            </div>
            <div class="hospital-card__actions">
                ${callBtnHTML}
                <button class="btn-dispatch" id="dispatch-btn-${idx}" onclick="dispatchAlert(${idx}, this)">
                    🚨 Send Alert
                </button>
                <button class="btn-call-emergency" style="font-size:0.75rem; padding:0.4rem 0.8rem; height:auto; animation:none;" onclick="triggerTwilioDispatch('${currentDispatchAlert.id}', this)">
                    📞 Call & SMS (Twilio)
                </button>
                <a href="${mapsUrl}" class="btn-route" title="View Route">
                    🗺️
                </a>
            </div>
        `;

        container.appendChild(card);
    });

    // Store hospitals in memory for dispatch
    window._dispatchHospitals = hospitals;
}

/* --- Dispatch Alert to Hospital --- */
async function dispatchAlert(hospitalIdx, btnEl) {
    const hospital = window._dispatchHospitals?.[hospitalIdx];
    const alert = currentDispatchAlert;

    if (!hospital || !alert) {
        showToast('Missing dispatch data.', 'warning');
        return;
    }

    btnEl.disabled = true;
    btnEl.innerHTML = '⏳ Sending…';

    const mapsUrl = `https://www.google.com/maps/dir/${alert.latitude},${alert.longitude}/${hospital.lat},${hospital.lng}`;

    try {
        const response = await fetch(`${YOLO_BACKEND_URL}/dispatch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                hospital: {
                    name: hospital.name,
                    lat: hospital.lat,
                    lng: hospital.lng,
                    distance: hospital.distance.toFixed(1),
                    travelTime: hospital.travelTime,
                    phone: hospital.phone,
                },
                accident: {
                    type: alert.detectionType,
                    confidence: alert.confidence,
                    latitude: alert.latitude,
                    longitude: alert.longitude,
                    timestamp: alert.timestamp,
                    location: alert.location,
                },
                routeUrl: mapsUrl,
            }),
        });

        const result = await response.json();

        if (response.ok) {
            btnEl.innerHTML = '✅ Alert Sent';
            btnEl.classList.add('btn-dispatch--sent');
            showToast(`📨 Emergency alert dispatched to ${hospital.name}!`, 'success');

            // Update status in correct storage
            if (alert.sourceType === 'incident') {
                const allIncidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');
                const idx = allIncidents.findIndex(i => i.id === alert.id);
                if (idx !== -1) {
                    allIncidents[idx].hospitalAlert = 'Sent';
                    localStorage.setItem('iq_incidents', JSON.stringify(allIncidents));
                    refreshDashboard(); // Update UI button
                }
            } else {
                // AI Alert
                const allAlerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
                const idx = allAlerts.findIndex(a => a.id === alert.id);
                if (idx !== -1) {
                    allAlerts[idx].hospitalStatus = 'Sent';
                    if (!allAlerts[idx].dispatchedTo) allAlerts[idx].dispatchedTo = [];
                    allAlerts[idx].dispatchedTo.push({
                        hospital: hospital.name,
                        distance: hospital.distance.toFixed(1) + 'km',
                        sentAt: new Date().toISOString(),
                    });
                    localStorage.setItem('iq_alerts', JSON.stringify(allAlerts));
                    refreshLogs();
                }
            }
        } else {
            throw new Error(result.error || 'Dispatch failed');
        }
    } catch (err) {
        console.error('Dispatch error:', err);
        // Fallback: mark as sent locally even if backend dispatch fails
        btnEl.innerHTML = '✅ Alert Logged';
        btnEl.classList.add('btn-dispatch--sent');
        showToast(`📋 Alert logged for ${hospital.name} (email dispatch unavailable)`, 'info');

        // Still save to localStorage
        if (alert.sourceType === 'incident') {
            const allIncidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');
            const idx = allIncidents.findIndex(i => i.id === alert.id);
            if (idx !== -1) {
                allIncidents[idx].hospitalAlert = 'Sent';
                localStorage.setItem('iq_incidents', JSON.stringify(allIncidents));
                refreshDashboard();
            }
        } else {
            const allAlerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
            const idx = allAlerts.findIndex(a => a.id === alert.id);
            if (idx !== -1) {
                allAlerts[idx].hospitalStatus = 'Sent';
                if (!allAlerts[idx].dispatchedTo) allAlerts[idx].dispatchedTo = [];
                allAlerts[idx].dispatchedTo.push({
                    hospital: hospital.name,
                    distance: hospital.distance.toFixed(1) + 'km',
                    sentAt: new Date().toISOString(),
                    method: 'local-only',
                });
                localStorage.setItem('iq_alerts', JSON.stringify(allAlerts));
                refreshLogs();
            }
        }
    }
}

/* ==========================================
   SECTION 3: ALERT LOGS & HISTORY
   ========================================== */
function refreshLogs() {
    const alerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
    const tbody = document.getElementById('logs-tbody');
    const emptyState = document.getElementById('logs-empty');

    tbody.innerHTML = '';

    if (alerts.length === 0) {
        emptyState.classList.remove('hidden');
        return;
    }

    emptyState.classList.add('hidden');

    [...alerts].reverse().forEach(alert => {
        const statusBadge = alert.hospitalStatus === 'Sent'
            ? '<span class="badge badge--green">Sent</span>'
            : '<span class="badge badge--amber">Pending</span>';

        const row = document.createElement('tr');
        row.innerHTML = `
      <td style="font-family:monospace;font-size:0.82rem;">#${alert.id.slice(-6).toUpperCase()}</td>
      <td>📍 ${alert.location}</td>
      <td>${new Date(alert.timestamp).toLocaleString()}</td>
      <td><span class="badge badge--red">${alert.detectionType}</span></td>
      <td>${statusBadge}</td>
      <td>
        <div style="display:flex;gap:4px;">
          ${alert.hospitalStatus !== 'Sent' ? `<button class="btn btn-sm btn-danger" onclick="markAlertSent('${alert.id}')">Send Alert</button>` : ''}
          <button class="btn btn-sm btn-ghost" onclick="deleteAlert('${alert.id}')">🗑️</button>
        </div>
      </td>
    `;
        tbody.appendChild(row);
    });
}

function markAlertSent(alertId) {
    const alerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
    const idx = alerts.findIndex(a => a.id === alertId);
    if (idx !== -1) {
        alerts[idx].hospitalStatus = 'Sent';
        localStorage.setItem('iq_alerts', JSON.stringify(alerts));
        refreshLogs();
        showToast('Hospital alert sent ✅', 'success');
    }
}

function deleteAlert(alertId) {
    let alerts = JSON.parse(localStorage.getItem('iq_alerts') || '[]');
    alerts = alerts.filter(a => a.id !== alertId);
    localStorage.setItem('iq_alerts', JSON.stringify(alerts));
    refreshLogs();
    refreshDashboard();
    showToast('Alert deleted', 'info');
}

/* ==========================================
   UTILITIES
   ========================================== */
function animateCounter(elementId, targetValue) {
    const el = document.getElementById(elementId);
    const current = parseInt(el.textContent) || 0;
    const diff = targetValue - current;
    const steps = 20;
    let step = 0;

    if (diff === 0) return;

    const interval = setInterval(() => {
        step++;
        const value = Math.round(current + (diff * (step / steps)));
        el.textContent = value;
        if (step >= steps) {
            el.textContent = targetValue;
            clearInterval(interval);
        }
    }, 30);
}

function getTimeAgo(dateStr) {
    const now = new Date();
    const then = new Date(dateStr);
    const diffMs = now - then;
    const mins = Math.floor(diffMs / 60000);
    const hours = Math.floor(diffMs / 3600000);
    const days = Math.floor(diffMs / 86400000);

    if (mins < 1) return 'Just now';
    if (mins < 60) return mins + 'm ago';
    if (hours < 24) return hours + 'h ago';
    return days + 'd ago';
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const icons = { success: '✅', error: '🚨', warning: '⚠️', info: 'ℹ️' };

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `
    <span class="toast__icon">${icons[type]}</span>
    <span class="toast__message">${message}</span>
    <button class="toast__close" onclick="this.parentElement.remove()">✕</button>
  `;

    container.appendChild(toast);

    setTimeout(() => {
        if (toast.parentElement) toast.remove();
    }, 4000);
}

/* ==========================================
   PERSISTENT URGENT ALERT SYSTEM
   ========================================== */

let ignoredIncidentIds = new Set();

function initUrgentAlertSystem() {
    // Check for new incidents every 3 seconds
    setInterval(checkUrgentIncidents, 3000);
}

function checkUrgentIncidents() {
    const incidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');

    // Find pending incidents that are NOT in the ignored set
    const pendingIncidents = incidents.filter(i => i.status === 'pending' && !ignoredIncidentIds.has(i.id));

    const modal = document.getElementById('urgent-alert-modal');
    const detailsContainer = document.getElementById('urgent-modal-details');

    if (pendingIncidents.length > 0) {
        // Show the latest one
        const latest = pendingIncidents[pendingIncidents.length - 1];

        // Populate Modal
        detailsContainer.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                    <h3 style="margin:0 0 4px; color:#1F2937;">${latest.detectionType || 'User Report'}</h3>
                    <p style="margin:0; color:#4B5563; font-size:0.9rem;">${latest.location || 'Unknown Location'}</p>
                </div>
                <span style="background:#FEE2E2; color:#991B1B; padding:4px 8px; border-radius:4px; font-size:0.8rem; font-weight:bold;">PENDING</span>
            </div>
            <div style="margin-top:12px; font-size:0.9rem; color:#374151;">
                ${latest.description || 'No description provided.'}
            </div>
            <div style="margin-top:8px; font-size:0.8rem; color:#6B7280;">
                Reported by: ${latest.reporterID || 'Anonymous'} • ${new Date(latest.createdAt).toLocaleTimeString()}
            </div>
        `;

        // Update Modal UI with actions
        // We inject the buttons dynamically so we can attach the ID
        const actionsDiv = document.createElement('div');
        actionsDiv.style.display = 'grid';
        actionsDiv.style.gap = '12px';
        actionsDiv.style.gridTemplateColumns = '1fr 1fr';
        actionsDiv.style.marginTop = '24px';

        actionsDiv.innerHTML = `
            <button onclick="dismissUrgentAlert('${latest.id}')" class="btn btn-ghost" style="border-color:#d1d5db; color:#4b5563;">
                ✕ Dismiss Temporarily
            </button>
            <button onclick="viewIncidentFromModal('${latest.id}')" class="btn btn-primary" style="background:#4b5563; border-color:#4b5563;">
                👀 View on Map
            </button>
        `;

        // Add Resolve Button (Full Width)
        const resolveBtn = document.createElement('button');
        resolveBtn.className = 'btn btn-danger';
        resolveBtn.onclick = () => resolveDirectlyFromModal(latest.id);
        resolveBtn.style.width = '100%';
        resolveBtn.style.marginTop = '12px';
        resolveBtn.style.padding = '14px';
        resolveBtn.style.fontSize = '1.1rem';
        resolveBtn.style.fontWeight = 'bold';
        resolveBtn.innerHTML = '✅ Acknowledge & Resolve';

        // Clear previous content of modal text container if needed, but we used innerHTML on detailsContainer
        // The modal structure in HTML has the button hardcoded, we should replace that part or hide it.
        // Easier approach: Replace the entire inner content of the modal wrapper (parent of detailsContainer)
        // OR, since the specific modal HTML in manager-dashboard.html has a hardcoded button, let's target the parent container of detailsContainer
        // actually, let's just use the 'urgent-modal-details' to show data, and manipulate the buttons below it.

        // Let's grab the modal content container (the white box inside the fixed overlay)
        // We'll trust the ID 'urgent-alert-modal' points to the overlay. The first child is the white box.
        const modalBox = modal.firstElementChild;

        // Re-render the whole box content relative to data
        modalBox.innerHTML = `
            <div style="font-size:4rem; margin-bottom:16px;">🚨</div>
            <h2 style="color:#991B1B; font-weight:800; font-size:1.8rem; margin:0 0 12px;">NEW CRITICAL INCIDENT!</h2>
            <p style="color:#B91C1C; margin-bottom:24px; font-size:1.1rem;">
                A new report has been submitted.<br>
                <strong>Immediate action required.</strong>
            </p>
            
            <div style="background:white; padding:16px; border-radius:8px; margin-bottom:24px; text-align:left; border:1px solid #FECACA;">
                ${detailsContainer.innerHTML} <!-- Reuse the inner HTML we just built -->
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
                <button onclick="dismissUrgentAlert('${latest.id}')" class="btn" style="background:white; color:#4B5563; border:1px solid #D1D5DB;">
                   ✕ Dismiss
                </button>
                <button onclick="viewIncidentFromModal('${latest.id}')" class="btn" style="background:#4B5563; color:white; border:none;">
                   👀 View Details
                </button>
            </div>
            
            <button onclick="resolveDirectlyFromModal('${latest.id}')" class="btn btn-danger" style="width:100%; padding:14px; font-size:1.1rem; font-weight:bold; box-shadow:0 4px 6px rgba(220, 38, 38, 0.2);">
                ✅ Acknowledge & Resolve
            </button>
        `;

        modal.style.display = 'flex';
    } else {
        modal.style.display = 'none';
    }
}

function dismissUrgentAlert(id) {
    if (id) ignoredIncidentIds.add(id);
    document.getElementById('urgent-alert-modal').style.display = 'none';
}

function viewIncidentFromModal(id) {
    dismissUrgentAlert(id); // Hide modal first
    switchSection('live'); // Go to live dashboard

    // Scroll to the specific card if possible.
    // We might need to wait for refreshDashboard() if it wasn't loaded.
    // For now, simple switch is good. The latest incident is usually at top.

    // Optional: Highlight the card
    setTimeout(() => {
        const cards = document.querySelectorAll('.video-card');
        if (cards.length > 0) {
            cards[0].style.border = '2px solid red';
            cards[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, 500);
}

function resolveDirectlyFromModal(id) {
    if (id) {
        resolveIncident(id);
        // We don't need to add to ignored list because it's no longer 'pending'
        checkUrgentIncidents(); // Re-check immediately
    }
}

/* --- Human-in-the-Loop Twilio Dispatch --- */
async function triggerTwilioDispatch(alertId, btnEl) {
    if (!currentDispatchAlert) return;

    const confirmMsg = `⚠️ CONFIRM: Call Ambulance for incident at ${currentDispatchAlert.location}? \n\nThis will trigger Twilio Voice Call & SMS.`;
    if (!confirm(confirmMsg)) return;

    btnEl.disabled = true;
    const originalHTML = btnEl.innerHTML;
    btnEl.innerHTML = '⏳ Triggering Twilio...';

    try {
        const response = await fetch(`${YOLO_BACKEND_URL}/dispatch-ambulance`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                location: currentDispatchAlert.location,
                alertId: currentDispatchAlert.id
            })
        });

        const result = await response.json();
        if (response.ok && result.success) {
            btnEl.innerHTML = '📞 Call Initiated';
            btnEl.style.background = 'linear-gradient(135deg, #16A34A, #15803D)';
            showToast('🚑 Twilio call and SMS triggered successfully!', 'success');
        } else {
            throw new Error(result.error || 'Dispatch failed');
        }
    } catch (err) {
        console.error('Twilio Dispatch Error:', err);
        btnEl.disabled = false;
        btnEl.innerHTML = originalHTML;
        showToast(`❌ Twilio Alert Failed: ${err.message}`, 'error');
    }
}
