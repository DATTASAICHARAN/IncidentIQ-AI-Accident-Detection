<div align="center">

<img src="https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=white" />
<img src="https://img.shields.io/badge/Firebase-Firestore-FFCA28?style=for-the-badge&logo=firebase&logoColor=black" />
<img src="https://img.shields.io/badge/Vite-8-646CFF?style=for-the-badge&logo=vite&logoColor=white" />
<img src="https://img.shields.io/badge/TailwindCSS-4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" />
<img src="https://img.shields.io/badge/OpenStreetMap-Leaflet-7EBC6F?style=for-the-badge&logo=leaflet&logoColor=white" />
<img src="https://img.shields.io/badge/Hosted-Firebase-orange?style=for-the-badge&logo=firebase" />

<br/><br/>

# 🏥 QueueCare — Smart Virtual Hospital Queue System

### *Eliminate hospital waiting rooms. Track your place in line. Get notified before it's your turn.*

[**🔴 Live Demo**](https://cureq-eb02c.web.app) &nbsp;|&nbsp; [**📐 Architecture**](#-system-architecture) &nbsp;|&nbsp; [**🚀 Features**](#-key-features) &nbsp;|&nbsp; [**⚙️ Setup**](#%EF%B8%8F-local-setup)

</div>

---

## 🌟 Why QueueCare?

Every year, patients spend **billions of hours** waiting in hospital lobbies — a problem that causes stress, missed treatments, and inefficiency. **QueueCare** is a real-time virtual queue management system that lets patients book appointments, join a live token queue, and **get voice-called 5 minutes before their turn** — all from any device.

Doctors get a live dashboard to manage their queue, track overtime, and automatically recalculate projected wait times for every patient downstream.

---

## ✨ Key Features

### 🧑‍⚕️ For Patients
| Feature | Description |
|---|---|
| 📍 **GPS Hospital Finder** | Detects user location via browser Geolocation API and queries the **Overpass API** (OpenStreetMap) to list real nearby hospitals within 8 km |
| 🗺️ **Interactive Map** | Full React-Leaflet map with live user & hospital markers, animated panning, and popup booking buttons |
| 🔖 **Smart Token Booking** | Books an appointment and auto-assigns a queue token with a projected time calculated at **4-minute intervals** from the current time |
| 📊 **Live Queue Tracker** | Real-time scrollable queue card view powered by **Firestore `onSnapshot`** — updates without any page refresh |
| ⏱️ **Live Countdown Timer** | Per-second countdown showing exact time until the patient's turn |
| 🔔 **Voice Reminder Notification** | 5-minute voice alert using the **Web Speech API** (simulating a Twilio phone call) with an on-screen toast |
| ⭐ **Post-Session Feedback** | Star rating + written review modal auto-triggered after appointment completion |
| 🏙️ **City Search** | Manual city search powered by the **Nominatim geocoding API** to explore hospitals anywhere |

### 👨‍⚕️ For Doctors
| Feature | Description |
|---|---|
| 📋 **Live Queue Dashboard** | Real-time appointment list sorted by status: `in-progress → next → pending → completed` |
| ▶️ **One-Click Status Updates** | Instantly move patients from `pending → in-progress → completed` with live Firestore writes |
| ⚠️ **Overtime Detection** | If a session exceeds 4 minutes, a pulsing **OVERTIME** badge and a **"Shift Queue"** button appear |
| 🔄 **Smart Queue Recalculation** | Completing a session triggers automatic ripple-update of all pending patients' projected times |
| 📅 **Date Picker** | View and manage appointments for any date — past or future |
| 🟢 **Live Sync Indicator** | Pulsing "Live Sync" badge confirms real-time Firestore connection |

### 🔐 Authentication
- Role-based sign-up / sign-in (**Patient** or **Doctor**)
- Firebase Auth with email & password
- Doctors provide: Specialization, Hospital, Qualification
- Role stored in Firestore `users` collection, read on every login

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT (React + Vite)                        │
│                                                                     │
│  ┌──────────────┐   ┌─────────────────────┐   ┌─────────────────┐  │
│  │  Auth Layer  │   │   Patient Dashboard  │   │ Doctor Dashboard│  │
│  │              │   │                     │   │                 │  │
│  │ Firebase Auth│   │  ┌───────────────┐  │   │  ┌──────────┐  │  │
│  │ Role-based   │   │  │ Map Explorer  │  │   │  │Live Queue│  │  │
│  │ Routing      │   │  │ (React-Leaflet│  │   │  │Manager   │  │  │
│  └──────┬───────┘   │  │ + OSM Tiles)  │  │   │  └────┬─────┘  │  │
│         │           │  └───────┬───────┘  │   │       │         │  │
│         │           │          │          │   │       │         │  │
│         │           │  ┌───────▼───────┐  │   │  ┌────▼─────┐  │  │
│         │           │  │Live Queue View│  │   │  │ Status   │  │  │
│         │           │  │(onSnapshot)   │  │   │  │ Controls │  │  │
│         │           │  └───────┬───────┘  │   │  └────┬─────┘  │  │
│         │           │          │          │   │       │         │  │
│         │           │  ┌───────▼───────┐  │   │  ┌────▼─────┐  │  │
│         │           │  │Notification   │  │   │  │ Overtime │  │  │
│         │           │  │Service (Voice │  │   │  │ Detector │  │  │
│         │           │  │+ Toast)       │  │   │  └──────────┘  │  │
│         │           │  └───────────────┘  │   └─────────────────┘  │
│         │           └─────────────────────┘                        │
└─────────┼───────────────────────┬─────────────────────────────────┘
          │                       │
          ▼                       ▼
┌─────────────────┐   ┌───────────────────────────────────────────────┐
│  Firebase Auth  │   │              Firebase Firestore (NoSQL)        │
│                 │   │                                               │
│  - Email/Pass   │   │  ┌──────────────┐   ┌──────────────────────┐ │
│  - Session Mgmt │   │  │  users/      │   │   appointments/      │ │
│  - UID binding  │   │  │  {uid}       │   │   {appointmentId}    │ │
└─────────────────┘   │  │  - name      │   │   - patientId        │ │
                       │  │  - role      │   │   - doctorId         │ │
                       │  │  - email     │   │   - token (int)      │ │
                       │  │  - phone     │   │   - status           │ │
                       │  │  - specializ.│   │   - projectedTime    │ │
                       │  │  - hospital  │   │   - appointmentDate  │ │
                       │  └──────────────┘   │   - patientData {}   │ │
                       │                     │   - reminderSent     │ │
                       │                     │   - rating / feedback│ │
                       │                     └──────────────────────┘ │
                       └───────────────────────────────────────────────┘
                                         │
                                         │  Real-time onSnapshot listeners
                                         │  (zero-polling, push-based)
                                         ▼
                       ┌───────────────────────────────────────────────┐
                       │         External API Integrations             │
                       │                                               │
                       │  ┌──────────────────┐  ┌──────────────────┐  │
                       │  │  Overpass API    │  │  Nominatim API   │  │
                       │  │  (OpenStreetMap) │  │  (Geocoding)     │  │
                       │  │  Real hospital   │  │  City → lat/lng  │  │
                       │  │  data within 8km │  │  coordinate map  │  │
                       │  └──────────────────┘  └──────────────────┘  │
                       │                                               │
                       │  ┌──────────────────────────────────────┐    │
                       │  │  Web Speech API (Browser Native)     │    │
                       │  │  Voice notifications — simulates     │    │
                       │  │  Twilio automated reminder calls     │    │
                       │  └──────────────────────────────────────┘    │
                       └───────────────────────────────────────────────┘
                                         │
                                         ▼
                       ┌───────────────────────────────────────────────┐
                       │              Firebase Hosting                 │
                       │         https://cureq-app.web.app             │
                       └───────────────────────────────────────────────┘
```

### Data Flow — Booking an Appointment

```
Patient selects hospital (OSM data)
        │
        ▼
Patient selects doctor (Firestore: users?role=doctor)
        │
        ▼
Booking form submitted
        │
        ├── Query Firestore for existing appointments (same doctor, same date)
        │   → Calculate next token number (count + 1)
        │   → Calculate projectedTime (base 9AM + token × 4 minutes)
        │
        ├── Write new appointment document to Firestore
        │
        ├── Trigger voice confirmation (Web Speech API)
        │
        └── onSnapshot listeners fire on Patient & Doctor dashboards
            → Both UIs update in real-time without refresh
```

### Queue Recalculation Flow — When a Doctor Finishes a Session

```
Doctor clicks "Mark Done"
        │
        ├── Update appointment status → 'completed' in Firestore
        │
        └── recalculateQueue() fires:
            ├── Fetches all 'pending' appointments for this doctor
            └── Writes new projectedTime = now + (index + 1) × 4 minutes
                → Every waiting patient's countdown instantly adjusts
```

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Frontend Framework** | React 19 + Vite 8 | Component-based SPA with fast HMR |
| **Styling** | Tailwind CSS 4 | Utility-first responsive design |
| **Routing** | React Router DOM v7 | Role-based client-side routing |
| **Database** | Firebase Firestore | NoSQL real-time database with push listeners |
| **Authentication** | Firebase Auth | Secure email/password auth with UID binding |
| **Hosting** | Firebase Hosting | Global CDN deployment |
| **Maps** | React-Leaflet + OpenStreetMap | Interactive geo-mapping without API key costs |
| **Hospital Data** | Overpass API | Live OSM query for real hospitals near GPS coords |
| **Geocoding** | Nominatim API | City name → coordinates for manual search |
| **Notifications** | Web Speech API | Browser-native voice alerts (Twilio-ready) |
| **Icons** | Lucide React | Consistent, lightweight SVG icon set |

---

## 🗂️ Project Structure

```
QueueCare/
├── src/
│   ├── pages/
│   │   ├── Auth.jsx              # Login / Sign-up with role selection
│   │   ├── PatientDashboard.jsx  # Map, hospital finder, booking, live queue
│   │   ├── DoctorDashboard.jsx   # Queue manager, overtime tracker
│   │   ├── Login.jsx             # Standalone login redirect
│   │   └── Signup.jsx            # Standalone signup redirect
│   ├── components/
│   │   ├── Navbar.jsx            # Top navigation with auth state
│   │   └── Toast.jsx             # Animated notification toast
│   ├── context/
│   │   └── AuthContext.jsx       # Global auth state via React Context
│   ├── services/
│   │   └── NotificationService.js # Voice + toast notification engine
│   ├── firebase.js               # Firestore + Auth exports + reminder sweep
│   └── firebaseConfig.js         # Firebase project config
├── backend/                      # Node.js backend scaffold (extensible)
├── functions/                    # Firebase Cloud Functions (Twilio-ready)
├── firebase.json                 # Hosting + functions config
└── vite.config.js                # Vite build config
```

---

## ⚙️ Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/DATTASAICHARAN/QueueCare-Smart-Virtual-Hospital-Queue-System.git
cd "QueueCare – Smart Virtual Hospital Queue System"

# 2. Install dependencies
npm install

# 3. Configure Firebase
# Create src/firebaseConfig.js with your Firebase project credentials:
# export default initializeApp({ apiKey, authDomain, projectId, ... })

# 4. Start development server
npm run dev
```

> The app will be available at `http://localhost:5173`

---

## 🔮 Production Roadmap

- [ ] **Twilio Integration** — Replace Web Speech API simulation with real SMS/call via Firebase Cloud Functions
- [ ] **Push Notifications** — Firebase Cloud Messaging for background alerts
- [ ] **Admin Panel** — Hospital admin dashboard to manage doctors and specializations
- [ ] **Payment Gateway** — Razorpay/Stripe for consultation fee collection
- [ ] **Medical Records** — Secure upload and storage of patient reports via Firebase Storage
- [ ] **WhatsApp Reminders** — Twilio WhatsApp API for regional accessibility
- [ ] **Multi-language Support** — i18n for regional Indian languages

---

## 👨‍💻 Author

**Datta Sai Charan**
- 💼 [LinkedIn](https://www.linkedin.com/in/mamidala-datta-sai-charan-873a1a3b4/)
- 🐙 [GitHub](https://github.com/DATTASAICHARAN)

---

<div align="center">

*Built with ❤️ to modernize healthcare access — one queue at a time.*

⭐ **Star this repo if you find it useful!**

</div>
