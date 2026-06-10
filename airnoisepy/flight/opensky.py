"""
airnoisepy.flight.opensky : Récupération et nettoyage des trajectoires ADS-B depuis OpenSky Network
Responsable : Syndia Jean
Référence : opensky-network.org et ECAC Doc 29, vol 2 - segmentation de trajectoire
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