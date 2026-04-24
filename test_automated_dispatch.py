import requests
import json

def test_automated_routes():
    base_url = "http://localhost:5001"
    
    # 1. Test User Report
    print("Testing /api/user-report...")
    user_payload = {
        "location": "Anna Nagar Signal",
        "details": "Minor accident near metro",
        "user_id": "TEST_USER_99"
    }
    try:
        r1 = requests.post(f"{base_url}/api/user-report", json=user_payload, timeout=5)
        print(f"Status: {r1.status_code}")
        print(f"Response: {json.dumps(r1.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

    print("-" * 30)

    # 2. Test AI Detection
    print("Testing /api/ai-detection...")
    ai_payload = {
        "location": "T-Nagar Junction",
        "confidence_score": 95.8,
        "camera_id": "CAM-AI-999"
    }
    try:
        r2 = requests.post(f"{base_url}/api/ai-detection", json=ai_payload, timeout=5)
        print(f"Status: {r2.status_code}")
        print(f"Response: {json.dumps(r2.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_automated_routes()
