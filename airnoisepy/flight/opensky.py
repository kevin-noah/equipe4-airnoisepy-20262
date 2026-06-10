"""
airnoisepy.flight.opensky : Récupération et nettoyage des trajectoires ADS-B depuis OpenSky Network
Responsable : Syndia Jean
Référence :
- https://openskynetwork.github.io/opensky-api/python.html
- https://openskynetwork.github.io/opensky-api/python.html#opensky_api.FlightData
- opensky-network.org et ECAC Doc 29, vol 2 - segmentation de trajectoire
"""
import os
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
        parametres = {"latitude_min": latitude_min, "latitude_max": latitude_max,
                      "longitude_min": longitude_min, "longitude_max": longitude_max}
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
            })
        return avions




#Méthodes privées

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