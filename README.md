# 🚦 IncidentIQ — AI-Powered Road Accident Detection & Emergency Dispatch System

> **Real-time CCTV accident detection using YOLOv8, with automated ambulance dispatch, live dashboards, and a citizen SOS rescue portal.**

---

## 📌 Overview

**IncidentIQ** is a full-stack intelligent traffic surveillance system that automatically detects road accidents from CCTV footage using a custom-trained **YOLOv8** computer vision model. When an accident is confirmed, the system instantly dispatches emergency services via automated **Twilio voice calls & SMS**, notifies hospitals, and provides a real-time command dashboard for traffic managers.

The system is built around three roles:
- 🧑‍💼 **Traffic Managers** — Monitor live incidents, run AI analysis on uploaded footage, and manually dispatch emergency services.
- 👤 **Citizens (Users)** — Report accidents via a web portal, view nearby hospitals, and trigger an **SOS RescueLink** alert in emergencies.
- 🤖 **AI System (CCTV Watcher)** — Continuously analyses live camera feeds and auto-dispatches on confirmed detections.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Frontend (HTML/JS)                │
│  login.html → manager-dashboard.html / user-portal  │
│         Real-time UI via Socket.IO                  │
└────────────────┬────────────────────────────────────┘
                 │ HTTP REST + WebSocket
┌────────────────▼────────────────────────────────────┐
│           Flask Backend — server.py (Port 5000)     │
│  • YOLOv8 inference on uploaded CCTV videos         │
│  • REST API: /api/analyze, /api/cctv-alert, /api/sos│
│  • Socket.IO: real-time alert broadcasting          │
│  • Twilio: auto voice + SMS dispatch                │
│  • Firebase Auth + Firestore integration            │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│          cctv_watcher.py (Background Service)       │
│  • Watches live CCTV streams / video files          │
│  • Runs YOLO on every frame (15 fps inference)      │
│  • Requires 30 consecutive frames at >80% confidence│
│  • POSTs confirmed alerts to /api/cctv-alert        │
└─────────────────────────────────────────────────────┘
```

---

## ✨ Key Features

### 🤖 AI Detection Engine
- Custom-trained **YOLOv8** model (`accident_model_v2.pt`) detecting 5 accident classes:
  - Vehicle Collision, Multi-car Pileup, Hit & Run, Pedestrian Accident, General Accident
- **False-positive suppression**: Requires 30 consecutive frames at ≥ 80% confidence before triggering
- **60-second cooldown** per camera to prevent duplicate alerts
- Supports live RTSP streams, webcams, and video file playback

### 🚨 Automated Emergency Dispatch
- On AI-confirmed accident: automatically sends **Twilio voice call + SMS** to ambulance / dispatch
- Google Maps link with GPS coordinates embedded in every alert
- **Human-in-the-loop** override: manager can manually dispatch from dashboard at any time
- Per-hospital calling from the user portal (allowlist-protected)

### 📡 Real-Time Manager Dashboard
- **Live Dashboard** — Incident feed with stats (Total / Pending / Active / Resolved)
- **AI Analysis Hub** — Upload CCTV footage, pin camera location on a Leaflet map, run YOLO
- **CCTV Live Alerts** — WebSocket-streamed alerts with snapshots, dispatch buttons, false-alarm tagging
- **Alert Logs** — Full searchable history of all detections and dispatch actions
- Model **retraining trigger** from false-alarm feedback data

### 🆘 RescueLink — Citizen SOS Portal
- Users register with **blood group** and **emergency contact** number
- One-tap **SOS button** triggers 4 parallel Twilio actions (via `ThreadPoolExecutor`):
  | Action | Channel | Recipient |
  |--------|---------|-----------|
  | A | SMS | Responder network |
  | B | Voice call | Responder |
  | C | Voice call | User's emergency contact |
  | D | SMS | User's emergency contact |
- Location shared as live Google Maps link
- Firestore-backed **emergency alert** documents for audit trail

### 🔄 Self-Improving Model (Retraining Pipeline)
- Managers can mark detections as **"False Alarm"** — frames are saved to `retraining_data/false_positive/`
- `retrain.py` fine-tunes `accident_model_v2.pt` on corrected data (10 epochs, lr=0.001)
- New model saved to `runs/detect/accident_model_v2_retrained/weights/best.pt`
- Manager-triggered from dashboard with a single button click

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI / CV** | YOLOv8 (Ultralytics), OpenCV |
| **Backend** | Python, Flask, Flask-SocketIO, Eventlet |
| **Database** | Google Firebase Firestore, JSON profile store |
| **Auth** | Firebase Authentication |
| **Notifications** | Twilio (Voice Calls + SMS), SMTP Email |
| **Maps** | Leaflet.js, Overpass API, Google Maps links |
| **Frontend** | Vanilla HTML/CSS/JS, Socket.IO client |
| **DevOps** | python-dotenv, `.env` config, `.gitignore` |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js (optional, for JS tooling)
- Twilio account (for SMS/call dispatch)
- Firebase project (for auth + Firestore)

### 1. Clone & Install

```bash
git clone https://github.com/your-username/accident-detection.git
cd accident-detection
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
# Twilio (Emergency Dispatch)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM=+1XXXXXXXXXX
AMBULANCE_PHONE=+91XXXXXXXXXX

# RescueLink SOS
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
RESCUELINK_RESPONDER_SMS=+91XXXXXXXXXX
RESCUELINK_RESPONDER_VOICE=+91XXXXXXXXXX
EMERGENCY_PHONE_NUMBER=+91XXXXXXXXXX

# Firebase
FIREBASE_API_KEY=your_key
FIREBASE_AUTH_DOMAIN=your_project.firebaseapp.com
FIREBASE_PROJECT_ID=your_project_id
FIREBASE_STORAGE_BUCKET=your_project.appspot.com
FIREBASE_MESSAGING_SENDER_ID=000000000000
FIREBASE_APP_ID=1:000000000000:web:xxxx

# SMTP (optional, for email alerts)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your_email@gmail.com
SMTP_PASSWORD=your_app_password
```

### 3. Run the Backend

```bash
python server.py
# Server starts on http://localhost:5000
```

### 4. Run the CCTV Watcher (optional)

```bash
# Watch a video file:
python cctv_watcher.py --source path/to/cctv.mp4

# Watch webcam:
python cctv_watcher.py --source 0

# Override GPS coordinates:
python cctv_watcher.py --source 0 --lat 17.3850 --lng 78.4867
```

### 5. Retrain the Model (after feedback)

```bash
python retrain.py
# Or trigger from the manager dashboard → AI Analysis Hub → "Retrain Model"
```

---

## 📁 Project Structure

```
accident-detection/
├── server.py                  # Main Flask backend (1699 lines)
├── cctv_watcher.py            # CCTV live stream monitor
├── retrain.py                 # YOLO model fine-tuning pipeline
├── accident_model_v2.pt       # Custom-trained YOLOv8 weights (~22 MB)
├── rescue_user_profiles.json  # RescueLink user data store
├── firestore.rules            # Firebase security rules
│
├── index.html                 # Landing / redirect page
├── login.html                 # Firebase Auth login/register
├── manager-dashboard.html     # Traffic manager control panel
├── user-portal.html           # Citizen accident report + SOS portal
├── rescue-dashboard-demo.html # RescueLink demo page
│
├── requirements.txt           # Python dependencies
├── package.json               # Node.js dependencies (Twilio/Firebase JS)
├── run_retrain.bat            # Windows batch script for retraining
├── RESCUE_LINK.md             # RescueLink integration documentation
│
└── snapshots/                 # Auto-saved CCTV accident frames (JPEG)
```

---

## 📊 Model Details

| Property | Value |
|----------|-------|
| Architecture | YOLOv8 |
| Model file | `accident_model_v2.pt` |
| Size | ~22 MB |
| Inference confidence threshold | 80% |
| Consecutive frames required | 30 |
| Detection classes | 5 (Vehicle Collision, Pileup, Hit & Run, Pedestrian, Accident) |
| Input resolution | 640×640 |
| Inference speed | ~15 fps (CPU), faster on GPU |

---

## 🔐 Security Notes

- Emergency contact numbers and blood group data are stored **server-side only** — never exposed to the frontend
- Hospital call allowlist (`ALLOWED_HOSPITAL_NUMBERS`) prevents abuse of the Twilio call API
- Firebase security rules enforce authenticated access to Firestore collections
- All sensitive credentials are loaded from `.env` (excluded from git via `.gitignore`)

---

## 📸 Screenshots

| Manager Dashboard | AI Analysis Hub | User SOS Portal |
|---|---|---|
| Live incident feed with real-time WebSocket alerts | Upload CCTV footage + pin location on map + run YOLO | One-tap SOS with 4-way Twilio dispatch |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'Add your feature'`
4. Push to branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License.

---

## 👨‍💻 Author

**Datta Sai Charan**  
Built as part of a real-world AI & emergency response engineering project.

> *"Detecting accidents before responders are even called — saving seconds that save lives."*
