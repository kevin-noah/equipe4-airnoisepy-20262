# Responsable : Syndia
# Tests unitaires pour NoiseContour

import datetime
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from airnoisepy.noise.contour import (
    NoiseContour,
    YUL_LATITUDE,
    YUL_LONGITUDE,
    KM_PAR_DEGRE_LATITUDE,
    KM_PAR_DEGRE_LONGITUDE,
)

#Données de test

def _make_calculator(lden_valeur=65.0, lden_grid=None):
    """
    Crée un MockNoiseCalculator avec des valeurs Lden fictives.
    NoiseCalculator n'est pas importé.
    """

    mock = MagicMock()
    mock.compute_lden.return_value = lden_valeur
    if lden_grid is not None:
        mock.compute_grid.return_value = lden_grid
    else:
        mock.compute_grid.side_effect = lambda flights, grid, *args, **kwargs: \
            np.full(len(grid), lden_valeur)
    return mock

def _make_lden_values(noisecalculator, valeur=65.0):
    """Crée un tableau de Lden fictifs de la bonne taille pour noise contour."""
    return np.full(len(noisecalculator.receptor_grid), valeur)

def _make_capteurs_adm():
    """Capteurs ADM fictifs proches de YUL."""
    return [
        {'nom': 'Dorval',  'lat': 45.450, 'lon': -73.750, 'lden_mesure': 62.5},
        {'nom': 'Lachine', 'lat': 45.430, 'lon': -73.700, 'lden_mesure': 58.3},]

#fixtures

@pytest.fixture
def calculator():
    """MockNoiseCalculator retournant 65 dB partout."""
    return _make_calculator(lden_valeur=65.0)


@pytest.fixture
def noisecalculator(calculator):
    """NoiseContour avec grille réduite (grid_size=20) pour les tests rapides."""
    return NoiseContour(calculator=calculator, grid_size=20)


@pytest.fixture
def noisecalculator_custom(calculator):
    """NoiseContour avec paramètres personnalisés."""
    return NoiseContour(calculator=calculator,
                        center_latitude=45.47, center_longitude=-73.74,
                        radius_km=10.0, grid_size=20)


@pytest.fixture
def lden_values(noisecalculator):
    """Tableau de Lden fictifs à 65 dB pour toute la grille."""
    return _make_lden_values(noisecalculator, valeur=65.0)


@pytest.fixture
def lden_values_varies(noisecalculator):
    """Tableau de Lden avec variation : 55 à 75 dB."""
    n = len(noisecalculator.receptor_grid)
    return np.linspace(55.0, 75.0, n)

#Test __init__

class TestInit:

    def test_attributs_stockes(self, calculator, noisecalculator):
        assert noisecalculator.calculator is calculator
        assert noisecalculator.center == (YUL_LATITUDE, YUL_LONGITUDE)
        assert noisecalculator.radius_km == 25.0
        assert noisecalculator.grid_size == 20

    def test_center_par_defaut_yul(self, noisecalculator):
        assert noisecalculator.center[0] == pytest.approx(YUL_LATITUDE, abs=1e-4)
        assert noisecalculator.center[1] == pytest.approx(YUL_LONGITUDE, abs=1e-4)

    def test_receptor_grid_construit_a_linit(self, noisecalculator):
        assert noisecalculator.receptor_grid is not None
        assert isinstance(noisecalculator.receptor_grid, np.ndarray)

    def test_parametres_personnalises(self, calculator):
        noisecalculator = NoiseContour(calculator=calculator,
                          center_latitude=45.0, center_longitude=-73.0,
                          radius_km=10.0, grid_size=50)
        assert noisecalculator.center == (45.0, -73.0)
        assert noisecalculator.radius_km == 10.0
        assert noisecalculator.grid_size == 50

    def test_calculator_stocke(self, calculator, noisecalculator):
        assert noisecalculator.calculator is calculator

#Test get_receptor_grid

class TestGetReceptorGrid:

    def test_retourne_meme_objet_que_receptor_grid(self, noisecalculator):
        assert noisecalculator.get_receptor_grid() is noisecalculator.receptor_grid

    def test_shape_correcte(self, noisecalculator):
        grid = noisecalculator.get_receptor_grid()
        assert grid.ndim == 2
        assert grid.shape[1] == 2

    def test_type_ndarray(self, noisecalculator):
        assert isinstance(noisecalculator.get_receptor_grid(), np.ndarray)

#Test compute_lden_grid

class TestComputeLdenGrid:

    def test_appelle_compute_grid(self, noisecalculator, calculator):
        flights = [MagicMock()]
        date = datetime.date(2026, 5, 31)
        noisecalculator.compute_lden_grid(flights, date)
        calculator.compute_grid.assert_called_once()

    def test_transmet_receptor_grid(self, noisecalculator, calculator):
        flights = [MagicMock()]
        date = datetime.date(2026, 5, 31)
        noisecalculator.compute_lden_grid(flights, date)
        args = calculator.compute_grid.call_args[0]
        np.testing.assert_array_equal(args[1], noisecalculator.receptor_grid)

    def test_transmet_flights(self, noisecalculator, calculator):
        flights = [MagicMock(), MagicMock()]
        date = datetime.date(2026, 5, 31)
        noisecalculator.compute_lden_grid(flights, date)
        args = calculator.compute_grid.call_args[0]
        assert args[0] is flights

    def test_retourne_ndarray(self, noisecalculator, calculator):
        flights = [MagicMock()]
        date = datetime.date(2026, 5, 31)
        result = noisecalculator.compute_lden_grid(flights, date)
        assert isinstance(result, np.ndarray)

    def test_aircraft_type_transmis(self, noisecalculator, calculator):
        flights = [MagicMock()]
        date = datetime.date(2026, 5, 31)
        noisecalculator.compute_lden_grid(flights, date, aircraft_type="B738")
        args = calculator.compute_grid.call_args[0]
        assert args[2] == "B738"

#Tests compute_lden_recepteur

class TestComputeLdenRecepteur:

    def test_appelle_compute_lden(self, noisecalculator, calculator):
        flights = [MagicMock()]
        recepteur = (45.47, -73.74)
        date = datetime.date(2026, 5, 31)
        noisecalculator.compute_lden_recepteur(flights, recepteur, date)
        calculator.compute_lden.assert_called_once()

    def test_transmet_recepteur(self, noisecalculator, calculator):
        flights = [MagicMock()]
        recepteur = (45.47, -73.74)
        date = datetime.date(2026, 5, 31)
        noisecalculator.compute_lden_recepteur(flights, recepteur, date)
        args = calculator.compute_lden.call_args[0]
        assert args[1] == recepteur

    def test_retourne_float(self, noisecalculator, calculator):
        flights = [MagicMock()]
        recepteur = (45.47, -73.74)
        date = datetime.date(2026, 5, 31)
        result = noisecalculator.compute_lden_recepteur(flights, recepteur, date)
        assert isinstance(result, float)

    def test_valeur_retournee_par_calculator(self, noisecalculator, calculator):
        calculator.compute_lden.return_value = 67.3
        flights = [MagicMock()]
        recepteur = (45.47, -73.74)
        date = datetime.date(2026, 5, 31)
        result = noisecalculator.compute_lden_recepteur(flights, recepteur, date)
        assert result == pytest.approx(67.3)

#Tests plot

class TestPlot:

    def test_retourne_fig_et_ax(self, noisecalculator, lden_values_varies):
        with patch("matplotlib.pyplot.show"):
            fig, ax = noisecalculator.plot(lden_values_varies, basemap=False)
        assert fig is not None
        assert ax is not None

    def test_sauvegarde_si_save_path(self, noisecalculator, lden_values_varies, tmp_path):
        save_path = str(tmp_path / "test_lden.png")
        with patch("matplotlib.pyplot.show"):
            noisecalculator.plot(lden_values_varies, basemap=False, save_path=save_path)
        import os
        assert os.path.isfile(save_path)

    def test_title_accepte(self, noisecalculator, lden_values_varies):
        with patch("matplotlib.pyplot.show"):
            fig, ax = noisecalculator.plot(lden_values_varies, title="Test titre", basemap=False)
        assert ax.get_title() == "Test titre"

    def test_sans_basemap_ne_crash_pas(self, noisecalculator, lden_values_varies):
        with patch("matplotlib.pyplot.show"):
            fig, ax = noisecalculator.plot(lden_values_varies, basemap=False)
        assert fig is not None


#Tests Méthodes privées

#Tests _build_grid

class TestBuildGrid:

    def test_retourne_ndarray(self, noisecalculator):
        assert isinstance(noisecalculator.receptor_grid, np.ndarray)

    def test_shape_deux_colonnes(self, noisecalculator):
        assert noisecalculator.receptor_grid.ndim == 2
        assert noisecalculator.receptor_grid.shape[1] == 2

    def test_points_dans_le_cercle(self, noisecalculator):
        center_lat, center_lon = noisecalculator.center
        latitudes = noisecalculator.receptor_grid[:, 0]
        longitudes = noisecalculator.receptor_grid[:, 1]
        distances_km = np.sqrt(
            ((latitudes - center_lat) * KM_PAR_DEGRE_LATITUDE) ** 2 +
            ((longitudes - center_lon) * KM_PAR_DEGRE_LONGITUDE) ** 2
        )
        assert np.all(distances_km <= noisecalculator.radius_km + 1e-6)

    def test_grille_non_vide(self, noisecalculator):
        assert len(noisecalculator.receptor_grid) > 0

    def test_grille_plus_grande_avec_grand_rayon(self, calculator):
        noisecalculator_petit = NoiseContour(calculator=calculator, radius_km=5.0, grid_size=20)
        noisecalculator_grand = NoiseContour(calculator=calculator, radius_km=20.0, grid_size=20)

        center_latitude, center_longitude = noisecalculator_grand.center
        latitudes_grand = noisecalculator_grand.receptor_grid[:, 0]
        longitudes_grand = noisecalculator_grand.receptor_grid[:, 1]
        dist_max_grand = np.max(np.sqrt(
            ((latitudes_grand - center_latitude) * KM_PAR_DEGRE_LATITUDE) ** 2 +
            ((longitudes_grand - center_longitude) * KM_PAR_DEGRE_LONGITUDE) ** 2
        ))

        latitudes_petit = noisecalculator_petit.receptor_grid[:, 0]
        longitudes_petit = noisecalculator_petit.receptor_grid[:, 1]
        dist_max_petit = np.max(np.sqrt(
            ((latitudes_petit - center_latitude) * KM_PAR_DEGRE_LATITUDE) ** 2 +
            ((longitudes_petit - center_longitude) * KM_PAR_DEGRE_LONGITUDE) ** 2
        ))

        assert dist_max_grand > dist_max_petit

    def test_centre_dans_la_grille(self, noisecalculator):
        center_latitude, center_longitude = noisecalculator.center
        latitudes = noisecalculator.receptor_grid[:, 0]
        longitudes = noisecalculator.receptor_grid[:, 1]
        distances = np.sqrt((latitudes - center_latitude) ** 2 + (longitudes - center_longitude) ** 2)
        assert np.min(distances) < 0.1

    def test_colonne_0_sont_latitudes(self, noisecalculator):
        latitudes = noisecalculator.receptor_grid[:, 0]
        longitudes = noisecalculator.receptor_grid[:, 1]
        assert np.all((latitudes > 44.0) & (latitudes < 47.0))
        assert np.all((longitudes > -75.0) & (longitudes < -72.0))

#Tests _interpolate_surface

class TestInterpolerSurface:

    def test_retourne_trois_elements(self, noisecalculator, lden_values):
        result = noisecalculator._interpoler_surface(lden_values)
        assert len(result) == 3

    def test_z_grid_shape(self, noisecalculator, lden_values):
        z_grid, latitude_lin, longitude_lin = noisecalculator._interpoler_surface(lden_values)
        assert z_grid.shape == (noisecalculator.grid_size, noisecalculator.grid_size)

    def test_latitude_lin_shape(self, noisecalculator, lden_values):
        z_grid, latitude_lin, longitude_lin = noisecalculator._interpoler_surface(lden_values)
        assert len(latitude_lin) == noisecalculator.grid_size

    def test_longitude_lin_shape(self, noisecalculator, lden_values):
        z_grid, latitude_lin, longitude_lin = noisecalculator._interpoler_surface(lden_values)
        assert len(longitude_lin) == noisecalculator.grid_size

    def test_latitude_lin_croissant(self, noisecalculator, lden_values):
        z_grid, latitude_lin, longitude_lin = noisecalculator._interpoler_surface(lden_values)
        assert np.all(np.diff(latitude_lin) > 0)

    def test_longitude_lin_croissant(self, noisecalculator, lden_values):
        z_grid, latitude_lin, longitude_lin = noisecalculator._interpoler_surface(lden_values)
        assert np.all(np.diff(longitude_lin) > 0)

    def test_z_grid_valeurs_dans_plage(self, noisecalculator, lden_values):
        z_grid, _, _ = noisecalculator._interpoler_surface(lden_values)
        valeur_min = float(np.nanmin(lden_values))
        valeur_max = float(np.nanmax(lden_values))
        assert np.nanmin(z_grid) >= valeur_min - 1e-6
        assert np.nanmax(z_grid) <= valeur_max + 1.0

    def test_couvre_zone_yul(self, noisecalculator, lden_values):
        center_latitude, center_longitude = noisecalculator.center
        z_grid, latitude_lin, longitude_lin = noisecalculator._interpoler_surface(lden_values)
        assert latitude_lin[0] < center_latitude < latitude_lin[-1]
        assert longitude_lin[0] < center_longitude < longitude_lin[-1]

