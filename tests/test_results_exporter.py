# Responsable : Laura
# Tests unitaires pour ResultsExporter

"""
Tests unitaires pour la classe ResultsExporter.

Ces tests vérifient que la classe responsable de l'exportation des résultats
crée correctement les fichiers de sortie attendus :
CSV, carte HTML Folium et animation GIF.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from airnoisepy.results_exporter import ResultsExporter


def test_results_exporter_creates_output_directory(tmp_path):
    """
    Vérifie que ResultsExporter crée automatiquement le dossier de sortie.

    :param tmp_path: Dossier temporaire fourni par pytest.
    :type tmp_path: pathlib.Path
    """

    output_dir = tmp_path / "results"

    exporter = ResultsExporter(output_dir=output_dir)

    assert output_dir.exists()
    assert output_dir.is_dir()
    assert exporter.output_dir == output_dir


def test_export_csv_creates_file(tmp_path):
    """
    Vérifie que export_csv crée un fichier CSV valide.

    :param tmp_path: Dossier temporaire fourni par pytest.
    :type tmp_path: pathlib.Path
    """

    exporter = ResultsExporter(output_dir=tmp_path)

    noise_levels = [55.2, 60.1]
    receptor_grid = [
        (45.47, -73.74),
        (45.48, -73.75),
    ]

    output_file = exporter.export_csv(noise_levels, receptor_grid)

    output_path = Path(output_file)

    assert output_path.exists()
    assert output_path.suffix == ".csv"

    df = pd.read_csv(output_path)

    assert list(df.columns) == ["latitude", "longitude", "lden_db"]
    assert len(df) == 2
    assert df.loc[0, "latitude"] == 45.47
    assert df.loc[0, "longitude"] == -73.74
    assert df.loc[0, "lden_db"] == 55.2


def test_export_csv_raises_error_when_lengths_do_not_match(tmp_path):
    """
    Vérifie que export_csv lève une erreur si le nombre de niveaux de bruit
    ne correspond pas au nombre de récepteurs.

    :param tmp_path: Dossier temporaire fourni par pytest.
    :type tmp_path: pathlib.Path
    """

    exporter = ResultsExporter(output_dir=tmp_path)

    noise_levels = [55.2, 60.1, 70.4]
    receptor_grid = [
        (45.47, -73.74),
        (45.48, -73.75),
    ]

    with pytest.raises(ValueError):
        exporter.export_csv(noise_levels, receptor_grid)


def test_export_map_creates_html_file(tmp_path):
    """
    Vérifie que export_map crée un fichier HTML contenant une carte Folium.

    :param tmp_path: Dossier temporaire fourni par pytest.
    :type tmp_path: pathlib.Path
    """

    exporter = ResultsExporter(output_dir=tmp_path)

    noise_levels = [52.0, 60.5, 68.2]
    receptor_grid = [
        (45.47, -73.74),
        (45.48, -73.75),
        (45.49, -73.76),
    ]

    output_file = exporter.export_map(noise_levels, receptor_grid)

    output_path = Path(output_file)

    assert output_path.exists()
    assert output_path.suffix == ".html"

    html_content = output_path.read_text(encoding="utf-8")

    assert "Lden" in html_content
    assert "leaflet" in html_content.lower()


def test_export_map_raises_error_when_lengths_do_not_match(tmp_path):
    """
    Vérifie que export_map lève une erreur si les données d'entrée ne sont
    pas cohérentes.

    :param tmp_path: Dossier temporaire fourni par pytest.
    :type tmp_path: pathlib.Path
    """

    exporter = ResultsExporter(output_dir=tmp_path)

    noise_levels = [52.0]
    receptor_grid = [
        (45.47, -73.74),
        (45.48, -73.75),
    ]

    with pytest.raises(ValueError):
        exporter.export_map(noise_levels, receptor_grid)


def test_export_animation_gif_creates_file(tmp_path):
    """
    Vérifie que export_animation_gif crée un fichier GIF valide.

    :param tmp_path: Dossier temporaire fourni par pytest.
    :type tmp_path: pathlib.Path
    """

    exporter = ResultsExporter(output_dir=tmp_path)

    frame_black = np.zeros((100, 100, 3), dtype=np.uint8)
    frame_white = np.ones((100, 100, 3), dtype=np.uint8) * 255

    frames = [frame_black, frame_white]

    output_file = exporter.export_animation_gif(frames, fps=1)

    output_path = Path(output_file)

    assert output_path.exists()
    assert output_path.suffix == ".gif"
    assert output_path.stat().st_size > 0


def test_export_animation_gif_raises_error_for_empty_frames(tmp_path):
    """
    Vérifie que export_animation_gif lève une erreur lorsque la liste
    d'images est vide.

    :param tmp_path: Dossier temporaire fourni par pytest.
    :type tmp_path: pathlib.Path
    """

    exporter = ResultsExporter(output_dir=tmp_path)

    with pytest.raises(ValueError):
        exporter.export_animation_gif([])


def test_export_animation_gif_raises_error_for_invalid_fps(tmp_path):
    """
    Vérifie que export_animation_gif lève une erreur lorsque fps est nul
    ou négatif.

    :param tmp_path: Dossier temporaire fourni par pytest.
    :type tmp_path: pathlib.Path
    """

    exporter = ResultsExporter(output_dir=tmp_path)

    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    with pytest.raises(ValueError):
        exporter.export_animation_gif([frame], fps=0)