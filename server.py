"""
IncidentIQ — YOLO Accident Detection Backend
Loads accident_model_v2.pt, analyses uploaded CCTV video files,
and brokers real-time CCTV alerts via WebSockets (Flask-SocketIO).
"""

import os
import cv2
import base64
import tempfile
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from ultralytics import YOLO

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
model = YOLO(MODEL_PATH)
print("[IncidentIQ] ✅ Model loaded successfully!")

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

def dispatch_emergency_twilio(location):
    """
    Expert implementation of a fully automated emergency dispatch system.
    Triggers both a Voice Call and an SMS Alert instantly.
    """
    import urllib.parse
    from twilio.rest import Client as TwilioClient
    
    # 1. Validation
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER and EMERGENCY_PHONE_NUMBER):
        print(f"[IncidentIQ] ⚠️ Automated dispatch aborted: Twilio credentials missing in .env")
        return {"error": "Twilio configuration missing"}

    results = {"voice": "pending", "sms": "pending"}
    
    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # 2. Automated Voice Call
        try:
            # Reusable TwiML for automated voice response
            twiml = f'<Response><Say voice="alice">Emergency. Accident detected at {location}. Ambulance required immediately.</Say></Response>'
            call = client.calls.create(
                to=EMERGENCY_PHONE_NUMBER,
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
            sms_body = f"Alert: Traffic accident reported at {location}. Dispatch ambulance. Maps: {maps_link}"
            
            message = client.messages.create(
                to=EMERGENCY_PHONE_NUMBER,
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
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode("utf-8")


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Accept a video file + location, run YOLO frame-by-frame,
    and return the best detection result with an annotated snapshot.
    """
    if "video" not in request.files:
        return jsonify({"error": "No video file uploaded"}), 400

    video_file = request.files["video"]
    filename = video_file.filename
    latitude = request.form.get("latitude", "0")
    longitude = request.form.get("longitude", "0")
    

    # Save uploaded video to a temporary file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    video_file.save(tmp.name)
    tmp.close()

    best_detection = None
    best_confidence = 0.0
    best_frame_annotated = None
    last_frame = None
    frames_processed = 0

    try:
        cap = cv2.VideoCapture(tmp.name)
        if not cap.isOpened():
            return jsonify({"error": "Could not open video file"}), 400

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30

        # Sample every N frames to keep analysis fast (analyze ~2 frames/sec)
        sample_interval = max(1, int(fps / 2))

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_interval == 0:
                frames_processed += 1
                last_frame = frame.copy()  # Keep the last processed frame

                # Run YOLO inference on every frame
                results = model(frame, verbose=False, conf=0.05)

                for result in results:
                    if result.boxes is not None and len(result.boxes) > 0:
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
                                # Draw bounding boxes on the frame
                                annotated = result.plot()
                                best_frame_annotated = annotated.copy()

            frame_idx += 1

        cap.release()

    finally:
        # Clean up temp file
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    # Build response
    if best_detection and best_confidence >= 0.75:
        import uuid
        alert_id = str(uuid.uuid4())

        # ── Auto-dispatch: SMS & Voice Call ambulance immediately on detection ─────
        # (Updated as per user request for automatic system dispatch)
        sms_sent = auto_dispatch_ambulance(
            lat            = float(latitude),
            lng            = float(longitude),
            detection_type = best_detection["class_name"],
            confidence     = best_detection["confidence"],
            alert_id       = alert_id,
        )

        # Broadcast to all dashboard clients via WebSocket
        alert_payload = {
            "alertId"      : alert_id,
            "cameraId"     : "AI-ANALYSIS",
            "cameraLabel"  : f"AI Analysis — {filename}",
            "timestamp"    : datetime.now().isoformat(),
            "latitude"     : float(latitude),
            "longitude"    : float(longitude),
            "confidence"   : best_detection["confidence"],
            "detectionType": best_detection["class_name"],
            "location"     : f"{float(latitude):.4f}, {float(longitude):.4f}",
            "status"       : "auto-dispatched" if sms_sent else "pending",
        }
        socketio.emit("cctv_alert", alert_payload)
        socketio.emit("new_accident_alert", {
            "alert_id": alert_id,
            "location": alert_payload["location"],
            "severity": "High",
            "camera_id": "AI-ANALYSIS",
            "timestamp": alert_payload["timestamp"],
            "status": alert_payload["status"]
        })

        response = {
            "detected"       : True,
            "detectionType"  : best_detection["class_name"],
            "confidence"     : f"{best_detection['confidence']}%",
            "confidenceRaw"  : best_detection["confidence"],
            "classId"        : best_detection["class_id"],
            "framesProcessed": frames_processed,
            "frameBase64"    : frame_to_base64(best_frame_annotated) if best_frame_annotated is not None else None,
            "latitude"       : float(latitude),
            "longitude"      : float(longitude),
            "alertId"        : alert_id,
            "autoDispatched" : True,
            "smsSent"        : sms_sent,
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
    return jsonify({"status": "ok", "model": "accident_model_v2.pt", "message": "YOLO backend is running"})


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
    
    # 1. Execute core dispatch logic
    twilio_results = dispatch_emergency_twilio(location)
    
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
