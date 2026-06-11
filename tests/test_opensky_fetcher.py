# Responsable : Syndia
# Tests unitaires pour OpenSkyFetcher

import pytest
from airnoisepy.flight.opensky import (OpenSkyFetcher,
                                       DEFAULT_MAX_GAP_S,
                                       DEFAULT_RADIUS_KM,
                                       MAX_ALTITUDE_AGL_M,
                                       YUL_LATITUDE_KM,
                                       YUL_LONGITUDE_KM)
from unittest.mock import patch, MagicMock

#Données de test

def _make_point(time=0, latitude=45.47, longitude=-73.74, altitude=500.0, true_track=240.0, on_ground=False):
    """Construit un dictionnaire de point pour les tests"""
    return {
        "time": time,
        "latitude": latitude,
        "longitude": longitude,
        "base_altitude": altitude,
        "true_track": true_track,}

def _make_track(path, icao24="c07e32", callsigne="ACA750"):
    """Construit un dictionnaire de track_data pour les tests"""
    return {"icao24": icao24, "callsign": callsigne, "path": path}

# Trajectoire brute valide d'un avion en approche sur YUL
TRACK_VALIDE = _make_track([
    [1748649600, 45.50, -73.80,  900.0, 240.0, False],
    [1748649605, 45.49, -73.79,  850.0, 241.0, False],
    [1748649610, 45.48, -73.78,  800.0, 242.0, False],
    [1748649615, 45.47, -73.77,  750.0, 243.0, False],
    [1748649620, 45.46, -73.76,  700.0, 244.0, False],
    [1748649625, 45.45, -73.75,  650.0, 245.0, False],
])

# Trajectoire avec un outlier d'altitude
TRACK_AVEC_OUTLIER = _make_track([
    [1748649600, 45.50, -73.80,   900.0, 240.0, False],
    [1748649605, 45.49, -73.79,   850.0, 241.0, False],
    [1748649610, 45.48, -73.78, 99999.0, 242.0, False],  # outlier
    [1748649615, 45.47, -73.77,   800.0, 243.0, False],
    [1748649620, 45.46, -73.76,   750.0, 244.0, False],
])

# Trajectoire vide
TRACK_VIDE = _make_track([])

# Trajectoire avec entrées invalides
TRACK_INVALIDE = _make_track([
    None,
    [1748649600, None, -73.80, 900.0, 240.0, False],  # latitude None
    [1748649605],  # trop court
    [1748649610, 45.48, -73.78, 800.0, 242.0, False],  # seul point valide
])

#Fixture

@pytest.fixture
def fetcher():
    """OpenSkyFetcher anonyme sans SRTM."""
    return OpenSkyFetcher()


@pytest.fixture
def fetcher_auth():
    """OpenSkyFetcher avec identifiants fictifs."""
    return OpenSkyFetcher(username="username", password="test123")

#Test init

class TestInit:

    def test_sans_identifiants(self, fetcher):
        assert fetcher.username is None
        assert fetcher.password is None
        assert fetcher.dem is None

    def test_avec_identifiants(self, fetcher_auth):
        assert fetcher_auth.username == "username"
        assert fetcher_auth.password == "test123"

    def test_dem_path_inexistant(self):
        "doit annoncer file not found"
        with pytest.raises(FileNotFoundError):
            OpenSkyFetcher(dem_path="chemin/inexistant/yul_dem.tif")

    def test_rasterio_absent(self):
        with patch("airnoisepy.flight.opensky.RASTERIO_AVAILABLE", False):
            with pytest.raises(ImportError):
                OpenSkyFetcher(dem_path="yul_dem.tif")

    def test_base_url_correcte(self, fetcher):
        assert fetcher.BASE_URL == "https://opensky-network.org/api"


#Test fetch_flights

class TestFletchFlights:

    def test_time_superieure_7_jours(self, fetcher):
        with pytest.raises(ValueError, match="7 jours"):
            fetcher.fetch_flights("CYUL", 0, 8 * 86400)

    def test_fenetre_exactement_7_jours(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = []
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            result = fetcher.fetch_flights("CYUL", 0, 7 * 86400)
        assert result == []

    def test_fusion_arrivees_et_departs(self, fetcher):
        vol_a = {"icao24": "c07e32", "firstSeen": 1000, "callsign": "ACA750"}
        vol_d = {"icao24": "c04b3a", "firstSeen": 2000, "callsign": "WJA100"}

        mock_arr = MagicMock()
        mock_arr.json.return_value = [vol_a]
        mock_arr.raise_for_status = MagicMock()

        mock_dep = MagicMock()
        mock_dep.json.return_value = [vol_d]
        mock_dep.raise_for_status = MagicMock()

        with patch("requests.get", side_effect=[mock_arr, mock_dep]):
            result = fetcher.fetch_flights("CYUL", 0, 86_400)

        assert len(result) == 2

    def test_deduplication_doublons(self, fetcher):
        vol = {"icao24": "c07e32", "firstSeen": 1000, "callsign": "ACA750"}

        mock_arr = MagicMock()
        mock_arr.json.return_value = [vol]
        mock_arr.raise_for_status = MagicMock()

        mock_dep = MagicMock()
        mock_dep.json.return_value = [vol]  # même vol dans les deux listes
        mock_dep.raise_for_status = MagicMock()

        with patch("requests.get", side_effect=[mock_arr, mock_dep]):
            result = fetcher.fetch_flights("CYUL", 0, 86_400)

        assert len(result) == 1

    def test_retourne_liste_vide_si_aucun_vol(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = []
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            result = fetcher.fetch_flights("CYUL", 0, 86_400)
        assert result == []

    def test_identifiants_transmis_a_api(self, fetcher_auth):
        mock = MagicMock()
        mock.json.return_value = []
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock) as mock_get:
            fetcher_auth.fetch_flights("CYUL", 0, 86_400)
            auth = mock_get.call_args[1]["auth"]
            assert auth == ("username", "test123")

    def test_sans_identifiants_auth_none(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = []
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock) as mock_get:
            fetcher.fetch_flights("CYUL", 0, 86_400)
            auth = mock_get.call_args[1]["auth"]
            assert auth is None