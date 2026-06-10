"""
airnoisepy.flight.opensky : Récupération et nettoyage des trajectoires ADS-B depuis OpenSky Network
Responsable : Syndia Jean
Référence : opensky-network.org et ECAC Doc 29, vol 2 - segmentation de trajectoire
"""
import os

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

Base_URL = 'https://opensky-network.org/api'


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

    Base_URL = Base_URL

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
