# Responsable : Syndia
# Tests unitaires pour OpenSkyFetcher

import pytest
from airnoisepy.flight.opensky import (OpenSkyFetcher,
                                       DEFAULT_RADIUS_KM,
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
        "baro_altitude": altitude,
        "true_track": true_track,
        "on_ground": on_ground,
        "velocity": None,}

def _make_track(path, icao24="c07e32", callsign="ACA750"):
    """Construit un dictionnaire de track_data pour les tests"""
    return {"icao24": icao24, "callsign": callsign, "path": path}

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

#Tests fetch_track

class TestFetchTrack:

    def test_retourne_trajectoire(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = TRACK_VALIDE
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            result = fetcher.fetch_track("c07e32", 1748649600)
        assert result["icao24"] == "c07e32"
        assert len(result["path"]) == 6

    def test_parametres_transmis_a_lapi(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = TRACK_VALIDE
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock) as mock_get:
            fetcher.fetch_track("c07e32", 1748649600)
            params = mock_get.call_args[1]["params"]
            assert params["icao24"] == "c07e32"
            assert params["time"] == 1748649600

    def test_endpoint_correct(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = TRACK_VALIDE
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock) as mock_get:
            fetcher.fetch_track("c07e32", 1748649600)
            url = mock_get.call_args[0][0]
            assert "/tracks/all" in url

#Tests fetch_realtime

class TestFetchRealtime:

    def _make_state(self):
        """State vector OpenSky complet (17 champs)."""
        return ["c07e32", "ACA750 ", "Canada", 1748649600, 1748649600,
                -73.74, 45.47, 500.0, False, 250.0, 240.0, -3.0,
                None, 480.0, "1234", False, 0]

    def test_retourne_liste_avions(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = {"states": [self._make_state()]}
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            avions = fetcher.fetch_realtime()
        assert len(avions) == 1

    def test_champs_corrects(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = {"states": [self._make_state()]}
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            avion = fetcher.fetch_realtime()[0]
        assert avion["icao24"] == "c07e32"
        assert avion["callsign"] == "ACA750"  # strip() appliqué
        assert avion["baro_altitude"] == 480.0  # state[13]
        assert avion["latitude"] == 45.47
        assert avion["longitude"] == -73.74

    def test_baro_altitude_est_state_13(self, fetcher):
        state = self._make_state()
        state[7] = 999.0  # geo_altitude — ne doit PAS être utilisé
        state[13] = 480.0  # baro_altitude — doit être utilisé
        mock = MagicMock()
        mock.json.return_value = {"states": [state]}
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            avion = fetcher.fetch_realtime()[0]
        assert avion["baro_altitude"] == 480.0

    def test_states_none_ignores(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = {"states": [None, None]}
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            avions = fetcher.fetch_realtime()
        assert avions == []

    def test_states_trop_courts_ignores(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = {"states": [[1, 2, 3]]}  # < 9 champs
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            avions = fetcher.fetch_realtime()
        assert avions == []

    def test_bbox_transmise_correctement(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = {"states": []}
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock) as mock_get:
            fetcher.fetch_realtime(bbox=(45.30, 45.65, -74.05, -73.40))
            params = mock_get.call_args[1]["params"]
        assert params["lamin"] == 45.30
        assert params["lamax"] == 45.65
        assert params["lomin"] == -74.05
        assert params["lomax"] == -73.40

# Test clean_track

class TestCleanTrack:

    def test_trajectoire_vide_retourne_liste_vide(self, fetcher):
        assert fetcher.clean_track(TRACK_VIDE) == []

    def test_retourne_liste_de_dicts(self, fetcher):
        result = fetcher.clean_track(TRACK_VALIDE)
        assert isinstance(result, list)
        for point in result:
            assert isinstance(point, dict)

    def test_champs_obligatoires_presents(self, fetcher):
        result = fetcher.clean_track(TRACK_VALIDE)
        for point in result:
            for cle in ("time", "latitude", "longitude",
                        "baro_altitude", "altitude_agl", "velocity", "on_ground"):
                assert cle in point, f"Clé manquante : {cle}"

    def test_entrees_invalides_ignorees(self, fetcher):
        result = fetcher.clean_track(TRACK_INVALIDE)
        # Aucun point ne doit avoir latitude ou longitude None
        for point in result:
            assert point["latitude"] is not None
            assert point["longitude"] is not None

    def test_altitude_agl_non_negative(self, fetcher):
        result = fetcher.clean_track(TRACK_VALIDE)
        for point in result:
            assert point["altitude_agl"] >= 0.0

    def test_velocity_calculee(self, fetcher):
        result = fetcher.clean_track(TRACK_VALIDE)
        for point in result:
            assert point["velocity"] is not None
            assert point["velocity"] >= 0.0

    def test_points_dans_zone_yul(self, fetcher):
        result = fetcher.clean_track(TRACK_VALIDE)
        for point in result:
            dist = OpenSkyFetcher._haversine_distance_km(
                point["latitude"], point["longitude"],
                YUL_LATITUDE_KM, YUL_LONGITUDE_KM
            )
            assert dist <= DEFAULT_RADIUS_KM


# Test to_flight_operation

class TestToFlightOperation:

    def test_leve_value_error_si_trajectoire_vide(self, fetcher):
        with patch.object(fetcher, "clean_track", return_value=[]):
            with pytest.raises(ValueError, match="c07e32"):
                fetcher.to_flight_operation("c07e32", TRACK_VALIDE)

    def test_leve_import_error_si_flight_operation_indisponible(self, fetcher):
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", False):
            with pytest.raises(ImportError, match="FlightOperation"):
                fetcher.to_flight_operation("c07e32", TRACK_VALIDE)

    def test_callsign_vide_fallback_sur_icao24(self, fetcher):
        track_sans_callsign = _make_track(TRACK_VALIDE["path"], icao24="c07e32", callsign="")
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", True):
            with patch("airnoisepy.flight.opensky.FlightOperation") as mock_class:
                mock_class.from_opensky.return_value = MagicMock()
                fetcher.to_flight_operation("c07e32", track_sans_callsign)
                format_passe = mock_class.from_opensky.call_args[0][0]
        assert format_passe["callsign"] == "c07e32"

    def test_aircraft_type_a320_pour_icao24_connu(self, fetcher):
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", True):
            with patch("airnoisepy.flight.opensky.FlightOperation") as mock_class:
                mock_class.from_opensky.return_value = MagicMock()
                fetcher.to_flight_operation("c07e32", TRACK_VALIDE)
                format_passe = mock_class.from_opensky.call_args[0][0]
        assert format_passe["aircraft_type"] == "A320"

    def test_waypoints_champs_obligatoires(self, fetcher):
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", True):
            with patch("airnoisepy.flight.opensky.FlightOperation") as mock_class:
                mock_class.from_opensky.return_value = MagicMock()
                fetcher.to_flight_operation("c07e32", TRACK_VALIDE)
                format_passe = mock_class.from_opensky.call_args[0][0]
        for wp in format_passe["waypoints"]:
            for cle in ("time", "latitude", "longitude",
                        "baro_altitude", "altitude_agl", "velocity"):
                assert cle in wp, f"Clé manquante dans waypoint : {cle}"

    def test_altitude_agl_non_negative_dans_waypoints(self, fetcher):
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", True):
            with patch("airnoisepy.flight.opensky.FlightOperation") as mock_class:
                mock_class.from_opensky.return_value = MagicMock()
                fetcher.to_flight_operation("c07e32", TRACK_VALIDE)
                format_passe = mock_class.from_opensky.call_args[0][0]
        for wp in format_passe["waypoints"]:
            assert wp["altitude_agl"] >= 0.0

    def test_path_dans_format_meme_longueur_que_waypoints(self, fetcher):
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", True):
            with patch("airnoisepy.flight.opensky.FlightOperation") as mock_class:
                mock_class.from_opensky.return_value = MagicMock()
                fetcher.to_flight_operation("c07e32", TRACK_VALIDE)
                format_passe = mock_class.from_opensky.call_args[0][0]
        assert len(format_passe["path"]) == len(format_passe["waypoints"])

    def test_retourne_objet_flight_operation(self, fetcher):
        mock_fo = MagicMock()
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", True):
            with patch("airnoisepy.flight.opensky.FlightOperation") as mock_class:
                mock_class.from_opensky.return_value = mock_fo
                result = fetcher.to_flight_operation("c07e32", TRACK_VALIDE)
        assert result is mock_fo

    def test_icao24_transmis_a_from_opensky(self, fetcher):
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", True):
            with patch("airnoisepy.flight.opensky.FlightOperation") as mock_class:
                mock_class.from_opensky.return_value = MagicMock()
                fetcher.to_flight_operation("c07e32", TRACK_VALIDE)
                format_passe = mock_class.from_opensky.call_args[0][0]
        assert format_passe["icao24"] == "c07e32"

    def test_callsign_transmis_a_from_opensky(self, fetcher):
        with patch("airnoisepy.flight.opensky.FLIGHT_OPERATION_AVAILABLE", True):
            with patch("airnoisepy.flight.opensky.FlightOperation") as mock_class:
                mock_class.from_opensky.return_value = MagicMock()
                fetcher.to_flight_operation("c07e32", TRACK_VALIDE)
                format_passe = mock_class.from_opensky.call_args[0][0]
        assert format_passe["callsign"] == "ACA750"


#Tests Méthodes privées

#Test _remove_outliers

class TestRemoveOutliers:

    def test_supprime_altitude_tres_haute(self, fetcher):
        points = [_make_point(i, altitude=500.0) for i in range(20)]
        points[10] = _make_point(10, altitude=99999.0)
        result = fetcher._remove_outliers(points)
        altitudes = [p["baro_altitude"] for p in result]
        assert 99999.0 not in altitudes

    def test_conserve_trajectoire_normale(self, fetcher):
        points = [_make_point(i, altitude=float(500 + i * 5)) for i in range(10)]
        result = fetcher._remove_outliers(points)
        assert len(result) == len(points)

    def test_retourne_intact_si_moins_de_window_points(self, fetcher):
        points = [_make_point(i) for i in range(3)]
        result = fetcher._remove_outliers(points, window=5)
        assert result == points

    def test_trajectoire_plate_conservee(self, fetcher):
        points = [_make_point(i, altitude=500.0) for i in range(10)]
        result = fetcher._remove_outliers(points)
        assert len(result) == 10

    def test_altitude_negative_aberrante_supprimee(self, fetcher):
        points = [_make_point(i, altitude=500.0) for i in range(20)]
        points[10] = _make_point(10, altitude=-9999.0)  # outlier négatif
        result = fetcher._remove_outliers(points)
        altitudes = [p["baro_altitude"] for p in result]
        assert -9999.0 not in altitudes


# Test _interpolate_gaps

class TestInterpolateGaps:

    def _pts(self, t1, t2, alt1=900.0, alt2=800.0):
        return [
            {"time": t1, "latitude": 45.50, "longitude": -73.80,
             "baro_altitude": alt1, "true_track": 240.0,
             "on_ground": False, "velocity": 0.0},
            {"time": t2, "latitude": 45.48, "longitude": -73.78,
             "baro_altitude": alt2, "true_track": 242.0,
             "on_ground": False, "velocity": 0.0},
        ]

    def test_trou_court_interpole(self, fetcher):
        points = self._pts(0, 10)
        result = fetcher._interpolate_gaps(points, max_gaps=10)
        assert len(result) > 2

    def test_trou_long_non_interpole(self, fetcher):
        points = self._pts(0, 30)
        result = fetcher._interpolate_gaps(points, max_gaps=10)
        assert len(result) == 2

    def test_gap_zero_pas_de_doublon(self, fetcher):
        points = self._pts(0, 0)
        result = fetcher._interpolate_gaps(points)
        assert len(result) == 2

    def test_interpolation_lineaire_latitude(self, fetcher):
        points = [
            {"time": 0, "latitude": 45.00, "longitude": -73.00,
             "baro_altitude": 1000.0, "true_track": 0.0,
             "on_ground": False, "velocity": 0.0},
            {"time": 10, "latitude": 45.10, "longitude": -73.10,
             "baro_altitude": 900.0, "true_track": 0.0,
             "on_ground": False, "velocity": 0.0},
        ]
        result = fetcher._interpolate_gaps(points, max_gaps=10)
        pt_milieu = next(p for p in result if p["time"] == 5)
        assert abs(pt_milieu["latitude"] - 45.05) < 0.001

    def test_interpolation_lineaire_altitude(self, fetcher):
        points = [
            {"time": 0, "latitude": 45.00, "longitude": -73.00,
             "baro_altitude": 1000.0, "true_track": 0.0,
             "on_ground": False, "velocity": 0.0},
            {"time": 10, "latitude": 45.10, "longitude": -73.10,
             "baro_altitude": 900.0, "true_track": 0.0,
             "on_ground": False, "velocity": 0.0},
        ]
        result = fetcher._interpolate_gaps(points, max_gaps=10)
        pt_milieu = next(p for p in result if p["time"] == 5)
        assert abs(pt_milieu["baro_altitude"] - 950.0) < 0.1

    def test_point_interpole_on_ground_false(self, fetcher):
        points = self._pts(0, 10)
        result = fetcher._interpolate_gaps(points, max_gaps=10)
        for pt in result[1:-1]:
            assert pt["on_ground"] is False

    def test_un_seul_point_retourne_intact(self, fetcher):
        points = [_make_point(0)]
        result = fetcher._interpolate_gaps(points)
        assert result == points

#Tests _correct_altitude_agl

class TestCorrectAltitudeAgl:

    def test_sans_srtm_altitude_agl_egale_baro(self, fetcher):
        points = [_make_point(0, altitude=500.0), _make_point(1, altitude=300.0)]
        result = fetcher._correct_altitude_agl(points)
        assert result[0]["altitude_agl"] == 500.0
        assert result[1]["altitude_agl"] == 300.0

    def test_cle_altitude_agl_ajoutee(self, fetcher):
        points = [_make_point(0, altitude=500.0)]
        result = fetcher._correct_altitude_agl(points)
        assert "altitude_agl" in result[0]

    def test_altitude_agl_jamais_negative(self, fetcher):
        points = [_make_point(0, altitude=0.0)]
        result = fetcher._correct_altitude_agl(points)
        assert result[0]["altitude_agl"] >= 0.0

    def test_altitude_agl_baro_zero(self, fetcher):
        points = [_make_point(0, altitude=0.0)]
        result = fetcher._correct_altitude_agl(points)
        assert result[0]["altitude_agl"] == 0.0

#Tests _filter_yul_zone

class TestFilterYulZone:

    def test_conserve_point_centre_yul(self, fetcher):
        points = [{"latitude": YUL_LATITUDE_KM, "longitude": YUL_LONGITUDE_KM,
                   "baro_altitude": 500.0, "altitude_agl": 500.0}]
        result = fetcher._filter_yul_zone(points)
        assert len(result) == 1

    def test_supprime_point_trop_loin(self, fetcher):
        points = [{"latitude": 46.35, "longitude": -72.55,
                   "baro_altitude": 500.0, "altitude_agl": 500.0}]
        result = fetcher._filter_yul_zone(points)
        assert len(result) == 0

    def test_supprime_point_trop_haut(self, fetcher):
        points = [{"latitude": YUL_LATITUDE_KM, "longitude": YUL_LONGITUDE_KM,
                   "baro_altitude": 5000.0, "altitude_agl": 5000.0}]
        result = fetcher._filter_yul_zone(points)
        assert len(result) == 0

    def test_fallback_baro_si_altitude_agl_absente(self, fetcher):
        points = [{"latitude": YUL_LATITUDE_KM, "longitude": YUL_LONGITUDE_KM,
                   "baro_altitude": 500.0}]
        result = fetcher._filter_yul_zone(points)
        assert isinstance(result, list)

    def test_rayon_personnalise(self, fetcher):
        points = [{"latitude": 45.38, "longitude": -73.74,
                   "baro_altitude": 500.0, "altitude_agl": 500.0}]
        assert len(fetcher._filter_yul_zone(points, radius_km=5)) == 0
        assert len(fetcher._filter_yul_zone(points, radius_km=15)) == 1

#Tests _api_get

class TestApiGet:

    def test_retourne_json_decode(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = [{"icao24": "c07e32"}]
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock):
            result = fetcher._api_get("/flights/arrival", {}, None)
        assert result == [{"icao24": "c07e32"}]

    def test_url_construite_correctement(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = []
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock) as mock_get:
            fetcher._api_get("/flights/arrival", {}, None)
            url = mock_get.call_args[0][0]
        assert url == "https://opensky-network.org/api/flights/arrival"

    def test_timeout_30_secondes(self, fetcher):
        mock = MagicMock()
        mock.json.return_value = []
        mock.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock) as mock_get:
            fetcher._api_get("/flights/arrival", {}, None)
            timeout = mock_get.call_args[1]["timeout"]
        assert timeout == 30

    def test_leve_exception_si_erreur_http(self, fetcher):
        mock = MagicMock()
        mock.raise_for_status.side_effect = Exception("404 Not Found")
        with patch("requests.get", return_value=mock):
            with pytest.raises(Exception, match="404"):
                fetcher._api_get("/mauvais/endpoint", {}, None)

#Tests _haversine_km

class TestHaversineDistanceKm:

    def test_distance_nulle_meme_point(self):
        d = OpenSkyFetcher._haversine_distance_km(45.47, -73.74, 45.47, -73.74)
        assert d == pytest.approx(0.0, abs=1e-6)

    def test_distance_yul_toronto(self):
        d = OpenSkyFetcher._haversine_distance_km(
            45.4706, -73.7408, 43.6772, -79.6306
        )
        assert 500.0 < d < 510.0

    def test_symetrie(self):
        d1 = OpenSkyFetcher._haversine_distance_km(45.47, -73.74, 45.50, -73.70)
        d2 = OpenSkyFetcher._haversine_distance_km(45.50, -73.70, 45.47, -73.74)
        assert d1 == pytest.approx(d2, rel=1e-6)

    def test_toujours_positive(self):
        d = OpenSkyFetcher._haversine_distance_km(45.47, -73.74, 45.50, -73.70)
        assert d > 0

    def test_yul_dans_rayon_25km(self):
        d = OpenSkyFetcher._haversine_distance_km(
            45.4706, -73.7408,
            45.29, -73.7408  # ~20 km au sud
        )
        assert d < 25.0

#Tests _compute_speed

class TestComputeSpeed:

    def test_un_seul_point_vitesse_nulle(self, fetcher):
        points = [_make_point(0, altitude=500.0)]
        result = fetcher._compute_speed(points)
        assert result[0]["velocity"] == 0.0

    def test_vitesse_positive_pour_points_distincts(self, fetcher):
        points = [
            _make_point(0, latitude=45.47, longitude=-73.74, altitude=500.0),
            _make_point(5, latitude=45.48, longitude=-73.73, altitude=480.0),
            _make_point(10, latitude=45.49, longitude=-73.72, altitude=460.0),
        ]
        result = fetcher._compute_speed(points)
        for p in result:
            assert p["velocity"] >= 0.0

    def test_dt_zero_vitesse_nulle(self, fetcher):
        # Deux points au même timestamp → pas de division par zéro
        points = [
            _make_point(0, latitude=45.47, longitude=-73.74, altitude=500.0),
            _make_point(0, latitude=45.47, longitude=-73.74, altitude=500.0),
            _make_point(5, latitude=45.48, longitude=-73.73, altitude=480.0),
        ]
        result = fetcher._compute_speed(points)
        assert result[0]["velocity"] == 0.0

    def test_cle_velocity_ajoutee(self, fetcher):
        points = [
            _make_point(0, latitude=45.47, longitude=-73.74, altitude=500.0),
            _make_point(5, latitude=45.48, longitude=-73.73, altitude=480.0),
        ]
        result = fetcher._compute_speed(points)
        for p in result:
            assert "velocity" in p

#Tests _map_aircraft_type

class TestMapAircraftType:

    @pytest.mark.parametrize("icao24,expected", [
        ("c07e32", "A320"),
        ("c04b3a", "B738"),
        ("c06184", "A321"),
        ("c05140", "DH8D"),
        ("c06c48", "B77W"),
        ("c07a97", "A220"),
    ])
    def test_icao24_connus(self, fetcher, icao24, expected):
        with patch("requests.get", side_effect=Exception("pas de réseau")):
            assert fetcher._map_aircraft_type(icao24) == expected

    def test_icao24_inconnu_retourne_a320(self, fetcher):
        with patch("requests.get", side_effect=Exception("pas de réseau")):
            assert fetcher._map_aircraft_type("aaaaaa") == "A320"

    def test_insensible_a_la_casse(self, fetcher):
        with patch("requests.get", side_effect=Exception("pas de réseau")):
            assert fetcher._map_aircraft_type("C07E32") == \
                   fetcher._map_aircraft_type("c07e32")

    def test_api_opensky_utilisee_si_credentials(self, fetcher_auth):
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {"typecode": "B77W"}
        with patch("requests.get", return_value=mock):
            result = fetcher_auth._map_aircraft_type("c06c48")
        assert result == "B77W"

    def test_fallback_dict_si_api_echoue(self, fetcher_auth):
        with patch("requests.get", side_effect=Exception("timeout")):
            result = fetcher_auth._map_aircraft_type("c07e32")
        assert result == "A320"