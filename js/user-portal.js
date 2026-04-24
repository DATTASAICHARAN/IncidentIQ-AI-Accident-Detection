/* ============================================
   USER PORTAL — Incident Reporting
   ============================================ */

let map, marker;
let uploadedFiles = [];
let userLocation = { lat: null, lng: null };

/* --- Init --- */
document.addEventListener('DOMContentLoaded', () => {
    // Auth guard
    const session = requireAuth('user');
    if (!session) return;

    // Show user name
    document.getElementById('user-name').textContent = session.name || session.email;

    // Init map
    initMap();

    // Fetch location
    fetchLocation();

    // Setup drag-and-drop
    setupUploadZone();
});

/* --- Map (OpenStreetMap + Leaflet) --- */
function initMap() {
    map = L.map('map').setView([20.5937, 78.9629], 5); // Default: India

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19
    }).addTo(map);
}

function fetchLocation() {
    const statusEl = document.getElementById('location-status');
    statusEl.className = 'location-badge pending';
    statusEl.textContent = '⏳ Fetching location…';

    if (!navigator.geolocation) {
        statusEl.textContent = '❌ Geolocation not supported';
        return;
    }

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            userLocation.lat = pos.coords.latitude;
            userLocation.lng = pos.coords.longitude;

            document.getElementById('lat-input').value = userLocation.lat.toFixed(6);
            document.getElementById('lng-input').value = userLocation.lng.toFixed(6);

            statusEl.className = 'location-badge';
            statusEl.textContent = '✅ Location captured';

            // Update map
            map.setView([userLocation.lat, userLocation.lng], 16);

            if (marker) {
                marker.setLatLng([userLocation.lat, userLocation.lng]);
            } else {
                marker = L.marker([userLocation.lat, userLocation.lng]).addTo(map);
                marker.bindPopup('<b>Incident Location</b>').openPopup();
            }
        },
        (err) => {
            console.warn('Geolocation error:', err);
            statusEl.className = 'location-badge pending';
            statusEl.textContent = '⚠️ Location unavailable — check permissions';
        },
        { enableHighAccuracy: true, timeout: 10000 }
    );
}

/* --- File Upload --- */
function setupUploadZone() {
    const zone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');

    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('dragover');
    });

    zone.addEventListener('dragleave', () => {
        zone.classList.remove('dragover');
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        handleFiles(e.dataTransfer.files);
    });

    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });
}

function handleFiles(fileList) {
    const files = Array.from(fileList);
    const allowed = ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'video/mp4', 'video/quicktime', 'video/webm'];

    files.forEach(file => {
        if (!allowed.includes(file.type)) {
            showToast('Unsupported file type: ' + file.name, 'warning');
            return;
        }
        if (file.size > 100 * 1024 * 1024) {
            showToast('File too large (max 100MB): ' + file.name, 'warning');
            return;
        }
        uploadedFiles.push(file);
        addPreview(file);
    });
}

function addPreview(file) {
    const grid = document.getElementById('preview-grid');
    const item = document.createElement('div');
    item.className = 'preview-item';
    item.style.animation = 'fadeIn 0.3s ease';

    const idx = uploadedFiles.indexOf(file);

    if (file.type.startsWith('image/')) {
        const img = document.createElement('img');
        img.src = URL.createObjectURL(file);
        img.alt = file.name;
        item.appendChild(img);
    } else {
        const vid = document.createElement('video');
        vid.src = URL.createObjectURL(file);
        vid.muted = true;
        vid.addEventListener('loadedmetadata', () => vid.currentTime = 1);
        item.appendChild(vid);
    }

    const removeBtn = document.createElement('button');
    removeBtn.className = 'preview-item__remove';
    removeBtn.textContent = '✕';
    removeBtn.onclick = () => {
        uploadedFiles.splice(idx, 1);
        item.remove();
    };
    item.appendChild(removeBtn);

    grid.appendChild(item);
}

/* --- Submit --- */
function submitReport() {
    const submitBtn = document.getElementById('submit-btn');

    // Validate
    if (uploadedFiles.length === 0) {
        showToast('Please upload at least one photo or video.', 'error');
        return;
    }

    if (!userLocation.lat || !userLocation.lng) {
        showToast('Location not captured. Please allow location access and click Refresh.', 'error');
        return;
    }

    // Disable button to prevent double-submit
    submitBtn.disabled = true;
    submitBtn.innerHTML = '⏳ Submitting...';

    const session = getSession();
    const description = document.getElementById('description').value.trim();

    // Build incident record
    const incident = {
        id: generateId(),
        reporterId: session.id,
        reporterName: session.name || session.email,
        description: description,
        latitude: userLocation.lat,
        longitude: userLocation.lng,
        mediaCount: uploadedFiles.length,
        mediaNames: uploadedFiles.map(f => f.name),
        status: 'pending',
        createdAt: new Date().toISOString()
    };

    // Save to localStorage
    const incidents = JSON.parse(localStorage.getItem('iq_incidents') || '[]');
    incidents.push(incident);
    localStorage.setItem('iq_incidents', JSON.stringify(incidents));

    // Store media as data URLs for demo (first 5 files only)
    const mediaPromises = uploadedFiles.slice(0, 5).map(file => {
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = () => resolve({ name: file.name, type: file.type, data: reader.result, incidentId: incident.id });
            reader.readAsDataURL(file);
        });
    });

    Promise.all(mediaPromises).then(mediaItems => {
        const existingMedia = JSON.parse(localStorage.getItem('iq_media') || '[]');
        localStorage.setItem('iq_media', JSON.stringify([...existingMedia, ...mediaItems]));

        showToast('Report submitted successfully! 🎉', 'success');

        // Reset form
        uploadedFiles = [];
        document.getElementById('preview-grid').innerHTML = '';
        document.getElementById('description').value = '';

        // Re-enable button after short delay
        setTimeout(() => {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '🚀 Submit Report';
        }, 1500);
    }).catch(err => {
        console.error("Submission error:", err);
        showToast('Failed to submit report. Please try again.', 'error');
        submitBtn.disabled = false;
        submitBtn.innerHTML = '🚀 Submit Report';
    });
}

/* --- Toast Notifications --- */
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

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
