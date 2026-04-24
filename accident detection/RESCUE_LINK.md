# RescueLink — Auth, profile, and SOS

This project implements **RescueLink** pieces on top of your existing Flask + Firebase Auth stack.

## 1. Database & user model

### Production (SQL / Prisma example)

Add required columns on `User`:

```prisma
model User {
  id               String   @id @default(cuid())
  email            String   @unique
  passwordHash     String
  name             String?
  bloodGroup       String   // e.g. A+, O-
  emergencyContact String   // E.164 e.g. +919876543210
  createdAt        DateTime @default(now())
  updatedAt        DateTime @updatedAt
}
```

**Validation**

- `bloodGroup`: one of `A+, A-, B+, B-, O+, O-, AB+, AB-`
- `emergencyContact`: E.164 (`+` country code + digits), 10–15 digits total

### This repo (demo)

Profiles are stored in **`rescue_user_profiles.json`** (created automatically) via:

- `POST /api/user-profile` — upsert after registration
- `GET /api/user-profile?userId=...` — load for session / SOS

---

## 2. Frontend flow

1. **Registration** (`login.html` + `auth.js`)
   - User selects **blood group** and enters **emergency contact**.
   - After Firebase `createUser`, frontend calls `POST /api/user-profile`.
   - Session in `localStorage` (`iq_session`) includes `bloodGroup` and `emergencyContact`.

2. **User dashboard** (`user-portal.html` + `user-portal.js`)
   - Prominent **SOS** strip at the top.
   - On click: `navigator.geolocation.getCurrentPosition` → `POST /api/sos` with `userId`, `latitude`, `longitude`.
   - Legacy users without profile see **Complete RescueLink profile** card → `POST /api/user-profile`.

---

## 3. Backend SOS (`POST /api/sos`)

Loads the user from **`rescue_user_profiles.json`**, builds map link  
`https://www.google.com/maps?q={lat},{lng}`, then runs **four Twilio actions in parallel** using `ThreadPoolExecutor` (Python equivalent of `Promise.all`):

| Action | Channel | Target | Content |
|--------|---------|--------|---------|
| A | SMS | Responder list | `EMERGENCY SOS: User requires immediate assistance. Blood Group: [blood]. Location: [Maps URL]` |
| B | Voice | Responder | TwiML `<Say>` emergency + blood + pointer to SMS map link |
| C | Voice | `emergencyContact` | Exact script: emergency contact triggered SOS; check messages for location |
| D | SMS | `emergencyContact` | `URGENT: [Name] has triggered an SOS. Their current location is: [Maps URL]` |

### Environment variables (`.env`)

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_PHONE_NUMBER=+13187661994

# Comma-separated E.164 numbers for Action A (responder SMS network)
RESCUELINK_RESPONDER_SMS=+13185551234,+919876543210

# Single E.164 for Action B (responder voice)
RESCUELINK_RESPONDER_VOICE=+13185551234

# Optional fallback if RESCUELINK_RESPONDER_SMS is empty
EMERGENCY_PHONE_NUMBER=+13185551234
```

**Twilio trial:** destination numbers must be **verified** in Twilio Console for SMS/voice.

---

## 4. Node.js reference (`Promise.all`)

See **`rescue-sos-node-example.js`** for the same four actions using:

```js
await Promise.all([actionA, actionB, actionC, actionD]);
```

---

## 5. Run

Serve the app from Flask (`python server.py` on port **5001**) so `/api/user-profile` and `/api/sos` share the same origin as static pages, or set CORS appropriately.
