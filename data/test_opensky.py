"""
Test de connexion OpenSky Network — données ADS-B historiques autour de YUL
Usage : python3 test_opensky.py <username> <password>
"""
import sys
import json
import requests
from datetime import datetime, timezone

if len(sys.argv) != 3:
    print("Usage: python3 test_opensky.py <username> <password>")
    sys.exit(1)

username, password = sys.argv[1], sys.argv[2]

# Bbox YUL : lat 45.30–45.65, lon -74.05–-73.40
BBOX = {"lamin": 45.30, "lomin": -74.05, "lamax": 45.65, "lomax": -73.40}

print("=== Test 1 : Données temps réel (sans auth) ===")
r = requests.get("https://opensky-network.org/api/states/all", params=BBOX, timeout=10)
states = r.json().get("states", []) or []
print(f"Avions en vol autour YUL : {len(states)}")

print("\n=== Test 2 : Données historiques (avec compte) ===")
# Hier à 14h UTC
now = datetime.now(timezone.utc)
t_end = int(now.replace(hour=14, minute=0, second=0, microsecond=0).timestamp())
t_start = t_end - 3600  # 1 heure

params = {**BBOX, "begin": t_start, "end": t_end}
r2 = requests.get(
    "https://opensky-network.org/api/flights/arrival",
    params={"airport": "CYUL", "begin": t_start, "end": t_end},
    auth=(username, password),
    timeout=15
)
print(f"Status : {r2.status_code}")
if r2.status_code == 200:
    flights = r2.json()
    print(f"Vols arrivée CYUL sur 1h : {len(flights)}")
    if flights:
        f = flights[0]
        print(f"Exemple : {f.get('callsign','?')} | type={f.get('estAircraftType','?')} | "
              f"départ={f.get('estDepartureAirport','?')}")
        print(f"\nSauvegarde dans data/sample_flights.json ...")
        with open("data/sample_flights.json", "w") as fout:
            json.dump(flights[:20], fout, indent=2)
        print("OK — 20 vols sauvegardés.")
elif r2.status_code == 401:
    print("Identifiants incorrects.")
elif r2.status_code == 403:
    print("Accès refusé — compte non académique ou quota dépassé.")
else:
    print("Réponse :", r2.text[:300])
