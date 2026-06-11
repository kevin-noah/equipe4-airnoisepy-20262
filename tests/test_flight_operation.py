# Responsable : Kevin
# Tests unitaires pour FlightOperation

import json
import os
import pytest

from airnoisepy.flight.operation import FlightOperation

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TRACK_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'sample_track.json')


@pytest.fixture
def aca750_track():
    with open(SAMPLE_TRACK_PATH) as f:
        return json.load(f)


@pytest.fixture
def aca750(aca750_track):
    return FlightOperation.from_opensky(aca750_track)


def _make_track(path, icao24='abc123', callsign='TST001'):
    """Construit un dict track_data minimal pour les tests paramétrés."""
    return {'icao24': icao24, 'callsign': callsign, 'path': path}


def _departure_path():
    """Trajectoire de décollage simple : 5 points qui montent."""
    t0 = 1_000_000
    return [
        [t0 +  0, 45.470, -73.740,    0, 0, True],
        [t0 + 20, 45.475, -73.750,  305, 0, False],
        [t0 + 40, 45.480, -73.760,  610, 0, False],
        [t0 + 60, 45.490, -73.775, 1500, 0, False],
        [t0 + 80, 45.500, -73.790, 3000, 0, False],
    ]


def _arrival_path():
    """Trajectoire d'arrivée simple : 5 points qui descendent."""
    t0 = 2_000_000
    return [
        [t0 +  0, 45.600, -74.000, 4000, 0, False],
        [t0 + 20, 45.580, -73.980, 2000, 0, False],
        [t0 + 40, 45.560, -73.960,  800, 0, False],
        [t0 + 60, 45.530, -73.940,  200, 0, False],
        [t0 + 80, 45.510, -73.920,    0, 0, True],
    ]


def _go_around_path():
    """
    Trajectoire avec remise de gaz : descente sous 610 m puis remontée.
    Points 0-2 : descente jusqu'à 200 m (sous le seuil 610 m).
    Point 3    : remontée → remise de gaz détectée.
    """
    t0 = 3_000_000
    return [
        [t0 +  0, 45.600, -74.000, 2000, 0, False],
        [t0 + 20, 45.580, -73.980,  600, 0, False],
        [t0 + 40, 45.560, -73.960,  200, 0, False],
        [t0 + 60, 45.550, -73.950,  800, 0, False],  # remontée sous 610 m déjà atteint
        [t0 + 80, 45.540, -73.940, 2000, 0, False],
    ]


# ---------------------------------------------------------------------------
# __init__ / attributs de base
# ---------------------------------------------------------------------------

class TestInit:
    def test_attributs_directs(self):
        wps = [
            {'time': 0, 'lat': 45.47, 'lon': -73.74, 'alt_baro': 0,   'speed': 0},
            {'time': 20,'lat': 45.48, 'lon': -73.75, 'alt_baro': 300, 'speed': 50},
        ]
        f = FlightOperation('aabbcc', '  ACA001  ', 'departure', wps)
        assert f.icao24 == 'aabbcc'
        assert f.callsign == 'ACA001'          # strip() appliqué
        assert f.operation_type == 'departure'
        assert f.waypoints is wps

    def test_callsign_none_ne_crash_pas(self):
        wps = [
            {'time': 0,  'lat': 45.0, 'lon': -73.0, 'alt_baro': 0,   'speed': 0},
            {'time': 10, 'lat': 45.1, 'lon': -73.1, 'alt_baro': 100, 'speed': 10},
        ]
        f = FlightOperation('aabbcc', None, 'arrival', wps)
        assert f.callsign == ''

    def test_segments_calcules_a_linit(self):
        wps = [
            {'time': 0,  'lat': 45.0, 'lon': -73.0, 'alt_baro': 0,   'speed': 0},
            {'time': 10, 'lat': 45.1, 'lon': -73.1, 'alt_baro': 100, 'speed': 10},
        ]
        f = FlightOperation('x', 'Y', 'departure', wps)
        assert len(f.segments) == 1


# ---------------------------------------------------------------------------
# from_opensky
# ---------------------------------------------------------------------------

class TestFromOpenSky:
    def test_icao24_et_callsign(self, aca750):
        assert aca750.icao24 == 'c07e32'
        assert aca750.callsign == 'ACA750'     # trailing spaces supprimés

    def test_nb_waypoints(self, aca750_track, aca750):
        assert len(aca750.waypoints) == len(aca750_track['path'])

    def test_nb_segments(self, aca750_track, aca750):
        assert len(aca750.segments) == len(aca750_track['path']) - 1

    def test_structure_waypoint(self, aca750):
        wp = aca750.waypoints[5]
        assert set(wp.keys()) == {'time', 'lat', 'lon', 'alt_baro', 'speed'}

    def test_structure_segment(self, aca750):
        seg = aca750.segments[0]
        expected_keys = {
            'lat_start', 'lon_start', 'alt_start',
            'lat_end',   'lon_end',   'alt_end',
            'speed_ms', 'duration_s', 'thrust_pct', 'phase',
        }
        assert set(seg.keys()) == expected_keys

    def test_premier_waypoint_speed_non_nul(self, aca750):
        # Le premier waypoint récupère la vitesse du segment suivant
        assert aca750.waypoints[0]['speed'] > 0

    def test_operation_type_arrival_aca750(self, aca750):
        # ACA750 : altitude finale 0 ≤ altitude initiale → arrival
        assert aca750.operation_type == 'arrival'

    def test_operation_type_departure(self):
        f = FlightOperation.from_opensky(_make_track(_departure_path()))
        assert f.operation_type == 'departure'

    def test_is_go_around_false_aca750(self, aca750):
        assert aca750.is_go_around is False


# ---------------------------------------------------------------------------
# classify_operation
# ---------------------------------------------------------------------------

class TestClassifyOperation:
    def test_departure(self):
        f = FlightOperation.from_opensky(_make_track(_departure_path()))
        assert f.classify_operation() == 'departure'

    def test_arrival(self):
        f = FlightOperation.from_opensky(_make_track(_arrival_path()))
        assert f.classify_operation() == 'arrival'

    def test_coherent_avec_operation_type(self, aca750):
        assert aca750.classify_operation() == aca750.operation_type


# ---------------------------------------------------------------------------
# detect_go_around
# ---------------------------------------------------------------------------

class TestDetectGoAround:
    def test_go_around_detecte(self):
        f = FlightOperation.from_opensky(_make_track(_go_around_path()))
        assert f.is_go_around is True

    def test_pas_de_go_around_sur_depart_normal(self):
        f = FlightOperation.from_opensky(_make_track(_departure_path()))
        assert f.is_go_around is False

    def test_pas_de_go_around_sur_arrivee_normale(self):
        f = FlightOperation.from_opensky(_make_track(_arrival_path()))
        assert f.is_go_around is False

    def test_track_trop_court(self):
        path = [[1_000_000, 45.47, -73.74, 0, 0, False]]
        f = FlightOperation.from_opensky(_make_track(path))
        assert f.is_go_around is False


# ---------------------------------------------------------------------------
# compute_segments
# ---------------------------------------------------------------------------

class TestComputeSegments:
    def test_nb_segments_egale_waypoints_moins_1(self, aca750):
        assert len(aca750.segments) == len(aca750.waypoints) - 1

    def test_positions_coherentes(self, aca750):
        # La fin d'un segment correspond au début du suivant
        for i in range(len(aca750.segments) - 1):
            s0 = aca750.segments[i]
            s1 = aca750.segments[i + 1]
            assert s0['lat_end'] == s1['lat_start']
            assert s0['lon_end'] == s1['lon_start']
            assert s0['alt_end'] == s1['alt_start']

    def test_duree_positive(self, aca750):
        for seg in aca750.segments:
            assert seg['duration_s'] >= 0

    def test_vitesse_positive(self, aca750):
        for seg in aca750.segments:
            assert seg['speed_ms'] >= 0

    def test_thrust_entre_0_et_1(self, aca750):
        for seg in aca750.segments:
            assert 0.0 <= seg['thrust_pct'] <= 1.0

    def test_phase_valeur_valide(self, aca750):
        phases_valides = {'takeoff', 'climb', 'cruise', 'approach', 'landing'}
        for seg in aca750.segments:
            assert seg['phase'] in phases_valides

    def test_vitesse_calculee_correctement(self):
        # Segment de 1000 m en 10 s → speed_ms = 100 m/s
        # On crée deux waypoints à ~1000 m de distance
        # 1° de latitude ≈ 111 000 m → 0.009° ≈ 999 m
        path = [
            [0,  45.000, -73.000, 500, 0, False],
            [10, 45.009, -73.000, 500, 0, False],
        ]
        f = FlightOperation.from_opensky(_make_track(path))
        seg = f.segments[0]
        assert abs(seg['speed_ms'] - 100.0) < 2.0   # tolérance 2 m/s

    def test_segments_vide_si_un_seul_waypoint(self):
        path = [[0, 45.0, -73.0, 0, 0, False]]
        f = FlightOperation.from_opensky(_make_track(path))
        assert f.segments == []


# ---------------------------------------------------------------------------
# get_thrust_profile
# ---------------------------------------------------------------------------

class TestGetThrustProfile:
    @pytest.mark.parametrize("phase,expected", [
        ('takeoff',  0.94),
        ('climb',    0.86),
        ('cruise',   0.80),
        ('approach', 0.68),
        ('landing',  0.68),
    ])
    def test_valeurs_connues(self, aca750, phase, expected):
        assert aca750.get_thrust_profile(phase) == expected

    def test_phase_inconnue_retourne_valeur_defaut(self, aca750):
        assert aca750.get_thrust_profile('unknown') == 0.80


# ---------------------------------------------------------------------------
# Phases de vol selon l'altitude (départ et arrivée)
# ---------------------------------------------------------------------------

class TestPhases:
    def test_depart_phases(self):
        # Décollage : alt < 1000 ft (< 305 m)   → takeoff
        # Montée    : 1000–10000 ft (305–3048 m) → climb
        # Croisière : > 10000 ft (> 3048 m)      → cruise
        path = [
            [0,  45.0, -73.0,  100, 0, False],   # takeoff
            [20, 45.1, -73.1,  500, 0, False],    # climb
            [40, 45.2, -73.2, 3500, 0, False],    # cruise
            [60, 45.3, -73.3, 5000, 0, False],
        ]
        f = FlightOperation.from_opensky(_make_track(path))
        phases = [s['phase'] for s in f.segments]
        assert phases[0] == 'takeoff'
        assert phases[1] == 'climb'
        assert phases[2] == 'cruise'

    def test_arrivee_phases(self):
        # mid-altitudes : (5000+1000)/2=3000 m → approach
        #                 (1000+400)/2=700 m → approach (> 305 m = 1000 ft)
        #                 (400+0)/2=200 m    → landing  (< 305 m)
        path = [
            [0,  45.3, -73.3, 5000, 0, False],
            [20, 45.2, -73.2, 1000, 0, False],
            [40, 45.1, -73.1,  400, 0, False],
            [60, 45.0, -73.0,    0, 0, True],
        ]
        f = FlightOperation.from_opensky(_make_track(path))
        phases = [s['phase'] for s in f.segments]
        assert phases[0] == 'approach'
        assert phases[1] == 'approach'
        assert phases[2] == 'landing'


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

class TestToDict:
    def test_cles_presentes(self, aca750):
        d = aca750.to_dict()
        assert set(d.keys()) == {
            'icao24', 'callsign', 'operation_type',
            'is_go_around', 'waypoints', 'segments',
        }

    def test_valeurs_coherentes(self, aca750):
        d = aca750.to_dict()
        assert d['icao24'] == aca750.icao24
        assert d['callsign'] == aca750.callsign
        assert d['is_go_around'] == aca750.is_go_around
        assert len(d['segments']) == len(aca750.segments)

    def test_serialisable_json(self, aca750):
        import json
        d = aca750.to_dict()
        json_str = json.dumps(d)     # ne doit pas lever d'exception
        assert isinstance(json_str, str)


# ---------------------------------------------------------------------------
# _haversine (méthode interne, testée directement)
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_distance_nulle(self):
        assert FlightOperation._haversine(45.0, -73.0, 45.0, -73.0) == pytest.approx(0.0)

    def test_distance_connue(self):
        # Montréal YUL → Toronto CYYZ : ~504 km
        d = FlightOperation._haversine(45.4706, -73.7408, 43.6772, -79.6306)
        assert 500_000 < d < 510_000

    def test_symetrie(self):
        d1 = FlightOperation._haversine(45.0, -73.0, 46.0, -74.0)
        d2 = FlightOperation._haversine(46.0, -74.0, 45.0, -73.0)
        assert d1 == pytest.approx(d2)
