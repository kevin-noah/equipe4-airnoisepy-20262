"""
airnoisepy.flight.opensky : Récupération et nettoyage des trajectoires ADS-B depuis OpenSky Network
Responsable : Syndia Jean
Référence :
- https://openskynetwork.github.io/opensky-api/python.html
- https://openskynetwork.github.io/opensky-api/python.html#opensky_api.FlightData
- opensky-network.org et ECAC Doc 29, vol 2 - segmentation de trajectoire
"""

import math
import os
import numpy as np
import requests

# Import conditionnel de rasterio (utile pour la lecture du MNT SRTM)
try:
    import rasterio
    from rasterio.transform import rowcol
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False


#Import conditionnel de FlightOperation (utile pour éviter un import circulaire)
try:
    from airnoisepy.flight.operation import FlightOperation
    FLIGHT_OPERATION_AVAILABLE = True
except ImportError:
    FLIGHT_OPERATION_AVAILABLE = False


#Variable globale

#Seuil de gap temporel pour l'interpolation en seconde
DEFAULT_MAX_GAP_S = 10

#Centre de l'aéroport YUL en km
YUL_LATITUDE_KM, YUL_LONGITUDE_KM = 45.4706, -73.7408

#Altitude maximale au dessus du sol en ft et en m
MAX_ALTITUDE_AGL_FT = 10000
MAX_ALTITUDE_AGL_M = MAX_ALTITUDE_AGL_FT * 0.3048

#Rayon de filtrage par défaut autour de YUL en km
DEFAULT_RADIUS_KM = 25

BASE_URL = 'https://opensky-network.org/api'


#Classe principale

class OpenSkyFetcher:
    """
    Récupère les trajectoires ADS-B depuis OpenSky Network et les nettoie
    pour les rendre exploitables par FlightOperation et NoiseCalculator.

    OpenSky collecte les signaux ADS-B émis par les avions en vol (comme un
    radar civil ouvert). Les données brutes contiennent des erreurs (sauts
    d'altitude, trous, altitude barométrique ≠ altitude réelle au-dessus du
    sol). Cette classe prend en charge tout le pipeline de nettoyage.

    Paramètres:
    - username : str (Identifiant openSky Network) ou None (accès public = limité aux dernières 1h seulement)
                 Recommandé : os.environ.get('OPENSKY_USER').
    - password : str (Mot de passe OpenSky Network) ou None
                 IMPORTANT : ne jamais mettre les identifiants en dur dans le code.
    - dem_path : str ou None
                 Chemin vers le fichier SRTM 30m (yul_dem.tif).  Si fourni, le modèle
                 numérique de terrain est chargé pour la correction altitude AGL.

    Attributs publics:
    - username  : str ou None
    - password  : str ou None
    - dem       : rasterio.DatasetReader ou None — fichier SRTM ouvert
    - BASE_URL  : str — 'https://opensky-network.org/api'

    Exemple:
    - fetcher = OpenSkyFetcher(
                  username=os.environ.get('OPENSKY_USER'),
                  password=os.environ.get('OPENSKY_PASS'),
                  dem_path='data/srtm/yul_dem.tif')
    """

    BASE_URL = BASE_URL

    def __init__(self, username=None, password=None, dem_path=None):
        self.username = username
        self.password = password
        self.dem = None

        if dem_path is not None:
            if not RASTERIO_AVAILABLE:
                raise ImportError("rasterio est requis pour la correction d'altitude AGL. Installez-le avec pip.install rasterio")
            if not os.path.isfile(dem_path):
                raise FileNotFoundError(f"Fichier SRTM introuvable : {dem_path}")
            self.dem = rasterio.open(dem_path)

#Méthodes publiques

    def fetch_flights(self, airport, begin, end):
        """
        Récupère la liste des vols (arrivées + départs) pour un aéroport
        sur une période donnée (période fourni par l'utilisateur).

        Paramètres:
        - airport : str (Code OACI de l'aéroport ex: 'CYUL')
        - begin : int (Timestamp UNIX de début de la période)
        - end : int (Timestamp UNIX de fin de la période)
                Fenêtre maximale autorisée par OpenSky : 7 jours.

        Retourne:
        - list[dict] : Liste de vols fusionnant arrivées et départs.
                     Chaque dict contient au minimum : 'icao24', 'callsign', 'firstSeen', 'lastSeen', 'estDepartureAirport', 'estArrivalAirport'.
        Exemple:
        - import time
        - now   = int(time.time())
        - begin = now - 86_400   # il y a 24h
        - fetcher = OpenSkyFetcher(username='...', password='...', dem_path='...')
        - flights = fetcher.fetch_flights('CYUL', begin, now)
        - print(f"{len(flights)} vols trouvés")
        """

        #Validation de la fenêtre temporelle en prenant en compte la limite d'OpenSky
        if (end - begin) > 7 * 86400 :
            raise ValueError("La fenêtre temporelle est trop grande et dépasse les 7 jours limite d'OpenSky")
        authentification = (self.username, self.password) if self.username else None
        parametres = {"airport": airport, "begin": begin, "end": end}
        arrivals = self._api_get("/flights/arrival", parametres, authentification)
        departures = self._api_get("/flights/departure", parametres, authentification)

        all_flights = arrivals + departures
        seen = set()
        unique = []
        for flight in all_flights:
            key = (flight.get("icao24", ""), flight.get("firstSeen", 0))
            if key not in seen:
                seen.add(key)
                unique.append(flight)
        return unique

    def fetch_track(self, icao24, time):
        """
        Récupère la trajectoire complète d'un avion pour un vol donné.

        Paramètres:
        - icao24 : str (Identifiant hexadécimal de l'avion ex: 'c07e32' pour Air Canada)
        - time : int (Timestamp UNIX du vol - dans la fenêtre du vol, pas nécessairement exactement à firstSeen)

        Retourne:
        - dict: Trajectoire brute au format OpenSky :
                {'icao24': ..., 'callsign': ..., 'path': [[time, latitude, longitude, baro_altitude, true_track, on_ground], ...]}
            où :
              time   = timestamp UNIX
              latitude = latitude (degrés)
              longitude = longitude (degrés)
              baro_altitude = altitude barométrique (mètres)
              true_track = cap magnétique (degrés)
              on_ground = True si l'avion est au sol

        Exemple:
        - track = fetcher.fetch_track('c07e32', 1748649600)
        - print(f"{len(track['path'])} points de trajectoire")
        """
        authentification = (self.username, self.password) if self.username else None
        parametres = {"icao24": icao24, "time": time}
        return self._api_get("/tracks/all", parametres, authentification)

    def fetch_realtime(self, bbox=(45.30, 45.65, -74.05, -73.40)):
        """
        Récupère les avions en vol en temps réel dans la zone YUL.

        Ne nécessite pas de compte OpenSky (données publiques).

        Paramètres:
        bbox : tuple de 4 float
            Boîte englobante (lat_min, lat_max, lon_min, lon_max).
            Valeur par défaut centrée sur YUL, rayon ~25 km.

        Retourne:
        list[dict] : Liste d'avions en vol, chaque dict contient :
                    {'icao24': ..., 'callsign': ..., 'path': [[time, latitude, longitude, baro_altitude, true_track, on_ground], ...]}

        Exemple:
        - avions = fetcher.fetch_realtime()
        - print(f"{len(avions)} avions en vol autour de YUL")
        """
        latitude_min, latitude_max, longitude_min, longitude_max = bbox
        parametres = {"lamin": latitude_min, "lamax": latitude_max,
                      "lomin": longitude_min, "lomax": longitude_max}
        response = self._api_get("/states/all", parametres, authentification=None)

        states = response.get("states", []) if isinstance(response, dict) else []
        avions = []
        for state in states:
            if state is None or len(state) < 9:
                continue
            avions.append({
                "icao24": state[0],
                "callsign": (state[1] or "").strip(),
                "longitude": state[5],
                "latitude": state[6],
                "baro_altitude": state[13] if len(state) > 13 else None,
                "on_ground": state[8],
                "velocity": state[9] if len(state) > 9 else None,
                "true_track": state[10] if len(state) > 10 else None,
                "vertical_rate": state[11] if len(state) > 11 else None,
            })
        return avions

    def clean_track(self, track_data):
        """
        Nettoie une trajectoire brute OpenSky et ajoute l'altitude AGL.

        Pipeline appliqué dans l'ordre :
          1. _remove_outliers() — supprimer les sauts d'altitude aberrants
          2. _interpolate_gaps() — combler les trous temporels < max_gap_s
          3. _correct_altitude_agl() — corriger l'altitude (barométrique → AGL)
          4. _filter_yul_zone() — garder seulement la zone YUL

        Paramètres:
        - track_data : dict
            Trajectoire brute OpenSky (sortie de fetch_track()).

        Retourne:
        list[dict] : Points nettoyés, chaque dict contient :
            'time', 'latitude', 'longitude', 'baro_altitude', 'altitude_agl', 'velocity', 'on_ground'.

        Notes
        -----
        L'altitude barométrique (baro_altitude) est relative au niveau de la mer
        (QNH). Pour le calcul acoustique ECAC Doc 29, on a besoin de l'altitude
        AGL (Above Ground Level). La différence est l'élévation du terrain
        sous l'avion, lue dans le fichier SRTM.

        Exemple:
        - track  = fetcher.fetch_track('c07e32', 1748649600)
        - points = fetcher.clean_track(track)
        - print(f"{len(points)} points après nettoyage")
        """

        raw_path = track_data.get("path", [])
        if not raw_path:
            return []

        points = []
        for entry in raw_path:
            if entry is None or len(entry) < 6:
                continue
            time, latitude, longitude, baro_altitude, true_track, on_ground = entry[:6]
            if latitude is None or longitude is None:
                continue
            points.append({
                "time": time,
                "latitude": latitude,
                "longitude": longitude,
                "baro_altitude": baro_altitude if baro_altitude is not None else 0.0,
                "true_track": true_track if true_track is not None else 0.0,
                "on_ground": bool(on_ground),
                "velocity": None,
            })
        if not points:
            return []

        points = self._compute_speed(points)

        points = self._remove_outliers(points)
        points = self._interpolate_gaps(points)
        points = self._correct_altitude_agl(points)
        points = self._filter_yul_zone(points)

        return points

    def to_flight_operation(self, icao24, track_data):
        """
        Convertit une trajectoire brute OpenSky en objet FlightOperation.

        Paramètres:
        - icao24 : str (Identifiant hexadécimal de l'avion)
        - track_data : dict (Trajectoire brute OpenSky - sortie de fetch_track())

        Retourne:
        - FlightOperation : Objet prêt à être passé à NoiseCalculator.

        Exemple:
        - track = fetcher.fetch_track('c07e32', 1748649600)
        - fo    = fetcher.to_flight_operations('c07e32', track)
        - print(fo.operation_type)   # 'departure' ou 'arrival'
        """

        if not FLIGHT_OPERATION_AVAILABLE:
            raise ImportError("FlightOperation n'est pas disponible. Assurez-vous que airnoisepy/flight/operation.py est présent.")
        clean_points = self.clean_track(track_data)
        if not clean_points:
            raise ValueError(f"Trajectoire vide après nettoyage pour l'avion {icao24}")

        aircraft_type = self._map_aircraft_type(icao24)
        callsign = (track_data.get("callsign") or icao24).strip()
        waypoints = [{
            "time":          p["time"],
            "latitude":      p["latitude"],
            "longitude":     p["longitude"],
            "baro_altitude": p["baro_altitude"],
            "altitude_agl":  p.get("altitude_agl", p["baro_altitude"]),
            "velocity":      p.get("velocity", 0.0),
        } for p in clean_points]

        opensky_format = {
            "icao24": icao24,
            "callsign": callsign,
            "aircraft_type": aircraft_type,
            "path": [
                [p["time"], p["latitude"], p["longitude"],
                 p["baro_altitude"], p.get("true_track", 0.0), p["on_ground"]]
                for p in clean_points
            ],
            "waypoints": waypoints,
        }
        return FlightOperation.from_opensky(opensky_format)



#Méthodes privées
#Méthodes de nettoyage

    def _remove_outliers(self, points, window=15, z_thresh=2.0):
        """
        Supprime les points dont l'altitude barométrique est aberrante.
        Un point est supprimé si |z| > z_thresh.

        Paramètres:
        - points : list[dict]
        - window : int (Taille de la fenêtre glissante - défaut : 5 points)
        - z_thresh : float (Seuil de z-score au-delà duquel un point est supprimé - défaut : 3)

        Retourne:
        - list[dict]

        Notes:
        Parfois un avion reporte une altitude de -9999 ou +99999 ft par erreur. Un z-score > 3 signifie une valeur à plus de 3
        écarts-types de la moyenne locale, statistiquement improbable pour
        une trajectoire réelle.
        """
        if len(points) < window:
            return points

        altitudes = np.array([p["baro_altitude"] for p in points], dtype=float)
        cleaned = []

        for i, p in enumerate(points):
            lo = max(0, i - window // 2)
            hi = min(len(points), lo + window)
            window_vals = altitudes[lo:hi]

            mean = np.mean(window_vals)
            std = np.std(window_vals)

            if std < 1e-6:
                cleaned.append(p)
            elif abs(p["baro_altitude"] - mean) / std <= z_thresh:
                cleaned.append(p)
        return cleaned

    def _interpolate_gaps(self, points, max_gaps = DEFAULT_MAX_GAP_S):
        """
        Comble les trous temporels courts par interpolation linéaire.

        Paramètres:
        - points : list[dict]
        - max_gap : int (Seuil en secondes. Si gap <= max_gap → interpolation linéaire
                                            Si gap > max_gap_s → segmentation - on n'interpole pas).

        Retourne:
        - list[dict] : Points originaux + points interpolés insérés aux bons endroits.

        Notes:
        ADS-B envoie un signal environ toutes les 5 secondes. Des trous
        apparaissent quand l'avion est hors couverture radar ou quand le signal
        est perdu. Au-delà de max_gap, l'interpolation linéaire n'est pas
        fiable (l'avion peut avoir manœuvré entre les deux points connus).
        """
        if len(points) < 2:
            return points
        result = [points[0]]

        for i in range(1, len(points)):
            previous = points[i - 1]
            current = points[i]
            gap = current["time"] - previous["time"]

            if 0 < gap <= max_gaps:
                n_missing = int(gap // 5) - 1
                for k in range(1, n_missing + 1):
                    alpha = k / (n_missing + 1)
                    interp = {
                        "time": int(previous["time"] + alpha * gap),
                        "latitude": previous["latitude"] + alpha * (current["latitude"] - previous["latitude"]),
                        "longitude": previous["longitude"] + alpha * (current["longitude"] - previous["longitude"]),
                        "baro_altitude": previous["baro_altitude"] + alpha * (current["baro_altitude"] - previous["baro_altitude"]),
                        "true_track": previous.get("true_track", 0.0),
                        "on_ground": False,
                        "velocity": previous.get("velocity", 0.0),
                    }
                    result.append(interp)
            result.append(current)
        return result

    def _correct_altitude_agl(self, points):
        """
        Ajoute l'altitude AGL (Above Ground Level) à chaque point.

        Si un fichier SRTM a été chargé, on soustrait l'élévation du terrain
        sous l'avion (lue dans le raster) de l'altitude barométrique.
        Sans fichier SRTM, alt_agl = alt_baro (approximation).

        Paramètres:
        points : list[dict]

        Retourne:
        list[dict]: Même liste avec clé 'alt_agl' ajoutée.

        Exemple : avion à alt_baro = 500 m au-dessus de Montréal
        (élévation terrain ≈ 29 m d'après SRTM).
        alt_agl = 500 - 29 = 471 m au-dessus du sol.

        C'est l'altitude alt_agl qui est utilisée dans le calcul du
        slant-range 3D par NoiseCalculator.
        """

        for p in points:
            if self.dem is not None:
                try:
                    row, col = rowcol(self.dem.transform, p["longitude"], p["latitude"])
                    elevation = float(self.dem.read(1)[row, col])
                    if elevation < -500 or elevation > 5000:
                        elevation = 0.0
                except Exception:
                    elevation = 0.0
            else:
                elevation = 0.0
            p["altitude_agl"] = max(0.0, p["baro_altitude"] - elevation)
        return points

    def _filter_yul_zone(self, points, radius_km=DEFAULT_RADIUS_KM):
        """
        Conserve uniquement les points dans la zone d'intérêt autour de YUL.

        Un point est conservé si et seulement si :
          - distance au centre de YUL < radius_km (défaut 25 km)
          - altitude AGL < MAX_ALT_AGL_M (défaut 3 048 m / 10 000 ft)

        Paramètres:
        - points : list[dict]
        - radius_km : float

        Retourne:
        - list[dict]

        Notes:
        Au-delà de 25 km, l'avion est trop loin pour impacter significativement
        les riverains de YUL. Au-delà de 10 000 ft AGL, la contribution sonore
        au sol est négligeable (< 40 dB à cette distance). Ce filtrage réduit
        aussi fortement la quantité de données à traiter dans NoiseCalculator.
        """

        filtered = []
        for p in points:
            distance_km = self._haversine_distance_km(p["latitude"], p["longitude"], YUL_LATITUDE_KM, YUL_LONGITUDE_KM)
            altitude_agl = p.get("altitude_agl", p["baro_altitude"])
            if distance_km <= radius_km and altitude_agl <= MAX_ALTITUDE_AGL_M:
                filtered.append(p)
        return filtered



#Méthodes utiles

    def _api_get(self, endpoint, parametres, authentification):
        """
        Effectue un appel GET à l'API OpenSky et retourne le JSON décodé.

        Paramètres:
        - endpoint : str (Chemin de l'endpoint ex: '/flights/arrival')
        - params : dict (Paramètres de la requête)
        - auth : tuple ou None (username, password ou None pour accès anonyme)

        Retourne:
        - list ou dict (Réponse JSON décodée)
        """

        url = self.BASE_URL + endpoint
        response = requests.get(url, params=parametres, auth=authentification, timeout = 30)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _haversine_distance_km(lat1, lon1, lat2, lon2):
        """
        Calcule la distance entre deux points GPS sou forme d'un grand cercle
        Paramètres:
        lat1, lon1 : float — coordonnées du point 1 (degrés décimaux)
        lat2, lon2 : float — coordonnées du point 2 (degrés décimaux)

        Retourne:
        - float : Distance en kilomètres.
        """
        R = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _compute_speed(self, points):
        """
        Calcule la vitesse (m/s) entre points consécutifs.

        La vitesse au point i est estimée comme la distance 3D entre les points
        i-1 et i+1 divisée par la différence de temps correspondante. Pour le premier et le dernier point, on utilise
        des différences avant/arrière.

        Paramètres:
        - points : list[dict]

        Retourne:
        - list[dict] : Même liste avec clé 'velocity' (m/s) renseignée.
        """

        n = len(points)
        for i, p in enumerate(points):
            if n == 1:
                p["velocity"] = 0.0
                continue
            if i == 0:
                a, b = points[0], points[1]
            elif i == n - 1:
                a, b = points[- 2], points[-1]
            else:
                a, b = points[i - 1], points[i + 1]
            dt = b["time"] - a["time"]
            if dt == 0:
                p["velocity"] = 0.0
                continue
            dx = self._haversine_distance_km(a["latitude"], a["longitude"], b["latitude"], b["longitude"]) * 1000
            dz = abs(b["baro_altitude"] - a["baro_altitude"])
            distance_3d = math.sqrt(dx**2 + dz**2)
            p["velocity"] = distance_3d / abs(dt)
        return points

    def _map_aircraft_type(self, icao24):
        """
        Retourne le code OACI du type d'aéronef depuis son identifiant ICAO24.

        Paramètres:
        - icao24 : str (Code hexadécimal de l'avion ex: 'c07e32')

        Retourne:
        - Code OACI (ex: 'A320'). 'A320' si inconnu.
        """

        ICAO24_TO_TYPE = {
            "c07e32": "A320",  # Air Canada A320
            "c04b3a": "B738",  # WestJet 737-800
            "c06184": "A321",  # Air Canada A321
            "c05140": "DH8D",  # Jazz Aviation Q400
            "c06c48": "B77W",  # Air Canada 777-300ER
            "c07a97": "A220",  # Air Canada A220-300
        }
        aircraft_type = ICAO24_TO_TYPE.get(icao24.lower(), None)
        if aircraft_type is None:
            aircraft_type = "A320"
        return aircraft_type
