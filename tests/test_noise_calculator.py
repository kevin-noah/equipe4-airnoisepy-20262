# Responsable : Kevin
# Tests unitaires pour NoiseCalculator

import datetime
import json
import math
import os

import numpy as np
import pytest

from airnoisepy.flight_operation import FlightOperation
from airnoisepy.noise_calculator import NoiseCalculator

# ---------------------------------------------------------------------------
# Mock ANPDatabase — table synthétique A320 (formule du doc de tâches)
# L(d) = L0 - 20·log10(d/1000) - 0.005·(d-1000)/1000
# L0   = 55 + (thrust_pct*100 - 68) · 0.45
# ---------------------------------------------------------------------------

class MockANPDatabase:
    """Stub minimal d'ANPDatabase pour tester NoiseCalculator indépendamment."""

    def interpolate(self, aircraft_type, operation, distance, thrust_pct, metric='SEL'):
        L0 = 55 + (thrust_pct * 100 - 68) * 0.45
        return L0 - 20 * math.log10(distance / 1000) - 0.005 * (distance - 1000) / 1000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TRACK_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'sample_track.json')


@pytest.fixture
def anp():
    return MockANPDatabase()


@pytest.fixture
def calc(anp):
    return NoiseCalculator(anp)


@pytest.fixture
def calc_cold(anp):
    return NoiseCalculator(anp, temperature=-10.0, humidity=30.0)


@pytest.fixture
def aca750():
    with open(SAMPLE_TRACK_PATH) as f:
        return FlightOperation.from_opensky(json.load(f))


def _make_segment(lat_s=45.47, lon_s=-73.74, alt_s=1000,
                  lat_e=45.48, lon_e=-73.75, alt_e=1200,
                  speed=80.0, duration=20, thrust=0.80, phase='climb'):
    return {
        'lat_start': lat_s, 'lon_start': lon_s, 'alt_start': alt_s,
        'lat_end':   lat_e, 'lon_end':   lon_e, 'alt_end':   alt_e,
        'speed_ms': speed, 'duration_s': duration,
        'thrust_pct': thrust, 'phase': phase,
    }


def _make_flight_at_hour(hour_utc):
    """Crée un FlightOperation dont le premier waypoint tombe à l'heure UTC donnée."""
    base = datetime.datetime(2026, 6, 7, hour_utc, 0, 0, tzinfo=datetime.timezone.utc)
    t0 = int(base.timestamp())
    path = [
        [t0,      45.5, -73.8, 2000, 0, False],
        [t0 + 20, 45.4, -73.7, 1000, 0, False],
        [t0 + 40, 45.3, -73.6,    0, 0, True],
    ]
    return FlightOperation.from_opensky({'icao24': 'abc', 'callsign': 'TST', 'path': path})


# ---------------------------------------------------------------------------
# __init__ / alpha
# ---------------------------------------------------------------------------

class TestInit:
    def test_attributs_stockes(self, anp, calc):
        assert calc.anp_db is anp
        assert calc.temperature == 15.0
        assert calc.humidity == 70.0

    def test_alpha_positif(self, calc):
        assert calc.alpha > 0

    def test_alpha_ordre_grandeur(self, calc):
        # ISO 9613-1 à 1000 Hz, 15°C 70% HR ≈ 0.001–0.003 dB/m
        assert 0.0005 < calc.alpha < 0.005

    def test_alpha_varie_avec_conditions(self, calc, calc_cold):
        assert calc.alpha != calc_cold.alpha


# ---------------------------------------------------------------------------
# _slant_range
# ---------------------------------------------------------------------------

class TestSlantRange:
    def test_directement_sous_avion(self):
        seg = _make_segment(lat_s=45.0, lon_s=-73.0, alt_s=1000,
                            lat_e=45.0, lon_e=-73.0, alt_e=1000)
        d = NoiseCalculator._slant_range(seg, (45.0, -73.0))
        assert abs(d - 1000) < 1.0

    def test_augmente_avec_distance(self):
        seg = _make_segment(lat_s=45.47, lon_s=-73.74, alt_s=1000,
                            lat_e=45.48, lon_e=-73.75, alt_e=1000)
        d_proche = NoiseCalculator._slant_range(seg, (45.475, -73.745))
        d_loin   = NoiseCalculator._slant_range(seg, (45.000, -73.000))
        assert d_loin > d_proche

    def test_toujours_positif(self, aca750):
        r = (45.47, -73.74)
        for seg in aca750.segments:
            assert NoiseCalculator._slant_range(seg, r) > 0


# ---------------------------------------------------------------------------
# _correction_duration
# ---------------------------------------------------------------------------

class TestCorrectionDuration:
    def test_a_vitesse_reference_correction_nulle(self, calc):
        seg = _make_segment(speed=82.3)
        assert abs(calc._correction_duration(seg)) < 0.01

    def test_plus_rapide_correction_negative(self, calc):
        assert calc._correction_duration(_make_segment(speed=200.0)) < 0

    def test_plus_lent_correction_positive(self, calc):
        assert calc._correction_duration(_make_segment(speed=40.0)) > 0

    def test_vitesse_nulle_pas_exception(self, calc):
        result = calc._correction_duration(_make_segment(speed=0.0))
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# _correction_lateral
# ---------------------------------------------------------------------------

class TestCorrectionLateral:
    def test_toujours_positive_ou_nulle(self, calc, aca750):
        r = (45.47, -73.74)
        for seg in aca750.segments:
            assert calc._correction_lateral(seg, r) >= 0.0

    def test_avion_bas_angle_rasant_plus_fort(self, calc):
        seg_bas  = _make_segment(lat_s=45.0, lon_s=-73.0, alt_s=100,
                                 lat_e=45.0, lon_e=-73.0, alt_e=100)
        seg_haut = _make_segment(lat_s=45.0, lon_s=-73.0, alt_s=5000,
                                 lat_e=45.0, lon_e=-73.0, alt_e=5000)
        r = (45.1, -73.0)
        assert calc._correction_lateral(seg_bas, r) > calc._correction_lateral(seg_haut, r)


# ---------------------------------------------------------------------------
# _correction_atmospheric
# ---------------------------------------------------------------------------

class TestCorrectionAtmospheric:
    def test_a_distance_ref_correction_nulle(self, calc):
        assert abs(calc._correction_atmospheric(1000.0)) < 1e-9

    def test_au_dela_correction_negative(self, calc):
        assert calc._correction_atmospheric(5000.0) < 0

    def test_en_deca_correction_positive(self, calc):
        assert calc._correction_atmospheric(500.0) > 0

    def test_monotone_avec_distance(self, calc):
        corrs = [calc._correction_atmospheric(d) for d in [2000, 5000, 10000]]
        assert corrs[0] > corrs[1] > corrs[2]

    def test_ordre_grandeur_a_5km(self, calc):
        assert -15.0 < calc._correction_atmospheric(5000.0) < -0.5


# ---------------------------------------------------------------------------
# _aggregate_sel
# ---------------------------------------------------------------------------

class TestAggregateSel:
    def test_un_seul_segment(self):
        assert NoiseCalculator._aggregate_sel([60.0]) == pytest.approx(60.0)

    def test_deux_niveaux_egaux(self):
        # 70 + 70 dB → 73 dB (pas 140 !)
        assert NoiseCalculator._aggregate_sel([70.0, 70.0]) == pytest.approx(73.01, abs=0.1)

    def test_segment_dominant(self):
        result = NoiseCalculator._aggregate_sel([80.0, 50.0])
        assert 80.0 < result < 80.2

    def test_coherence_formule(self):
        levels = [65.0, 68.0, 62.0]
        expected = 10 * math.log10(sum(10 ** (l / 10) for l in levels))
        assert NoiseCalculator._aggregate_sel(levels) == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# compute_sel
# ---------------------------------------------------------------------------

class TestComputeSel:
    def test_retourne_float(self, calc, aca750):
        assert isinstance(calc.compute_sel(aca750, (45.47, -73.74)), float)

    def test_valeur_positive(self, calc, aca750):
        assert calc.compute_sel(aca750, (45.47, -73.74)) > 0

    def test_diminue_avec_distance(self, calc, aca750):
        sel_proche = calc.compute_sel(aca750, (45.47, -73.74))
        sel_loin   = calc.compute_sel(aca750, (44.00, -72.00))
        assert sel_proche > sel_loin

    def test_vol_sans_segments_retourne_zero(self, calc):
        fl = FlightOperation('x', 'Y', 'departure', [])
        assert calc.compute_sel(fl, (45.0, -73.0)) == 0.0

    def test_ordre_grandeur(self, calc, aca750):
        # A320 à quelques km → SEL entre 30 et 100 dB(A)
        sel = calc.compute_sel(aca750, (45.47, -73.74))
        assert 30.0 < sel < 100.0


# ---------------------------------------------------------------------------
# compute_lden
# ---------------------------------------------------------------------------

class TestComputeLden:
    def test_sans_vols_retourne_zero(self, calc):
        lden = calc.compute_lden([], (45.47, -73.74), datetime.date(2026, 6, 7))
        assert lden == 0.0

    def test_retourne_float(self, calc, aca750):
        lden = calc.compute_lden([aca750], (45.47, -73.74), datetime.date(2026, 6, 7))
        assert isinstance(lden, float)

    def test_penalite_nuit_superieure_au_jour(self, calc):
        r = (45.47, -73.74)
        d = datetime.date(2026, 6, 7)
        lden_day   = calc.compute_lden([_make_flight_at_hour(12)], r, d)
        lden_night = calc.compute_lden([_make_flight_at_hour(2)],  r, d)
        assert lden_night > lden_day

    def test_ordre_penalites_jour_soir_nuit(self, calc):
        r = (45.47, -73.74)
        d = datetime.date(2026, 6, 7)
        lden_day   = calc.compute_lden([_make_flight_at_hour(12)], r, d)
        lden_eve   = calc.compute_lden([_make_flight_at_hour(21)], r, d)
        lden_night = calc.compute_lden([_make_flight_at_hour(2)],  r, d)
        assert lden_day < lden_eve < lden_night

    def test_plusieurs_vols_lden_superieur(self, calc):
        r = (45.47, -73.74)
        d = datetime.date(2026, 6, 7)
        fl1 = _make_flight_at_hour(10)
        fl2 = _make_flight_at_hour(11)
        lden_1 = calc.compute_lden([fl1],      r, d)
        lden_2 = calc.compute_lden([fl1, fl2], r, d)
        assert lden_2 > lden_1


# ---------------------------------------------------------------------------
# compute_grid
# ---------------------------------------------------------------------------

class TestComputeGrid:
    def test_shape_sortie(self, calc, aca750):
        grid = np.array([[45.47, -73.74], [45.50, -73.80], [45.40, -73.60]])
        assert calc.compute_grid([aca750], grid).shape == (3,)

    def test_valeurs_positives_pres_trajectoire(self, calc, aca750):
        grid = np.array([[45.47, -73.74]])
        assert calc.compute_grid([aca750], grid)[0] > 0.0

    def test_diminue_avec_distance(self, calc, aca750):
        grid = np.array([[45.47, -73.74], [43.00, -71.00]])
        result = calc.compute_grid([aca750], grid)
        assert result[0] > result[1]

    def test_sans_vols_retourne_zeros(self, calc):
        grid = np.array([[45.47, -73.74], [45.50, -73.80]])
        np.testing.assert_array_equal(calc.compute_grid([], grid), np.zeros(2))

    def test_coherent_avec_compute_lden(self, calc, aca750):
        receptor = (45.47, -73.74)
        lden_scalar = calc.compute_lden([aca750], receptor, datetime.date(2026, 6, 7))
        lden_grid = calc.compute_grid([aca750], np.array([list(receptor)]))[0]
        assert abs(lden_grid - lden_scalar) < 0.1


# ---------------------------------------------------------------------------
# _utc_hour
# ---------------------------------------------------------------------------

class TestUtcHour:
    @pytest.mark.parametrize("h", [0, 7, 12, 19, 23])
    def test_heures_cles(self, h):
        ts = int(datetime.datetime(2026, 6, 7, h, 0, 0,
                                   tzinfo=datetime.timezone.utc).timestamp())
        assert NoiseCalculator._utc_hour(ts) == h


# ---------------------------------------------------------------------------
# Cohérence scalaire / vectorisé
# ---------------------------------------------------------------------------

class TestVectorisation:
    def test_slant_range_vec_coherent(self, aca750):
        r = (45.47, -73.74)
        grid = np.array([list(r)])
        seg = aca750.segments[10]
        d_scalar = NoiseCalculator._slant_range(seg, r)
        d_vec = NoiseCalculator._slant_range_vec(seg, grid[:, 0], grid[:, 1])
        assert abs(d_vec[0] - d_scalar) < 0.01

    def test_correction_lateral_vec_coherent(self, calc, aca750):
        r = (45.47, -73.74)
        grid = np.array([list(r)])
        seg = aca750.segments[10]
        corr_scalar = calc._correction_lateral(seg, r)
        d_vec = NoiseCalculator._slant_range_vec(seg, grid[:, 0], grid[:, 1])
        corr_vec = NoiseCalculator._correction_lateral_vec(
            seg, grid[:, 0], grid[:, 1], d_vec
        )[0]
        assert abs(corr_vec - corr_scalar) < 0.01
