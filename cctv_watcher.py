"""
cctv_watcher.py — IncidentIQ CCTV Live Accident Detector
=========================================================
Runs YOLO inference on a CCTV video file or camera stream.

False-Positive Management:
  • Requires the model to detect "accident" with > 80% confidence
    for CONSECUTIVE_FRAMES (30) frames in a row before triggering.
  • After a trigger, a per-camera COOLDOWN_SECONDS (60) lockout
    prevents duplicate alerts from the same feed.

On confirmation:
  • Saves a JPEG snapshot to ./snapshots/<cameraId>_<timestamp>.jpg
  • POSTs a JSON alert to the backend webhook: POST /api/cctv-alert

Usage:
  python cctv_watcher.py                  # Uses built-in test sources
  python cctv_watcher.py --source 0       # Webcam (index 0)
  python cctv_watcher.py --source path/to/cctv.mp4
"""

import os
import sys
import cv2
import json
import time
import requests
import argparse
from datetime import datetime

# ── Try to load .env ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Load YOLO model ───────────────────────────────────────────────────────────
try:
    from ultralytics import YOLO
except ImportError:
    print("[cctv_watcher] ❌ ultralytics not installed. Run: pip install ultralytics")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH        = os.path.join(BASE_DIR, "accident_model_v2.pt")
SNAPSHOTS_DIR     = os.path.join(BASE_DIR, "snapshots")
BACKEND_WEBHOOK   = os.getenv("BACKEND_WEBHOOK", "http://localhost:5000/api/cctv-alert")

# False-Positive thresholds
CONFIDENCE_THRESHOLD = 0.80   # 80% minimum confidence
CONSECUTIVE_FRAMES   = 30     # frames in a row to confirm
COOLDOWN_SECONDS     = 60     # seconds before same camera can alert again

# Camera definitions — add / edit entries here
# Each entry: { "id": str, "source": int|str, "lat": float, "lng": float }
DEFAULT_CAMERAS = [
    {
        "id"    : "CAM-01",
        "source": os.path.join(BASE_DIR, "test_cctv.mp4"),   # swap for 0 = webcam
        "lat"   : 13.0827,
        "lng"   : 80.2707,
        "label" : "Junction A — Anna Salai"
    },
    # Add more cameras here:
    # {"id": "CAM-02", "source": "rtsp://...", "lat": 13.05, "lng": 80.22, "label": "Flyover B"},
]

# ── State tracking per camera ─────────────────────────────────────────────────
class CameraState:
    def __init__(self, camera_cfg):
        self.cfg             = camera_cfg
        self.consecutive     = 0     # consecutive frames above threshold
        self.last_alert_time = 0.0   # epoch seconds of last trigger

    @property
    def in_cooldown(self):
        return (time.time() - self.last_alert_time) < COOLDOWN_SECONDS

    def reset(self):
        self.consecutive = 0


# ── Helpers ───────────────────────────────────────────────────────────────────
def save_snapshot(frame, camera_id: str) -> tuple[str, str]:
    """Save a frame as JPEG, return (local_path, public_url)."""
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{camera_id}_{ts}.jpg"
    path     = os.path.join(SNAPSHOTS_DIR, filename)
    cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    url      = f"http://localhost:5000/snapshots/{filename}"
    print(f"[cctv_watcher] 📸 Snapshot saved: {path}")
    return path, url


def post_alert(camera_state: CameraState, frame, confidence: float, detection_type: str):
    """Save snapshot and POST JSON webhook to the backend."""
    cam   = camera_state.cfg
    _path, url = save_snapshot(frame, cam["id"])

    payload = {
        "cameraId"      : cam["id"],
        "cameraLabel"   : cam.get("label", cam["id"]),
        "timestamp"     : datetime.now().isoformat(),
        "latitude"      : cam["lat"],
        "longitude"     : cam["lng"],
        "snapshotUrl"   : url,
        "confidence"    : round(confidence * 100, 1),
        "detectionType" : detection_type,
    }

    print(
        f"\n{'='*60}\n"
        f"🚨 CONFIRMED ACCIDENT — {cam['id']} ({cam.get('label','')})\n"
        f"   Confidence : {payload['confidence']}%\n"
        f"   Snapshot   : {url}\n"
        f"   Posting to : {BACKEND_WEBHOOK}\n"
        f"{'='*60}\n"
    )

    try:
        resp = requests.post(BACKEND_WEBHOOK, json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"[cctv_watcher] ✅ Alert accepted by backend.")
        else:
            print(f"[cctv_watcher] ⚠️  Backend returned {resp.status_code}: {resp.text[:200]}")
    except requests.exceptions.ConnectionError:
        print(f"[cctv_watcher] ❌ Backend unreachable at {BACKEND_WEBHOOK}. Is server.py running?")
    except Exception as e:
        print(f"[cctv_watcher] ❌ Failed to post alert: {e}")

    # Mark cooldown
    camera_state.last_alert_time = time.time()
    camera_state.reset()


# ── Per-camera processing loop ────────────────────────────────────────────────
def process_camera(model, cam_cfg: dict):
    """Open one CCTV source and run inference until stream ends or Ctrl-C."""
    state  = CameraState(cam_cfg)
    source = cam_cfg["source"]

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[cctv_watcher] ⚠️  Cannot open source for {cam_cfg['id']}: {source}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    print(f"[cctv_watcher] 📹 Watching {cam_cfg['id']} — {cam_cfg.get('label', source)} @ {fps:.0f} fps")

    while True:
        ret, frame = cap.read()
        if not ret:
            print(f"[cctv_watcher] Stream ended for {cam_cfg['id']}. Rewinding…")
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)   # loop video file
            state.reset()
            continue

        # Skip processing if in cooldown
        if state.in_cooldown:
            remaining = int(COOLDOWN_SECONDS - (time.time() - state.last_alert_time))
            if remaining % 10 == 0:
                print(f"[cctv_watcher] 🔒 {cam_cfg['id']} cooldown — {remaining}s remaining")
            time.sleep(0.033)
            continue

        # Run YOLO
        results = model(frame, verbose=False, conf=CONFIDENCE_THRESHOLD)

        accident_detected = False
        best_conf        = 0.0
        best_type        = "Accident"

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                conf   = float(box.conf[0])
                cls_id = int(box.cls[0])
                # Accept any detection class as "accident" since this model
                # is accident-specific. Adjust class IDs here if needed.
                if conf >= CONFIDENCE_THRESHOLD:
                    accident_detected = True
                    if conf > best_conf:
                        best_conf  = conf
                        best_type  = model.names.get(cls_id, "Accident")

        if accident_detected:
            state.consecutive += 1
            print(
                f"[{cam_cfg['id']}] ⚠️  High-confidence detection "
                f"({best_conf*100:.1f}%) — frame {state.consecutive}/{CONSECUTIVE_FRAMES}"
            )

            if state.consecutive >= CONSECUTIVE_FRAMES:
                # Annotate the confirming frame
                annotated = results[0].plot() if results else frame
                post_alert(state, annotated, best_conf, best_type)
        else:
            if state.consecutive > 0:
                print(f"[{cam_cfg['id']}] ✅ Chain broken at frame {state.consecutive} — resetting")
            state.reset()

        # Throttle to ~15 fps for inference (balance speed vs. accuracy)
        time.sleep(max(0, 1.0 / 15 - 0.01))

    cap.release()


# ── Main entry ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="IncidentIQ CCTV Watcher")
    parser.add_argument("--source", default=None,
                        help="Override camera source (path, RTSP URL, or int index)")
    parser.add_argument("--camera-id", default="CAM-01",
                        help="Camera ID to use when --source is overridden")
    parser.add_argument("--lat", type=float, default=13.0827, help="GPS latitude override")
    parser.add_argument("--lng", type=float, default=80.2707, help="GPS longitude override")
    parser.add_argument("--model", default=MODEL_PATH, help="Path to YOLO .pt model file")
    args = parser.parse_args()

    print(f"[cctv_watcher] 🔧 Loading YOLO model: {args.model}")
    if not os.path.exists(args.model):
        print(f"[cctv_watcher] ❌ Model not found: {args.model}")
        sys.exit(1)
    model = YOLO(args.model)
    print(f"[cctv_watcher] ✅ Model loaded. Confidence threshold: {CONFIDENCE_THRESHOLD*100:.0f}%")
    print(f"[cctv_watcher] 🔢 Consecutive frames required: {CONSECUTIVE_FRAMES}")
    print(f"[cctv_watcher] ⏳ Cooldown after alert: {COOLDOWN_SECONDS}s")
    print(f"[cctv_watcher] 📡 Webhook endpoint: {BACKEND_WEBHOOK}")
    print()

    # If --source provided, override camera list with single camera
    cameras = DEFAULT_CAMERAS
    if args.source is not None:
        src = int(args.source) if args.source.isdigit() else args.source
        cameras = [{
            "id"    : args.camera_id,
            "source": src,
            "lat"   : args.lat,
            "lng"   : args.lng,
            "label" : f"Manual source — {args.camera_id}",
        }]

    if len(cameras) == 1:
        # Single camera: run in main thread (easier Ctrl-C)
        try:
            process_camera(model, cameras[0])
        except KeyboardInterrupt:
            print("\n[cctv_watcher] Stopped.")
    else:
        # Multiple cameras: run in threads
        import threading
        threads = []
        for cam in cameras:
            t = threading.Thread(target=process_camera, args=(model, cam), daemon=True)
            t.start()
            threads.append(t)
            print(f"[cctv_watcher] 🚀 Started thread for {cam['id']}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[cctv_watcher] Stopped all camera threads.")


if __name__ == "__main__":
    main()
