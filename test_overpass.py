import requests

lat = 12.9716
lng = 77.5946
radius = 10000

query = f"""
[out:json][timeout:25];
(
    node["amenity"="hospital"](around:{radius},{lat},{lng});
    way["amenity"="hospital"](around:{radius},{lat},{lng});
    node["amenity"="clinic"](around:{radius},{lat},{lng});
    node["healthcare"="hospital"](around:{radius},{lat},{lng});
);
out center body;
"""

url = "https://overpass-api.de/api/interpreter"
print(f"Querying {url}...")

try:
    response = requests.post(url, data={"data": query})
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Elements found: {len(data.get('elements', []))}")
    else:
        print("Error:", response.text)
except Exception as e:
    print("Exception:", e)
