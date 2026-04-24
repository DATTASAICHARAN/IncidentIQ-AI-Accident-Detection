"""
IncidentIQ — YOLO Accident Detection Backend
Loads accident_model_v2.pt, analyses uploaded CCTV video files,
and brokers real-time CCTV alerts via WebSockets (Flask-SocketIO).
"""

import os
import sys
import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# Ensure Windows console can print UTF-8 log messages.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ── WebSocket (Socket.IO) ────────────────────────────────────────────────────
# async_mode='eventlet' gives real async support; falls back gracefully
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# ── Load YOLO model on startup ──────────────────────────────────────────────
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accident_model_v2.pt")
print(f"[IncidentIQ] Loading YOLO model from: {MODEL_PATH}")
model = None
model_load_error = None

if YOLO is None:
    model_load_error = "ultralytics package not installed"
    print(f"[IncidentIQ] WARNING: YOLO unavailable: {model_load_error}")
elif cv2 is None:
    model_load_error = "opencv-python package not installed"
    print(f"[IncidentIQ] WARNING: OpenCV unavailable: {model_load_error}")
else:
    try:
        model = YOLO(MODEL_PATH)
        print("[IncidentIQ] ✅ Model loaded successfully!")
    except Exception as exc:
        model_load_error = str(exc)
        print(f"[IncidentIQ] WARNING: Model failed to load: {model_load_error}")

# ── SMTP Config (from environment / .env) ────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

if SMTP_EMAIL:
    print(f"[IncidentIQ] 📧 SMTP configured: {SMTP_EMAIL}")
else:
    print("[IncidentIQ] ⚠️  SMTP not configured — dispatch will log only (set .env)")

# ── Twilio Config (for auto-dispatch SMS / call on accident detection) ────────
TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM         = os.getenv("TWILIO_FROM", "")        # Your Twilio number e.g. +14155552671
AMBULANCE_PHONE     = os.getenv("AMBULANCE_PHONE", "")    # Ambulance / dispatch centre number

if TWILIO_ACCOUNT_SID and AMBULANCE_PHONE:
    print(f"[IncidentIQ] 📱 Twilio configured — auto-dispatch SMS → {AMBULANCE_PHONE}")
else:
    print("[IncidentIQ] ⚠️  Twilio not configured — auto-dispatch will log only (set .env)")

# Load automated dispatch environment variables
TWILIO_PHONE_NUMBER    = os.getenv("TWILIO_PHONE_NUMBER", TWILIO_FROM)
EMERGENCY_PHONE_NUMBER = os.getenv("EMERGENCY_PHONE_NUMBER", AMBULANCE_PHONE)

# Allowed hospital numbers for user-portal call button (anti-abuse allowlist).
ALLOWED_HOSPITAL_NUMBERS = {
    "+916305198595",
    "+917416099434",
    "+917670889575",
    "+919032210200",
}

# ── RescueLink: user profiles (blood group + emergency contact) ───────────────
RESCUELINK_PROFILES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "rescue_user_profiles.json"
)
VALID_BLOOD_GROUPS = frozenset(
    {"A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"}
)
RESCUELINK_RESPONDER_VOICE = os.getenv("RESCUELINK_RESPONDER_VOICE", "").strip() or EMERGENCY_PHONE_NUMBER


def _responder_sms_numbers():
    """Comma-separated E.164 in RESCUELINK_RESPONDER_SMS, else primary emergency number."""
    raw = os.getenv("RESCUELINK_RESPONDER_SMS", "").strip()
    if raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    if EMERGENCY_PHONE_NUMBER and str(EMERGENCY_PHONE_NUMBER).strip():
        return [str(EMERGENCY_PHONE_NUMBER).strip()]
    return []


def _load_rescue_profiles():
    if not os.path.exists(RESCUELINK_PROFILES_PATH):
        return {}
    try:
        with open(RESCUELINK_PROFILES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_rescue_profiles(data):
    with open(RESCUELINK_PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _profile_public_safe(uid, full_profile):
    """
    Strip sensitive medical/contact fields before sending to the frontend.
    bloodGroup and emergencyContact stay server-side only (SOS route reads DB/file).
    """
    if not full_profile:
        return None
    complete = bool(
        full_profile.get("bloodGroup")
        and full_profile.get("emergencyContact")
    )
    return {
        "userId": uid,
        "name": full_profile.get("name") or "User",
        "email": full_profile.get("email") or "",
        "profileComplete": complete,
    }


def _validate_blood_group(bg):
    return bg in VALID_BLOOD_GROUPS


def to_e164_india(phone_raw):
    """
    Normalize user-provided phone values to E.164 (+91...) for India.
    Returns None if invalid.
    """
    if not phone_raw:
        return None
    digits = "".join(ch for ch in str(phone_raw) if ch.isdigit() or ch == "+")
    if not digits:
        return None
    if digits.startswith("+"):
        return digits
    # If number is local 10-digit Indian number, prefix +91
    only_digits = "".join(ch for ch in digits if ch.isdigit())
    if len(only_digits) == 10:
        return f"+91{only_digits}"
    return None


def _validate_emergency_phone_e164(phone_raw):
    """Require plausible E.164 (+country...), min 10 digits total."""
    if not phone_raw:
        return None
    s = str(phone_raw).strip()
    if not s.startswith("+"):
        s = to_e164_india(s) or ""
    if not s.startswith("+"):
        return None
    digits = sum(1 for c in s if c.isdigit())
    if digits < 10 or digits > 15:
        return None
    return s


def dispatch_emergency_twilio(location, details=""):
    """
    Expert implementation of a fully automated emergency dispatch system.
    Triggers both a Voice Call and an SMS Alert instantly.
    """
    import urllib.parse
    from twilio.rest import Client as TwilioClient
    
    # 1. Validation
    to_phone = EMERGENCY_PHONE_NUMBER

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and to_phone):
        print(f"[IncidentIQ] ⚠️ Automated dispatch aborted: Twilio credentials missing in .env")
        return {"error": "Twilio configuration missing"}

    results = {"voice": "pending", "sms": "pending"}
    
    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # 2. Automated Voice Call
        try:
            # Reusable TwiML for automated voice response
            detail_text = (details or "No additional description provided").replace('"', "'")
            twiml = f'<Response><Say voice="alice">Emergency. Accident detected at {location}. Details: {detail_text}. Ambulance required immediately.</Say></Response>'
            call = client.calls.create(
                to=to_phone,
                from_=TWILIO_PHONE_NUMBER,
                twiml=twiml
            )
            print(f"[Twilio] 📞 Automated Call triggered. SID: {call.sid}")
            results["voice"] = f"Success (SID: {call.sid})"
        except Exception as ve:
            print(f"[Twilio] ❌ Voice call failed: {ve}")
            results["voice"] = f"Failed: {str(ve)}"

        # 3. Automated SMS Alert
        try:
            encoded_loc = urllib.parse.quote(location)
            maps_link = f"https://www.google.com/maps/search/?api=1&query={encoded_loc}"
            sms_body = f"Alert: Traffic accident reported at {location}. Description: {details or 'No description provided'}. Dispatch ambulance. Maps: {maps_link}"
            
            message = client.messages.create(
                to=to_phone,
                from_=TWILIO_PHONE_NUMBER,
                body=sms_body
            )
            print(f"[Twilio] 📱 Automated SMS sent. SID: {message.sid}")
            results["sms"] = f"Success (SID: {message.sid})"
        except Exception as se:
            print(f"[Twilio] ❌ SMS alert failed: {se}")
            results["sms"] = f"Failed: {str(se)}"

        return results

    except Exception as e:
        print(f"[IncidentIQ] 💥 Critical Twilio API failure: {e}")
        return {"error": str(e)}


@app.route("/api/call-hospital", methods=["POST"])
def api_call_hospital():
    """
    Initiate a Twilio voice call to a selected hospital number from user portal.
    Triggered when user clicks Call beside a hospital card.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid payload"}), 400

    hospital_name = data.get("hospitalName", "Hospital")
    target_phone_raw = data.get("phone", "")
    target_phone = to_e164_india(target_phone_raw)
    latitude = data.get("latitude", None)
    longitude = data.get("longitude", None)
    description = (data.get("description", "") or "").strip()

    if not target_phone:
        return jsonify({"error": "Invalid or missing hospital phone number"}), 400

    if target_phone not in ALLOWED_HOSPITAL_NUMBERS:
        return jsonify({"error": "Phone number not allowed for Twilio call"}), 403

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER):
        return jsonify({"error": "Twilio configuration missing in .env"}), 500

    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        loc_label = "Location unavailable"
        maps_url = ""
        if latitude is not None and longitude is not None:
            try:
                lat_val = float(latitude)
                lng_val = float(longitude)
                loc_label = f"{lat_val:.6f}, {lng_val:.6f}"
                maps_url = f"https://www.google.com/maps?q={lat_val},{lng_val}"
            except (TypeError, ValueError):
                pass

        details_text = description if description else "No description provided"

        twiml = (
            f'<Response>'
            f'<Say voice="alice">This is an automated call from IncidentIQ. '
            f'Connecting to {hospital_name} for emergency response coordination.</Say>'
            f'</Response>'
        )

        call = client.calls.create(
            to=target_phone,
            from_=TWILIO_PHONE_NUMBER,
            twiml=twiml
        )

        sms_sent = False
        sms_sid = None
        try:
            sms_body = (
                f"IncidentIQ Alert for {hospital_name}\n"
                f"Location: {loc_label}\n"
                f"Description: {details_text}\n"
                f"{'Maps: ' + maps_url if maps_url else ''}"
            ).strip()
            sms = client.messages.create(
                to=target_phone,
                from_=TWILIO_PHONE_NUMBER,
                body=sms_body
            )
            sms_sent = True
            sms_sid = sms.sid
        except Exception as sms_exc:
            print(f"[Twilio] ⚠️ Hospital SMS failed: {sms_exc}")

        return jsonify({
            "success": True,
            "hospital": hospital_name,
            "to": target_phone,
            "from": TWILIO_PHONE_NUMBER,
            "callSid": call.sid,
            "status": call.status,
            "smsSent": sms_sent,
            "smsSid": sms_sid,
            "location": loc_label
        }), 200
    except Exception as exc:
        err_text = str(exc)
        print(f"[Twilio] ❌ Hospital call failed: {err_text}")

        # Twilio trial accounts can only call verified destination numbers.
        if "unverified" in err_text.lower() and "trial accounts" in err_text.lower():
            return jsonify({
                "error": (
                    "Twilio trial restriction: destination number is not verified. "
                    "Verify this number in Twilio Console (Verified Caller IDs) or upgrade account."
                ),
                "trialRestriction": True
            }), 400

        return jsonify({"error": err_text}), 500


# ── RescueLink: user profile + SOS (Twilio × 4 concurrent) ─────────────────

@app.route("/api/user-profile", methods=["GET", "POST"])
def api_user_profile():
    """
    GET  ?userId=...  — safe profile for dashboard (NO bloodGroup / emergencyContact).
    POST — upsert full profile server-side; response also omits sensitive fields.
    Body: { userId, name, email, bloodGroup, emergencyContact }
    """
    if request.method == "GET":
        uid = request.args.get("userId", "").strip()
        if not uid:
            return jsonify({"error": "userId required"}), 400
        profiles = _load_rescue_profiles()
        profile = profiles.get(uid)
        if not profile:
            return jsonify({
                "success": True,
                "profile": {
                    "userId": uid,
                    "name": "",
                    "email": "",
                    "profileComplete": False,
                },
            }), 200
        safe = _profile_public_safe(uid, profile)
        return jsonify({"success": True, "profile": safe})

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    uid = (data.get("userId") or "").strip()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    blood = (data.get("bloodGroup") or "").strip().upper().replace(" ", "")
    emergency_raw = data.get("emergencyContact", "")

    if not uid:
        return jsonify({"error": "userId required"}), 400
    if not _validate_blood_group(blood):
        return jsonify({"error": "Invalid bloodGroup. Use A+, A-, B+, B-, O+, O-, AB+, AB-."}), 400
    emergency = _validate_emergency_phone_e164(emergency_raw)
    if not emergency:
        return jsonify({"error": "Invalid emergencyContact. Use E.164 (+country...) or 10-digit local number."}), 400

    profiles = _load_rescue_profiles()
    profiles[uid] = {
        "name": name or "User",
        "email": email,
        "bloodGroup": blood,
        "emergencyContact": emergency,
        "updatedAt": datetime.now().isoformat(),
    }
    _save_rescue_profiles(profiles)
    safe = _profile_public_safe(uid, profiles[uid])
    return jsonify({"success": True, "profile": safe}), 200


@app.route("/api/sos", methods=["POST"])
def api_rescue_sos():
    """
    RescueLink SOS: run four Twilio actions concurrently (thread pool).
    Body: { userId, latitude, longitude }
    Loads bloodGroup + emergencyContact from server profile store.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    uid = (data.get("userId") or "").strip()
    try:
        lat = float(data.get("latitude"))
        lng = float(data.get("longitude"))
    except (TypeError, ValueError):
        return jsonify({"error": "latitude and longitude must be valid numbers"}), 400

    if not uid:
        return jsonify({"error": "userId required"}), 400

    profiles = _load_rescue_profiles()
    user = profiles.get(uid)
    if not user:
        return jsonify({"error": "Profile not found. Register with blood group and emergency contact."}), 404

    blood = user.get("bloodGroup", "")
    emergency = user.get("emergencyContact", "")
    name = user.get("name", "User")
    if not blood or not emergency:
        return jsonify({"error": "Profile incomplete: bloodGroup and emergencyContact required"}), 400

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER):
        return jsonify({"error": "Twilio not configured"}), 500

    maps_url = f"https://www.google.com/maps?q={lat},{lng}"

    # Exact copy per product spec
    sms_responder_body = (
        f"EMERGENCY SOS: User requires immediate assistance. Blood Group: {blood}. "
        f"Location: {maps_url}"
    )
    sms_contact_body = (
        f"URGENT: {name} has triggered an SOS. Their current location is: {maps_url}"
    )
    voice_responder_twiml = (
        '<Response><Say voice="alice">'
        f"Emergency SOS. {name} requires immediate assistance. Blood group {blood}. "
        f"Check the responder SMS for the exact map link."
        '</Say></Response>'
    )
    voice_contact_twiml = (
        '<Response><Say voice="alice">'
        "Alert: Your emergency contact has triggered an SOS. "
        "Please check your messages for their location."
        '</Say></Response>'
    )

    from twilio.rest import Client as TwilioClient
    client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    from_num = TWILIO_PHONE_NUMBER

    def action_a_sms_responders():
        targets = _responder_sms_numbers()
        if not targets:
            return {"skipped": True, "reason": "No RESCUELINK_RESPONDER_SMS or EMERGENCY_PHONE_NUMBER"}
        sids = []
        for to in targets:
            msg = client.messages.create(to=to, from_=from_num, body=sms_responder_body)
            sids.append(msg.sid)
        return {"skipped": False, "messageSids": sids}

    def action_b_voice_responder():
        to = (RESCUELINK_RESPONDER_VOICE or "").strip()
        if not to:
            return {"skipped": True, "reason": "No RESCUELINK_RESPONDER_VOICE or EMERGENCY_PHONE_NUMBER"}
        call = client.calls.create(to=to, from_=from_num, twiml=voice_responder_twiml)
        return {"skipped": False, "callSid": call.sid}

    def action_c_voice_emergency_contact():
        call = client.calls.create(to=emergency, from_=from_num, twiml=voice_contact_twiml)
        return {"callSid": call.sid}

    def action_d_sms_emergency_contact():
        msg = client.messages.create(to=emergency, from_=from_num, body=sms_contact_body)
        return {"messageSid": msg.sid}

    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {
            pool.submit(action_a_sms_responders): "action_a_sms_responders",
            pool.submit(action_b_voice_responder): "action_b_voice_responder",
            pool.submit(action_c_voice_emergency_contact): "action_c_voice_emergency_contact",
            pool.submit(action_d_sms_emergency_contact): "action_d_sms_emergency_contact",
        }
        for fut in as_completed(future_map):
            key = future_map[fut]
            try:
                results[key] = {"ok": True, "data": fut.result()}
            except Exception as ex:
                print(f"[RescueLink SOS] {key} failed: {ex}")
                results[key] = {"ok": False, "error": str(ex)}

    return jsonify({
        "success": True,
        "userId": uid,
        "mapsUrl": maps_url,
        "results": results,
    }), 200


@app.route("/api/sos-context", methods=["GET"])
def api_sos_context():
    """
    Return bloodGroup for a userId (server-side profile only).
    Used by the portal to build Firestore `emergency_alerts` docs without exposing
    blood group in localStorage. For production, protect with Firebase ID tokens.
    """
    uid = (request.args.get("userId") or "").strip()
    if not uid:
        return jsonify({"error": "userId required"}), 400

    profiles = _load_rescue_profiles()
    user = profiles.get(uid)
    if not user:
        return jsonify({"error": "Profile not found"}), 404

    blood = user.get("bloodGroup", "")
    if not blood:
        return jsonify({"error": "Blood group not set"}), 400

    return jsonify({"bloodGroup": blood}), 200


# ── Firebase Public Config (for frontend) ────────────────────────────────────
FIREBASE_CONFIG = {
    "apiKey"           : os.getenv("FIREBASE_API_KEY", ""),
    "authDomain"       : os.getenv("FIREBASE_AUTH_DOMAIN", ""),
    "projectId"        : os.getenv("FIREBASE_PROJECT_ID", ""),
    "storageBucket"    : os.getenv("FIREBASE_STORAGE_BUCKET", ""),
    "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", ""),
    "appId"            : os.getenv("FIREBASE_APP_ID", ""),
    "measurementId"    : os.getenv("FIREBASE_MEASUREMENT_ID", ""),
}

# Class names — adjust these if your model uses different labels
CLASS_LABELS = {
    0: "Vehicle Collision",
    1: "Multi-car Pileup",
    2: "Hit & Run",
    3: "Pedestrian Accident",
    4: "Accident",
}

# ── YOLO /analyze: automatic Twilio dispatch (voice + SMS) ───────────────────
# Fixed destination for AI-confirmed accidents; 60s cooldown prevents frame-loop spam.
YOLO_AUTO_DISPATCH_E164 = "+916281365760"
YOLO_AUTO_DISPATCH_COOLDOWN_SEC = 60
_last_yolo_auto_dispatch_monotonic = 0.0


def try_yolo_auto_dispatch_twilio(lat, lng, detection_type, confidence, alert_id):
    """
    Invoked when /analyze confirms an accident (confidence >= threshold).
    Sends SMS + voice to YOLO_AUTO_DISPATCH_E164 unless cooldown is active.
    Returns a dict safe to JSON-merge into the analyze response and to emit over SocketIO.
    """
    global _last_yolo_auto_dispatch_monotonic
    import time

    now = time.monotonic()
    elapsed = now - _last_yolo_auto_dispatch_monotonic
    if elapsed < YOLO_AUTO_DISPATCH_COOLDOWN_SEC:
        rem = YOLO_AUTO_DISPATCH_COOLDOWN_SEC - elapsed
        info = {
            "ok": False,
            "skipped": True,
            "reason": "cooldown",
            "cooldown_remaining_sec": round(rem, 1),
            "sms_sent": False,
        }
        try:
            socketio.emit("yolo_auto_dispatch", {
                "alertId": alert_id,
                "latitude": lat,
                "longitude": lng,
                "detectionType": detection_type,
                "dispatch": info,
            })
        except Exception:
            pass
        return info

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER):
        print("[YOLO Auto-Dispatch] Twilio not fully configured — skipping API call.")
        return {
            "ok": False,
            "skipped": False,
            "reason": "twilio_not_configured",
            "sms_sent": False,
        }

    # Start cooldown window as soon as we attempt (prevents rapid repeat calls)
    _last_yolo_auto_dispatch_monotonic = now

    to_num = YOLO_AUTO_DISPATCH_E164
    from_num = str(TWILIO_PHONE_NUMBER).strip()
    maps_url = f"https://www.google.com/maps?q={lat},{lng}"
    sms_body = (
        f"🚨 YOLO AI — {detection_type}\n"
        f"Confidence: {confidence}%\n"
        f"GPS: {lat}, {lng}\n"
        f"Map: {maps_url}\n"
        f"Alert ID: {alert_id}\n"
        f"Immediate response requested."
    )
    twiml = (
        '<Response><Say voice="alice">'
        "Emergency alert. The A I system has detected a possible accident at the reported coordinates. "
        "Please dispatch assistance immediately."
        "</Say></Response>"
    )

    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        call = client.calls.create(to=to_num, from_=from_num, twiml=twiml)
        print(f"[YOLO Auto-Dispatch] 📞 Call SID: {call.sid} → {to_num}")

        message = client.messages.create(to=to_num, from_=from_num, body=sms_body)
        print(f"[YOLO Auto-Dispatch] 📱 SMS SID: {message.sid} → {to_num}")

        info = {
            "ok": True,
            "skipped": False,
            "reason": "dispatched",
            "sms_sent": True,
            "call_sid": call.sid,
            "sms_sid": message.sid,
            "to": to_num,
        }
        try:
            socketio.emit("yolo_auto_dispatch", {
                "alertId": alert_id,
                "latitude": lat,
                "longitude": lng,
                "detectionType": detection_type,
                "dispatch": info,
            })
            socketio.emit("ambulance_dispatched", {
                "alert_id": alert_id,
                "location": f"{lat}, {lng}",
                "source": "yolo_auto",
            })
        except Exception:
            pass
        return info
    except Exception as e:
        print(f"[YOLO Auto-Dispatch] ❌ Twilio error: {e}")
        return {
            "ok": False,
            "skipped": False,
            "reason": "twilio_error",
            "error": str(e),
            "sms_sent": False,
        }


# ── Auto-Dispatch: send Twilio SMS to ambulance on accident detection ─────────
def auto_dispatch_ambulance(lat, lng, detection_type, confidence, alert_id):
    """
    Automatically called by /analyze when an accident is detected.
    Sends a real Twilio SMS (if configured) or logs to console.
    Returns True if SMS was sent, False otherwise.
    """
    import uuid
    maps_url = f"https://www.google.com/maps?q={lat},{lng}"
    ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sms_body = (
        f"🚨 ACCIDENT DETECTED — {detection_type}\n"
        f"Confidence : {confidence}%\n"
        f"GPS        : {lat}, {lng}\n"
        f"Map        : {maps_url}\n"
        f"Time       : {ts}\n"
        f"Alert ID   : {alert_id}\n"
        f"⚠️  Respond immediately!"
    )

    log_header = (
        f"\n{'='*60}\n"
        f"🚑 AUTO-DISPATCH TRIGGERED\n"
        f"{'='*60}\n"
        f"  Type       : {detection_type}\n"
        f"  Confidence : {confidence}%\n"
        f"  GPS        : {lat}, {lng}\n"
        f"  Map        : {maps_url}\n"
        f"  To         : {AMBULANCE_PHONE or 'NOT CONFIGURED'}\n"
    )

    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM and AMBULANCE_PHONE:
        try:
            from twilio.rest import Client as TwilioClient
            twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            
            # 1. SMS Alert
            message = twilio_client.messages.create(
                body=sms_body,
                from_=TWILIO_FROM,
                to=AMBULANCE_PHONE,
            )
            print(f"[Twilio] 📱 Auto-SMS Sent: {message.sid}")

            # 2. Voice Call (Newly added for automatic system detections)
            twiml_content = f'<Response><Say voice="alice">Emergency alert. An accident has been detected at the reported location. Immediate ambulance assistance is required.</Say></Response>'
            call = twilio_client.calls.create(
                to=AMBULANCE_PHONE,
                from_=TWILIO_FROM,
                twiml=twiml_content
            )
            print(f"[Twilio] 📞 Auto-Call SID: {call.sid}")

            print(log_header + f"  Twilio IDs : {message.sid} (SMS), {call.sid} (Call)\n  Status     : DISPATCHED ✅\n{'='*60}\n")
            return True
        except Exception as e:
            print(log_header + f"  Twilio ERR : {e}\n  Status     : DISPATCH FAILED ❌ (logged only)\n{'='*60}\n")
            return False
    else:
        print(log_header + f"  Status     : LOGGED ONLY (Twilio not configured)\n{'='*60}\n")
        return False


# ── Snapshots directory (saved by cctv_watcher.py) ───────────────────────────
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)


# ── Routes for serving HTML pages and static files ──────────────────────────

@app.route("/")
def index():
    """Serve the login page as the default landing page."""
    return send_from_directory(".", "login.html")

@app.route("/<path:filename>")
def serve_static(filename):
    """Serve HTML, CSS, JS, and other static files."""
    return send_from_directory(".", filename)


@app.route("/snapshots/<path:filename>")
def serve_snapshot(filename):
    """Serve CCTV snapshots saved by cctv_watcher.py."""
    return send_from_directory(SNAPSHOTS_DIR, filename)


@app.route("/api/config")
def get_config():
    """Serve public Firebase configuration to the frontend."""
    return jsonify(FIREBASE_CONFIG)


# ── Real-time CCTV Alert Webhook (called by cctv_watcher.py) ─────────────────

@app.route("/api/cctv-alert", methods=["POST"])
def cctv_alert():
    """
    Receive a confirmed accident alert from cctv_watcher.py and
    broadcast it to all connected dashboard clients via WebSocket.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    camera_id      = data.get("cameraId", "UNKNOWN")
    camera_label   = data.get("cameraLabel", camera_id)
    timestamp      = data.get("timestamp", datetime.now().isoformat())
    latitude       = data.get("latitude", 0)
    longitude      = data.get("longitude", 0)
    snapshot_url   = data.get("snapshotUrl", "")
    confidence     = data.get("confidence", 0)
    detection_type = data.get("detectionType", "Accident")

    # Generate a unique alert ID
    import uuid
    alert_id = str(uuid.uuid4())

    alert_payload = {
        "alertId"      : alert_id,
        "cameraId"     : camera_id,
        "cameraLabel"  : camera_label,
        "timestamp"    : timestamp,
        "latitude"     : latitude,
        "longitude"    : longitude,
        "snapshotUrl"  : snapshot_url,
        "confidence"   : confidence,
        "detectionType": detection_type,
        "location"     : f"{latitude:.4f}, {longitude:.4f}",
        "status"       : "pending",
    }

    # Broadcast to ALL connected dashboard clients
    socketio.emit("cctv_alert", alert_payload)
    socketio.emit("new_accident_alert", {
        "alert_id": alert_id,
        "location": alert_payload["location"],
        "severity": alert_payload.get("severity", "High"),
        "camera_id": camera_id,
        "timestamp": timestamp,
        "status": "pending_confirmation"
    })

    print(
        f"\n{'='*60}\n"
        f"🚨 CCTV ALERT RECEIVED & BROADCAST\n"
        f"{'='*60}\n"
        f"Camera    : {camera_id} ({camera_label})\n"
        f"Detection : {detection_type} ({confidence}%)\n"
        f"Location  : {latitude}, {longitude}\n"
        f"Snapshot  : {snapshot_url}\n"
        f"Alert ID  : {alert_id}\n"
        f"{'='*60}\n"
    )

    return jsonify({"success": True, "alertId": alert_id})


# ── Ambulance Dispatch (called by the dispatcher clicking the button) ─────────

@app.route("/api/dispatch-ambulance", methods=["POST"])
def dispatch_ambulance():
    """
    Human-in-the-loop ambulance dispatch.
    Called when the dispatcher clicks 'Confirm & Dispatch Ambulance'.
    Logs mock Twilio SMS and SendGrid e-mail payloads to console.
    Replace the print() blocks with real API calls when ready.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    alert_id       = data.get("alertId", "UNKNOWN")
    camera_id      = data.get("cameraId", "UNKNOWN")
    camera_label   = data.get("cameraLabel", camera_id)
    latitude       = data.get("latitude", 0)
    longitude      = data.get("longitude", 0)
    timestamp      = data.get("timestamp", datetime.now().isoformat())
    detection_type = data.get("detectionType", "Accident")
    confidence     = data.get("confidence", "N/A")
    maps_url       = f"https://www.google.com/maps?q={latitude},{longitude}"

    # ── Real Twilio SMS ──────────────────────────────────────────────────────
    sms_body = (
        f"🚨 AMBULANCE DISPATCHED — {detection_type}\n"
        f"Camera : {camera_label} ({camera_id})\n"
        f"Time   : {timestamp}\n"
        f"GPS    : {latitude}, {longitude}\n"
        f"Map    : {maps_url}\n"
        f"Conf   : {confidence}%\n"
        f"Ref ID : {alert_id}"
    )

    sms_sent = False
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM and AMBULANCE_PHONE:
        try:
            from twilio.rest import Client as TwilioClient
            twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            message = twilio_client.messages.create(
                body=sms_body,
                from_=TWILIO_FROM,
                to=AMBULANCE_PHONE,
            )
            print(f"[IncidentIQ] 📱 Manual Dispatch SMS Sent: {message.sid}")
            sms_sent = True
        except Exception as e:
            print(f"[IncidentIQ] ❌ Manual Dispatch SMS Failed: {e}")

    # ── Real Email (if SMTP configured) ──────────────────────────────────────
    email_sent = False
    if SMTP_EMAIL and SMTP_PASSWORD and SMTP_HOST:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"🚨 AMBULANCE DISPATCH — {detection_type} at {camera_label}"
            msg["From"] = SMTP_EMAIL
            msg["To"] = SMTP_EMAIL  # Send to self / emergency email
            
            html_content = (
                f"<h2>🚨 Accident Confirmed — Ambulance Dispatched</h2>"
                f"<table>"
                f"<tr><td><b>Camera</b></td><td>{camera_label} ({camera_id})</td></tr>"
                f"<tr><td><b>Type</b></td><td>{detection_type}</td></tr>"
                f"<tr><td><b>Confidence</b></td><td>{confidence}%</td></tr>"
                f"<tr><td><b>Time</b></td><td>{timestamp}</td></tr>"
                f"<tr><td><b>GPS</b></td><td>{latitude}, {longitude}</td></tr>"
                f"<tr><td><b>Map</b></td><td><a href='{maps_url}'>{maps_url}</a></td></tr>"
                f"<tr><td><b>Ref ID</b></td><td>{alert_id}</td></tr>"
                f"</table>"
            )
            msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.send_message(msg)
            email_sent = True
            print(f"[IncidentIQ] 📧 Manual Dispatch Email Sent to {SMTP_EMAIL}")
        except Exception as e:
            print(f"[IncidentIQ] ❌ Manual Dispatch Email Failed: {e}")

    # If neither is configured, keep the log as fallback
    if not sms_sent and not email_sent:
        print(
            f"\n{'='*60}\n"
            f"[DISPATCH LOGGED — NO API CONFIG]\n"
            f"{'='*60}\n"
            f"  To     : {AMBULANCE_PHONE or 'EMERGENCY'}\n"
            f"  Body   →\n{sms_body}\n"
            f"{'='*60}\n"
        )

    # Notify all dashboard clients the ambulance was dispatched
    socketio.emit("ambulance_dispatched", {
        "alertId"  : alert_id,
        "cameraId" : camera_id,
        "timestamp": datetime.now().isoformat(),
    })

    return jsonify({
        "success"   : True,
        "dispatched": True,
        "alertId"   : alert_id,
        "message"   : f"Ambulance dispatched for alert {alert_id} (mock — check server console)",
    })



def frame_to_base64(frame):
    """Convert an OpenCV frame to a base64-encoded JPEG string."""
    if cv2 is None:
        return None
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode("utf-8")


def _extract_best_detection(results):
    """Find highest-confidence detection from YOLO results."""
    best_detection = None
    best_confidence = 0.0
    best_annotated = None

    for result in results:
        if result.boxes is None or len(result.boxes) == 0:
            continue

        for box in result.boxes:
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            if conf > best_confidence:
                best_confidence = conf
                best_detection = {
                    "class_id": cls_id,
                    "class_name": CLASS_LABELS.get(cls_id, f"Class {cls_id}"),
                    "confidence": round(conf * 100, 1),
                }
                best_annotated = result.plot().copy()

    return best_detection, best_confidence, best_annotated


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Accept an image/video + location, run YOLO inference,
    and return best detection result with an annotated snapshot.
    """
    media_file = request.files.get("file") or request.files.get("video") or request.files.get("image")
    if media_file is None:
        return jsonify({"error": "No media file uploaded (expected file/video/image)"}), 400
    if cv2 is None:
        return jsonify({
            "error": "opencv-python is not installed on backend",
            "detected": False
        }), 503
    if model is None:
        return jsonify({
            "error": f"YOLO model unavailable: {model_load_error or 'model not loaded'}",
            "detected": False
        }), 503

    filename = media_file.filename or "uploaded_file"
    latitude = request.form.get("latitude", "0")
    longitude = request.form.get("longitude", "0")
    ext = os.path.splitext(filename)[1].lower()
    is_image = ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"]

    tmp_suffix = ext if ext else ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=tmp_suffix)
    media_file.save(tmp.name)
    tmp.close()

    best_detection = None
    best_confidence = 0.0
    best_frame_annotated = None
    last_frame = None
    frames_processed = 0

    try:
        if is_image:
            frame = cv2.imread(tmp.name)
            if frame is None:
                return jsonify({"error": "Could not read image file"}), 400

            results = model(frame, verbose=False, conf=0.05)
            det, conf, annotated = _extract_best_detection(results)
            frames_processed = 1
            last_frame = frame.copy()
            best_detection = det
            best_confidence = conf
            best_frame_annotated = annotated if annotated is not None else frame
        else:
            cap = cv2.VideoCapture(tmp.name)
            if not cap.isOpened():
                return jsonify({"error": "Could not open video file"}), 400

            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            # Requirement: sample 1 frame every 2 seconds
            sample_interval = max(1, int(fps * 2))

            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % sample_interval == 0:
                    frames_processed += 1
                    last_frame = frame.copy()

                    results = model(frame, verbose=False, conf=0.05)
                    det, conf, annotated = _extract_best_detection(results)
                    if det is not None and conf > best_confidence:
                        best_detection = det
                        best_confidence = conf
                        best_frame_annotated = annotated

                frame_idx += 1

            cap.release()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    # Build response
    if best_detection and best_confidence >= 0.75:
        import uuid

        alert_id = str(uuid.uuid4())
        lat_f = float(latitude)
        lng_f = float(longitude)
        # Automatic Twilio voice + SMS to YOLO_AUTO_DISPATCH_E164 (60s cooldown in try_yolo_auto_dispatch_twilio)
        dispatch_info = try_yolo_auto_dispatch_twilio(
            lat_f,
            lng_f,
            best_detection["class_name"],
            float(best_detection["confidence"]),
            alert_id,
        )
        response = {
            "detected"       : True,
            "detectionType"  : best_detection["class_name"],
            "confidence"     : f"{best_detection['confidence']}%",
            "confidenceRaw"  : best_detection["confidence"],
            "classId"        : best_detection["class_id"],
            "framesProcessed": frames_processed,
            "frameBase64"    : frame_to_base64(best_frame_annotated) if best_frame_annotated is not None else None,
            "latitude"       : lat_f,
            "longitude"      : lng_f,
            "alertId"        : alert_id,
            "autoDispatched" : bool(dispatch_info.get("ok")),
            "autoDispatchSkipped": bool(dispatch_info.get("skipped")),
            "autoDispatchReason": dispatch_info.get("reason"),
            "smsSent"        : bool(dispatch_info.get("sms_sent")),
            "cooldownRemainingSec": dispatch_info.get("cooldown_remaining_sec"),
            "dispatchDetails": dispatch_info,
            "mapsUrl"        : f"https://www.google.com/maps?q={latitude},{longitude}",
        }
    else:
        # Pick the best available frame for negative-feedback review
        neg_frame = best_frame_annotated if best_frame_annotated is not None else last_frame
        response = {
            "detected": False,
            "framesProcessed": frames_processed,
            "message": "No accidents detected in the footage.",
            "confidence": f"{round(best_confidence * 100, 1)}%" if best_confidence > 0 else "0%",
            "confidenceRaw": round(best_confidence * 100, 1),
            "frameBase64": frame_to_base64(neg_frame) if neg_frame is not None else None,
        }

    return jsonify(response)


# ── Emergency Dispatch ───────────────────────────────────────────────────────

@app.route("/dispatch", methods=["POST"])
def dispatch():
    """
    Receive hospital + accident details and send an emergency alert email.
    Falls back to console logging if SMTP is not configured.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    hospital = data.get("hospital", {})
    accident = data.get("accident", {})
    route_url = data.get("routeUrl", "")

    hospital_name = hospital.get("name", "Unknown Hospital")
    accident_type = accident.get("type", "Unknown")
    confidence = accident.get("confidence", "N/A")
    acc_lat = accident.get("latitude", 0)
    acc_lng = accident.get("longitude", 0)
    acc_time = accident.get("timestamp", datetime.now().isoformat())
    acc_location = accident.get("location", f"{acc_lat}, {acc_lng}")
    distance = hospital.get("distance", "?")
    travel_time = hospital.get("travelTime", "?")

    # Compose email
    subject = f"🚨 EMERGENCY: {accident_type} — {distance}km from {hospital_name}"

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #DC2626, #991B1B); color: white; padding: 24px; border-radius: 12px 12px 0 0;">
            <h1 style="margin: 0; font-size: 22px;">🚨 EMERGENCY ACCIDENT ALERT</h1>
            <p style="margin: 4px 0 0; opacity: 0.9;">IncidentIQ Automated Dispatch System</p>
        </div>
        <div style="background: #FEF2F2; padding: 24px; border: 1px solid #FECACA;">
            <h2 style="color: #991B1B; margin: 0 0 16px;">Accident Details</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 8px 0; color: #666;">Type</td><td style="padding: 8px 0; font-weight: bold;">{accident_type}</td></tr>
                <tr><td style="padding: 8px 0; color: #666;">Confidence</td><td style="padding: 8px 0; font-weight: bold;">{confidence}</td></tr>
                <tr><td style="padding: 8px 0; color: #666;">Location</td><td style="padding: 8px 0; font-weight: bold;">{acc_location}</td></tr>
                <tr><td style="padding: 8px 0; color: #666;">Coordinates</td><td style="padding: 8px 0;">{acc_lat}, {acc_lng}</td></tr>
                <tr><td style="padding: 8px 0; color: #666;">Time</td><td style="padding: 8px 0;">{acc_time}</td></tr>
                <tr><td style="padding: 8px 0; color: #666;">Distance</td><td style="padding: 8px 0; font-weight: bold;">{distance} km</td></tr>
                <tr><td style="padding: 8px 0; color: #666;">Est. Travel</td><td style="padding: 8px 0; font-weight: bold;">~{travel_time} min</td></tr>
            </table>
        </div>
        <div style="padding: 24px; background: white; border: 1px solid #E5E5E5; border-top: none;">
            <a href="https://www.google.com/maps?q={acc_lat},{acc_lng}" 
               style="display: inline-block; background: #DC2626; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-right: 8px;">
                📍 View Crash Site
            </a>
            <a href="{route_url}" 
               style="display: inline-block; background: #1D4ED8; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold;">
                🗺️ Get Directions
            </a>
        </div>
        <div style="padding: 16px 24px; background: #F8FAFC; border: 1px solid #E5E5E5; border-top: none; border-radius: 0 0 12px 12px; font-size: 12px; color: #94A3B8;">
            Sent automatically by IncidentIQ • YOLO Accident Detection System
        </div>
    </div>
    """

    log_entry = (
        f"\n{'='*60}\n"
        f"🚨 DISPATCH LOG — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'='*60}\n"
        f"Hospital : {hospital_name}\n"
        f"Distance : {distance} km (~{travel_time} min)\n"
        f"Accident : {accident_type} ({confidence})\n"
        f"Location : {acc_location} ({acc_lat}, {acc_lng})\n"
        f"Route    : {route_url}\n"
        f"{'='*60}\n"
    )

    # Try sending email
    email_sent = False
    if SMTP_EMAIL and SMTP_PASSWORD and SMTP_HOST:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = SMTP_EMAIL
            msg["To"] = SMTP_EMAIL  # Send to self for demo; replace with hospital email
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.send_message(msg)

            email_sent = True
            print(f"[IncidentIQ] 📧 Email sent to {SMTP_EMAIL} for {hospital_name}")
        except Exception as e:
            print(f"[IncidentIQ] ❌ Email failed: {e}")

    # Always log to console
    print(log_entry)

    return jsonify({
        "success": True,
        "emailSent": email_sent,
        "hospital": hospital_name,
        "message": f"Alert dispatched to {hospital_name}" + (" (email sent)" if email_sent else " (logged only)"),
    })


# ── Model Feedback / Retraining Data ────────────────────────────────────────

RETRAINING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retraining_data")

@app.route("/feedback", methods=["POST"])
def feedback():
    """
    Save detection feedback (true_positive / false_positive) for model retraining.
    Stores the annotated frame as JPEG and logs metadata to feedback_log.json.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    alert_id = data.get("alertId", "unknown")
    tag = data.get("tag", "unknown")  # 'true_positive' or 'false_positive'
    detection_type = data.get("detectionType", "Unknown")
    confidence = data.get("confidence", "N/A")
    confidence_raw = data.get("confidenceRaw", 0)
    frame_b64 = data.get("frameBase64")
    latitude = data.get("latitude", 0)
    longitude = data.get("longitude", 0)
    file_name = data.get("fileName", "unknown")
    timestamp = data.get("timestamp", datetime.now().isoformat())

    # Create directories
    tag_dir = os.path.join(RETRAINING_DIR, tag)
    os.makedirs(tag_dir, exist_ok=True)

    saved_frame_path = None

    # Save frame as JPEG if provided
    if frame_b64:
        try:
            import numpy as np
            frame_bytes = base64.b64decode(frame_b64)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            frame_filename = f"{alert_id}_{tag}.jpg"
            saved_frame_path = os.path.join(tag_dir, frame_filename)
            cv2.imwrite(saved_frame_path, frame_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            print(f"[IncidentIQ] 📸 Frame saved: {saved_frame_path}")
        except Exception as e:
            print(f"[IncidentIQ] ⚠️ Frame save failed: {e}")

    # Append to feedback log
    import json
    log_path = os.path.join(RETRAINING_DIR, "feedback_log.json")
    log_entry = {
        "alertId": alert_id,
        "tag": tag,
        "detectionType": detection_type,
        "confidence": confidence,
        "confidenceRaw": confidence_raw,
        "latitude": latitude,
        "longitude": longitude,
        "fileName": file_name,
        "framePath": saved_frame_path,
        "timestamp": timestamp,
        "feedbackAt": datetime.now().isoformat(),
    }

    existing_log = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                existing_log = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing_log = []

    existing_log.append(log_entry)

    with open(log_path, "w") as f:
        json.dump(existing_log, f, indent=2)

    tag_labels = {
        "true_positive": "True Positive ✅",
        "false_positive": "False Alarm ❌",
        "true_negative": "True Negative ✅",
        "false_negative": "False Negative (Missed Accident) ⚠️",
    }
    tag_label = tag_labels.get(tag, f"Unknown ({tag})")
    print(
        f"\n{'='*60}\n"
        f"🧠 FEEDBACK — {tag_label}\n"
        f"{'='*60}\n"
        f"Alert ID  : {alert_id}\n"
        f"Detection : {detection_type} ({confidence})\n"
        f"File      : {file_name}\n"
        f"Frame     : {saved_frame_path or 'N/A'}\n"
        f"{'='*60}\n"
    )

    return jsonify({
        "success": True,
        "tag": tag,
        "frameSaved": saved_frame_path is not None,
        "message": f"Feedback recorded: {tag_label}",
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "model": "accident_model_v2.pt",
        "message": "YOLO backend is running" if model is not None else "Backend running (analysis dependencies missing)",
        "analysisReady": model is not None and cv2 is not None,
        "dependencyIssue": model_load_error
    })


@app.route("/retrain", methods=["POST"])
def retrain_model():
    """
    Triggers the retraining script in a separate process.
    """
    try:
        import subprocess
        # Run retrain.py in a new process so it doesn't block the server
        # We use python executable from the current environment
        import sys
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retrain.py")
        
        subprocess.Popen([sys.executable, script_path], 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE)
        
        return jsonify({
            "success": True, 
            "message": "Retraining started in background! Check server console for progress."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Human-in-the-Loop Workflow ──────────────────────────────────────────────

# Temporary in-memory store for pending accidents (for dashboard to fetch if needed)
pending_accidents = []

@app.route("/log-accident", methods=["POST"])
def log_accident():
    """
    Endpoint for YOLO ML model to report a detected accident.
    Logs the event and alerts the dashboard via WebSockets.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    location = data.get("location", "Unknown Location")
    severity = data.get("severity", "Low")
    camera_id = data.get("camera_id", "CAM-001")
    timestamp = datetime.now().isoformat()
    
    import uuid
    alert_id = str(uuid.uuid4())

    event = {
        "alert_id": alert_id,
        "location": location,
        "severity": severity,
        "camera_id": camera_id,
        "timestamp": timestamp,
        "status": "pending_confirmation"
    }

    pending_accidents.append(event)
    if len(pending_accidents) > 100: pending_accidents.pop(0) # Keep last 100

    # Broadcast to dashboard
    socketio.emit("new_accident_alert", event)
    socketio.emit("cctv_alert", {
        "alertId": alert_id,
        "cameraId": camera_id,
        "cameraLabel": f"Manual Report: {camera_id}",
        "timestamp": timestamp,
        "latitude": 0, # Location usually provided as text in manual reports
        "longitude": 0,
        "confidence": 100,
        "detectionType": severity + " Accident",
        "location": location,
        "status": "pending"
    })

    print(f"[IncidentIQ] 🚨 New accident logged at {location} (Severity: {severity})")
    return jsonify({"success": True, "alert_id": alert_id, "message": "Accident logged. Awaiting confirmation."}), 201


@app.route("/dispatch-ambulance", methods=["POST"])
def dispatch_ambulance_manual():
    """
    Refined Human-in-the-loop dispatch. 
    Triggers Twilio logic only when manually called from the dashboard.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    location = data.get("location", "Unknown Location")
    alert_id = data.get("alertId", "N/A")
    
    # ── Twilio Real-Time Dispatch ─────────────────────────────────────────────
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and EMERGENCY_PHONE_NUMBER):
        return jsonify({"error": "Twilio not configured"}), 500

    results = {"voice": "skipped", "sms": "skipped"}

    def format_phone(num):
        num = str(num).replace(" ", "").replace("-", "")
        if not num.startswith("+"):
            return f"+91{num}" # Default to India
        return num

    to_num = format_phone(EMERGENCY_PHONE_NUMBER)
    from_num = format_phone(TWILIO_PHONE_NUMBER)

    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # 1. Voice Call (Updated as per user request)
        twiml = f'<Response><Say voice="alice">Emergency alert. An accident has been detected at the reported location. Immediate ambulance assistance is required.</Say></Response>'
        call = client.calls.create(
            to=to_num,
            from_=from_num,
            twiml=twiml
        )
        print(f"[Twilio] 📞 Manual Call SID: {call.sid}")
        results["voice"] = f"Success (SID: {call.sid})"

        # 2. SMS Alert
        import urllib.parse
        encoded_loc = urllib.parse.quote(location)
        maps_link = f"https://www.google.com/maps/search/?api=1&query={encoded_loc}"
        sms_body = f"Alert: Traffic accident detected at {location}. Dispatch ambulance. Maps: {maps_link}"
        
        message = client.messages.create(
            to=to_num,
            from_=from_num,
            body=sms_body
        )
        print(f"[Twilio] 📱 Manual SMS SID: {message.sid}")
        results["sms"] = f"Success (SID: {message.sid})"

        # Update status in memory if alert_id provided
        for entry in pending_accidents:
            if entry["alert_id"] == alert_id:
                entry["status"] = "dispatched"

        # Notify dashboard of dispatch
        socketio.emit("ambulance_dispatched", {"alert_id": alert_id, "location": location})

        return jsonify({
            "success": True, 
            "message": f"Dispatch confirmed for {location}",
            "twilio_results": results
        })

    except Exception as e:
        print(f"[Twilio] ❌ Manual dispatch failure: {e}")
        return jsonify({"error": str(e)}), 500


# ── Twilio Real-Time Incident & Disruption Management ────────────────────────

@app.route("/report-accident", methods=["POST"])
def report_accident():
    """
    Expert implementation of a real-time incident reporting route.
    Triggers an automated voice call and an SMS alert via Twilio.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    location = data.get("location", "Unknown Location")
    severity = data.get("severity", "Not Specified")
    
    # Generate Google Maps link
    import urllib.parse
    encoded_location = urllib.parse.quote(location)
    maps_link = f"https://www.google.com/maps/search/?api=1&query={encoded_location}"

    results = {
        "voice_call": {"status": "skipped", "sid": None},
        "sms_alert": {"status": "skipped", "sid": None},
        "location": location,
        "severity": severity
    }

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and EMERGENCY_PHONE_NUMBER):
        return jsonify({
            "error": "Twilio credentials not fully configured in .env",
            "missing_config": True
        }), 500

    try:
        from twilio.rest import Client as TwilioClient
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # 1. Twilio Automated Voice Call
        try:
            # TwiML for the voice response (Updated as per user request)
            twiml_content = f'<Response><Say voice="alice">Emergency alert. An accident has been detected at the reported location. Immediate ambulance assistance is required.</Say></Response>'
            
            call = client.calls.create(
                to=EMERGENCY_PHONE_NUMBER,
                from_=TWILIO_PHONE_NUMBER,
                twiml=twiml_content
            )
            print(f"[Twilio] 📞 Voice call initiated. SID: {call.sid}")
            results["voice_call"] = {"status": "success", "sid": call.sid}
        except Exception as e:
            print(f"[Twilio] ❌ Voice call failed: {e}")
            results["voice_call"] = {"status": "failed", "error": str(e)}

        # 2. Twilio SMS Alert
        try:
            sms_body = f"Alert: Traffic accident detected at {location}. Severity: {severity}. Dispatch ambulance. Maps: {maps_link}"
            
            message = client.messages.create(
                to=EMERGENCY_PHONE_NUMBER,
                from_=TWILIO_PHONE_NUMBER,
                body=sms_body
            )
            print(f"[Twilio] 📱 SMS alert sent. SID: {message.sid}")
            results["sms_alert"] = {"status": "success", "sid": message.sid}
        except Exception as e:
            print(f"[Twilio] ❌ SMS alert failed: {e}")
            results["sms_alert"] = {"status": "failed", "error": str(e)}

        return jsonify({
            "message": "Incident report processed",
            "results": results
        }), 200

    except Exception as e:
        print(f"[IncidentIQ] 💥 Critical failure in /report-accident: {e}")
        return jsonify({"error": str(e)}), 500


# ── Fully Automated Emergency Dispatch Routes ─────────────────────────────────

@app.route("/api/user-report", methods=["POST"])
def api_user_report():
    """
    Automated endpoint for manual user reporting from the website.
    Instantly triggers Twilio Voice and SMS alerts.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid payload"}), 400

    location = data.get("location", "Unknown Location")
    details = data.get("details", "")
    user_id = data.get("user_id", "Anonymous")
    lat = data.get("latitude", 0)
    lng = data.get("longitude", 0)

    import uuid
    alert_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()

    print(f"[IncidentIQ] 👤 User report from {user_id} at {location}. Triggering automation...")
    
    # 1. Execute core dispatch logic (auto call/SMS with location + description)
    twilio_results = dispatch_emergency_twilio(location, details)
    
    # 2. Synchronize with Dashboard
    event = {
        "alert_id": alert_id,
        "location": location,
        "severity": "High (Manual)",
        "camera_id": f"User: {user_id}",
        "timestamp": timestamp,
        "status": "automated_dispatch",
        "latitude": lat,
        "longitude": lng
    }
    socketio.emit("new_accident_alert", event)
    socketio.emit("cctv_alert", {
        "alertId": alert_id,
        "cameraId": f"USER-{user_id}",
        "cameraLabel": f"User Report: {user_id}",
        "timestamp": timestamp,
        "latitude": lat,
        "longitude": lng,
        "confidence": 100,
        "detectionType": "Manual Report",
        "location": location,
        "status": "dispatched"
    })

    return jsonify({
        "success": True,
        "message": "User report received. Emergency dispatch triggered.",
        "alert_id": alert_id,
        "twilio_results": twilio_results
    }), 201


@app.route("/api/ai-detection", methods=["POST"])
def api_ai_detection():
    """
    Automated endpoint for AI/YOLO model detections.
    Instantly triggers Twilio Voice and SMS alerts.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid payload"}), 400

    location = data.get("location", "Unknown Location")
    confidence = data.get("confidence_score", 0)
    camera_id = data.get("camera_id", "AI-CAM")
    lat = data.get("latitude", 0)
    lng = data.get("longitude", 0)

    import uuid
    alert_id = str(uuid.uuid4())
    timestamp = datetime.now().isoformat()

    print(f"[IncidentIQ] 🤖 AI Detection ({confidence}%) at {location} (Cam: {camera_id}). Triggering automation...")

    # 1. Execute core dispatch logic
    twilio_results = dispatch_emergency_twilio(location)

    # 2. Synchronize with Dashboard
    event = {
        "alert_id": alert_id,
        "location": location,
        "severity": "Critical (AI)",
        "camera_id": camera_id,
        "timestamp": timestamp,
        "status": "automated_dispatch",
        "latitude": lat,
        "longitude": lng
    }
    socketio.emit("new_accident_alert", event)
    socketio.emit("cctv_alert", {
        "alertId": alert_id,
        "cameraId": camera_id,
        "cameraLabel": f"AI CCTV: {camera_id}",
        "timestamp": timestamp,
        "latitude": lat,
        "longitude": lng,
        "confidence": confidence,
        "detectionType": "AI Accident",
        "location": location,
        "status": "dispatched"
    })

    return jsonify({
        "success": True,
        "message": "AI detection received. Emergency dispatch triggered.",
        "alert_id": alert_id,
        "twilio_results": twilio_results
    }), 201


if __name__ == "__main__":
    print("[IncidentIQ] 🚀 Starting SocketIO server on http://localhost:5001")
    print("[IncidentIQ] 🔌 WebSocket endpoint : ws://localhost:5001")
    print("[IncidentIQ] 📡 CCTV webhook       : POST http://localhost:5000/api/cctv-alert")
    print("[IncidentIQ] 🚑 Dispatch endpoint  : POST http://localhost:5000/api/dispatch-ambulance")
    # Use socketio.run() — eventlet provides true async WebSocket support
    socketio.run(app, host="0.0.0.0", port=5001, debug=False)
