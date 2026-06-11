# Responsable : Bouchra
# Tests unitaires pour ANPDatabase
#Suite de tests pytest pour ANPDatabase (Bouchra)
#MGA 802 — ÉTS Montréal, Été 2026

#Unités réelles Eurocontrol v9 :
  #- Distances : en mètres après conversion ft→m
    #[61, 122, 192, 305, 610, 1219, 1920, 3048, 4877, 7620]
  #- Thrust     : en lbs de poussée (pas en % N1)
  #- Métrique   : SEL uniquement après filtrage

import math
import warnings

import numpy as np
import pandas as pd
import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from airnoisepy.database.anp import ANPDatabase


# Distances standard en mètres (après conversion ft→m)
DISTANCES_M = [61, 122, 192, 305, 610, 1219, 1920, 3048, 4877, 7620]
# Thrust synthétique en lbs
THRUST_LBS = [4500.0, 9000.0, 13000.0, 18000.0, 23000.0]


# ------------------------------------------------------------------ #
#  Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def db_synthetic():
    return ANPDatabase()


@pytest.fixture
def db_custom():
    """Base construite manuellement avec deux avions (A320, B738)."""
    records = []
    for aircraft in ("A320", "B738"):
        for op in ("departure", "arrival"):
            for thrust in THRUST_LBS:
                l0 = 84.8 + (thrust - THRUST_LBS[0]) / (THRUST_LBS[-1] - THRUST_LBS[0]) * 10.0
                row = {"aircraft_id": aircraft, "operation": op,
                       "metric": "SEL", "thrust": thrust}
                d_ref = 305.0
                for d in DISTANCES_M:
                    row[f"{d}m"] = round(
                        l0 - 20.0 * np.log10(d / d_ref) - 0.005 * (d - d_ref) / d_ref, 1
                    )
                records.append(row)
    db = ANPDatabase()
    db._data = pd.DataFrame(records)
    db._build_interpolators()
    db.thrust_levels = THRUST_LBS
    db.source = "custom"
    return db


# ------------------------------------------------------------------ #
#  1. Initialisation                                                   #
# ------------------------------------------------------------------ #

class TestInit:

    def test_source_synthetic(self, db_synthetic):
        assert db_synthetic.source == "synthetic"

    def test_distances_list(self, db_synthetic):
        assert db_synthetic.distances == DISTANCES_M

    def test_thrust_levels_synthetic(self, db_synthetic):
        assert db_synthetic.thrust_levels == THRUST_LBS

    def test_data_not_empty(self, db_synthetic):
        assert db_synthetic._data is not None
        assert len(db_synthetic._data) > 0

    def test_missing_filepath_uses_synthetic(self):
        db = ANPDatabase(filepath=None)
        assert db.source == "synthetic"

    def test_invalid_filepath_raises(self):
        with pytest.raises(FileNotFoundError):
            ANPDatabase(filepath="/nonexistent/path/anp.xlsx")


# ------------------------------------------------------------------ #
#  2. load_synthetic                                                   #
# ------------------------------------------------------------------ #

class TestLoadSynthetic:

    def test_only_a320(self, db_synthetic):
        assert db_synthetic.list_aircraft() == ["A320"]

    def test_both_operations(self, db_synthetic):
        ops = db_synthetic._data["operation"].unique()
        assert "departure" in ops
        assert "arrival" in ops

    def test_all_thrust_levels_present(self, db_synthetic):
        thrusts = sorted(db_synthetic._data["thrust"].unique().tolist())
        assert thrusts == THRUST_LBS

    def test_all_distances_present(self, db_synthetic):
        dist_cols = sorted(
            [c for c in db_synthetic._data.columns if c.endswith("m") and
             c.replace("m", "").isdigit()],
            key=lambda c: int(c.replace("m", ""))
        )
        dist_values = [int(c.replace("m", "")) for c in dist_cols]
        assert dist_values == DISTANCES_M

    def test_l0_at_305m_min_thrust(self, db_synthetic):
        """À 305m (=1000ft) / thrust minimal → L0 de référence ≈ 84.8 dB."""
        row = db_synthetic._data[
            (db_synthetic._data["aircraft_id"] == "A320") &
            (db_synthetic._data["operation"]   == "arrival") &
            (db_synthetic._data["thrust"]      == THRUST_LBS[0])
        ]
        assert not row.empty
        val = float(row["305m"].iloc[0])
        assert abs(val - 84.8) < 0.5

    def test_l0_at_305m_max_thrust(self, db_synthetic):
        """À 305m / thrust maximal → L0 ≈ 84.8 + 10 = 94.8 dB."""
        row = db_synthetic._data[
            (db_synthetic._data["aircraft_id"] == "A320") &
            (db_synthetic._data["operation"]   == "departure") &
            (db_synthetic._data["thrust"]      == THRUST_LBS[-1])
        ]
        assert not row.empty
        val = float(row["305m"].iloc[0])
        assert abs(val - 94.8) < 0.5

    def test_levels_decrease_with_distance(self, db_synthetic):
        """Chaque courbe NPD doit être strictement décroissante."""
        dist_cols = [f"{d}m" for d in DISTANCES_M]
        for _, row in db_synthetic._data.iterrows():
            levels = row[dist_cols].values.astype(float)
            assert all(levels[i] >= levels[i + 1] for i in range(len(levels) - 1))

    def test_higher_thrust_higher_level(self, db_synthetic):
        """Niveau à thrust max > thrust min (même distance 305m)."""
        row_min = db_synthetic._data[
            (db_synthetic._data["aircraft_id"] == "A320") &
            (db_synthetic._data["thrust"]      == THRUST_LBS[0])
        ]
        row_max = db_synthetic._data[
            (db_synthetic._data["aircraft_id"] == "A320") &
            (db_synthetic._data["thrust"]      == THRUST_LBS[-1])
        ]
        assert float(row_max["305m"].iloc[0]) > float(row_min["305m"].iloc[0])


# ------------------------------------------------------------------ #
#  3. get_npd                                                          #
# ------------------------------------------------------------------ #

class TestGetNPD:

    def test_returns_dataframe(self, db_synthetic):
        assert isinstance(db_synthetic.get_npd("A320", "departure"), pd.DataFrame)

    def test_correct_aircraft_returned(self, db_synthetic):
        npd = db_synthetic.get_npd("A320", "departure")
        assert (npd["aircraft_id"] == "A320").all()

    def test_correct_operation_returned(self, db_synthetic):
        npd = db_synthetic.get_npd("A320", "arrival")
        assert (npd["operation"] == "arrival").all()

    def test_unknown_aircraft_raises(self, db_synthetic):
        with pytest.raises(KeyError):
            db_synthetic.get_npd("B777", "departure")

    def test_unknown_operation_raises(self, db_synthetic):
        with pytest.raises(KeyError):
            db_synthetic.get_npd("A320", "cruise")

    def test_custom_multiple_aircraft(self, db_custom):
        assert not db_custom.get_npd("A320", "departure").empty
        assert not db_custom.get_npd("B738", "arrival").empty

    def test_metric_sel_default(self, db_synthetic):
        assert not db_synthetic.get_npd("A320", "departure", metric="SEL").empty


# ------------------------------------------------------------------ #
#  4. interpolate                                                      #
# ------------------------------------------------------------------ #

class TestInterpolate:

    @pytest.mark.parametrize("distance,thrust", [
        (61,   THRUST_LBS[0]),
        (305,  THRUST_LBS[2]),
        (1219, THRUST_LBS[-1]),
        (7620, THRUST_LBS[0]),
    ])
    def test_returns_float_at_grid_points(self, db_synthetic, distance, thrust):
        val = db_synthetic.interpolate("A320", "departure", distance, thrust)
        assert isinstance(val, float)
        assert not math.isnan(val)

    def test_exact_value_at_305m_min_thrust(self, db_synthetic):
        """interpolate doit retrouver la valeur de la table à 305m / thrust min."""
        expected = float(
            db_synthetic._data[
                (db_synthetic._data["aircraft_id"] == "A320") &
                (db_synthetic._data["operation"]   == "departure") &
                (db_synthetic._data["thrust"]      == THRUST_LBS[0])
            ]["305m"].iloc[0]
        )
        val = db_synthetic.interpolate("A320", "departure", 305.0, THRUST_LBS[0])
        assert abs(val - expected) < 0.1

    def test_interpolated_value_between_grid_points(self, db_synthetic):
        """Valeur à 500m doit être comprise entre 305m et 610m."""
        val_305 = db_synthetic.interpolate("A320", "departure", 305.0,  THRUST_LBS[2])
        val_610 = db_synthetic.interpolate("A320", "departure", 610.0,  THRUST_LBS[2])
        val_500 = db_synthetic.interpolate("A320", "departure", 500.0,  THRUST_LBS[2])
        assert val_610 < val_500 < val_305

    def test_interpolated_value_between_thrust_levels(self, db_synthetic):
        """Valeur entre thrust[1] et thrust[2] doit être comprise entre les deux."""
        t_low  = THRUST_LBS[1]
        t_high = THRUST_LBS[2]
        t_mid  = (t_low + t_high) / 2.0
        val_low  = db_synthetic.interpolate("A320", "departure", 305.0, t_low)
        val_high = db_synthetic.interpolate("A320", "departure", 305.0, t_high)
        val_mid  = db_synthetic.interpolate("A320", "departure", 305.0, t_mid)
        assert val_low < val_mid < val_high

    def test_clipping_below_min_distance(self, db_synthetic):
        """Distance < 61m → clippée à 61m."""
        val_clip = db_synthetic.interpolate("A320", "departure", 61.0,  THRUST_LBS[2])
        val_low  = db_synthetic.interpolate("A320", "departure",  1.0,  THRUST_LBS[2])
        assert abs(val_clip - val_low) < 0.01

    def test_clipping_above_max_distance(self, db_synthetic):
        """Distance > 7620m → clippée à 7620m."""
        val_clip = db_synthetic.interpolate("A320", "departure", 7620.0,  THRUST_LBS[2])
        val_far  = db_synthetic.interpolate("A320", "departure", 50000.0, THRUST_LBS[2])
        assert abs(val_clip - val_far) < 0.01

    def test_clipping_thrust_below_min(self, db_synthetic):
        """Thrust < min → clippé à min."""
        val_clip = db_synthetic.interpolate("A320", "departure", 305.0, THRUST_LBS[0])
        val_low  = db_synthetic.interpolate("A320", "departure", 305.0, 10.0)
        assert abs(val_clip - val_low) < 0.01

    def test_clipping_thrust_above_max(self, db_synthetic):
        """Thrust > max → clippé à max."""
        val_clip = db_synthetic.interpolate("A320", "departure", 305.0, THRUST_LBS[-1])
        val_high = db_synthetic.interpolate("A320", "departure", 305.0, 999999.0)
        assert abs(val_clip - val_high) < 0.01

    def test_higher_thrust_higher_level_interpolated(self, db_synthetic):
        """thrust[3] doit donner un niveau > thrust[1] (interpolé)."""
        val_low  = db_synthetic.interpolate("A320", "arrival", 610.0, THRUST_LBS[1])
        val_high = db_synthetic.interpolate("A320", "arrival", 610.0, THRUST_LBS[3])
        assert val_high > val_low

    def test_closer_distance_higher_level(self, db_synthetic):
        """305m doit donner un niveau > 3048m."""
        val_near = db_synthetic.interpolate("A320", "arrival", 305.0,  THRUST_LBS[2])
        val_far  = db_synthetic.interpolate("A320", "arrival", 3048.0, THRUST_LBS[2])
        assert val_near > val_far

    def test_unknown_aircraft_raises(self, db_synthetic):
        with pytest.raises(KeyError):
            db_synthetic.interpolate("B777", "departure", 305.0, THRUST_LBS[0])

    def test_departure_vs_arrival_both_valid(self, db_synthetic):
        val_dep = db_synthetic.interpolate("A320", "departure", 305.0, THRUST_LBS[2])
        val_arr = db_synthetic.interpolate("A320", "arrival",   305.0, THRUST_LBS[2])
        assert isinstance(val_dep, float)
        assert isinstance(val_arr, float)


# ------------------------------------------------------------------ #
#  5. list_aircraft                                                    #
# ------------------------------------------------------------------ #

class TestListAircraft:

    def test_synthetic_returns_a320(self, db_synthetic):
        assert db_synthetic.list_aircraft() == ["A320"]

    def test_custom_returns_all_types(self, db_custom):
        aircraft = db_custom.list_aircraft()
        assert "A320" in aircraft
        assert "B738" in aircraft

    def test_returns_sorted_list(self, db_custom):
        aircraft = db_custom.list_aircraft()
        assert aircraft == sorted(aircraft)

    def test_returns_list(self, db_synthetic):
        assert isinstance(db_synthetic.list_aircraft(), list)


# ------------------------------------------------------------------ #
#  6. _map_icao_codes — format NPD_ID Eurocontrol v9                  #
# ------------------------------------------------------------------ #

class TestMapIcaoCodes:

    @pytest.mark.parametrize("npd_id,expected_code", [
        ("A320-250N",  "A320"),
        ("A320-270N",  "A320"),
        ("747400RN",   "B744"),
        ("ERJ190-300", "E290"),
        ("A330-743L",  "A333"),
    ])
    def test_eurocontrol_npd_ids_mapped_correctly(self, db_synthetic, npd_id, expected_code):
        df = pd.DataFrame({"aircraft_id": [npd_id]})
        result = db_synthetic._map_icao_codes(df)
        assert result["aircraft_id"].iloc[0] == expected_code

    def test_case_insensitive_match(self, db_synthetic):
        """La correspondance doit fonctionner quelle que soit la casse."""
        df = pd.DataFrame({"aircraft_id": ["a320-250n"]})
        result = db_synthetic._map_icao_codes(df)
        assert result["aircraft_id"].iloc[0] == "A320"

    def test_already_oaci_code_preserved(self, db_synthetic):
        """Un code déjà court et inconnu est retourné tel quel."""
        df = pd.DataFrame({"aircraft_id": ["UNKNOWN_TYPE"]})
        result = db_synthetic._map_icao_codes(df)
        assert result["aircraft_id"].iloc[0] == "UNKNOWN_TYPE"

    def test_unknown_name_preserved_as_is(self, db_synthetic):
        df = pd.DataFrame({"aircraft_id": ["FlyingMachine 9000"]})
        result = db_synthetic._map_icao_codes(df)
        assert result["aircraft_id"].iloc[0] == "FlyingMachine 9000"


# ------------------------------------------------------------------ #
#  7. _validate_monotonicity                                           #
# ------------------------------------------------------------------ #

class TestValidateMonotonicity:

    def test_synthetic_no_warning(self, db_synthetic):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            db_synthetic._validate_monotonicity(db_synthetic._data)
        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert len(user_warnings) == 0

    def test_non_monotone_raises_warning(self, db_synthetic):
        """Une courbe avec valeur croissante doit générer un UserWarning."""
        bad_row = {
            "aircraft_id": "TEST", "operation": "departure",
            "metric": "SEL", "thrust": 13000.0,
            "61m":   95.0, "122m":  90.0, "192m": 100.0,   # ← 192m > 122m
            "305m":  80.0, "610m":  72.0, "1219m": 65.0,
            "1920m": 59.0, "3048m": 52.0, "4877m": 45.0, "7620m": 38.0,
        }
        df_bad = pd.DataFrame([bad_row])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            db_synthetic._validate_monotonicity(df_bad)
        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert len(user_warnings) >= 1


# ------------------------------------------------------------------ #
#  8. Cohérence physique — valeurs Eurocontrol réelles                 #
# ------------------------------------------------------------------ #

class TestPhysicalConsistency:

    def test_a320_approach_305m_realistic_range(self, db_synthetic):
        """A320 à 305m (≈1000ft) / thrust minimal → plage réaliste 80–92 dB."""
        val = db_synthetic.interpolate("A320", "arrival", 305.0, THRUST_LBS[0])
        assert 78.0 <= val <= 95.0

    def test_a320_takeoff_305m_realistic_range(self, db_synthetic):
        """A320 à 305m / thrust maximal → plage réaliste 88–100 dB."""
        val = db_synthetic.interpolate("A320", "departure", 305.0, THRUST_LBS[-1])
        assert 85.0 <= val <= 102.0

    def test_a320_far_distance_low_level(self, db_synthetic):
        """A320 à 7620m → niveau < 70 dB."""
        val = db_synthetic.interpolate("A320", "departure", 7620.0, THRUST_LBS[2])
        assert val < 70.0

    def test_a320_near_distance_high_level(self, db_synthetic):
        """A320 à 61m → niveau > 90 dB."""
        val = db_synthetic.interpolate("A320", "departure", 61.0, THRUST_LBS[-1])
        assert val > 90.0

