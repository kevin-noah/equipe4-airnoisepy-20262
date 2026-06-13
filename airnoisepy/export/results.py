# Responsable : Laura
# Classe ResultsExporter — carte folium HTML, animation 24h MP4/GIF, export CSV
"""
Module d'exportation des résultats pour AirNoisePy.

Ce module contient la classe ResultsExporter. Cette classe est responsable
de sauvegarder les résultats produits par le programme sous différents formats :
CSV, carte HTML, animation et rapport de validation.
"""

from pathlib import Path

import pandas as pd
import folium
import imageio.v2 as imageio

class ResultsExporter:
    """
    Classe responsable de l'exportation des résultats du projet AirNoisePy.

    Cette classe centralise les méthodes permettant de sauvegarder les
    résultats finaux du calcul de bruit aérien. Elle ne calcule pas le bruit
    elle-même. Elle reçoit plutôt des résultats déjà produits par les autres
    modules du projet et les transforme en fichiers exploitables.

    :param output_dir: Dossier dans lequel les fichiers de sortie seront créés.
    :type output_dir: str
    """

    def __init__(self, output_dir="results"):
        """
        Initialise l'exportateur de résultats.

        Le constructeur crée automatiquement le dossier de sortie si celui-ci
        n'existe pas déjà. Cela permet d'éviter une erreur au moment de
        sauvegarder un fichier.

        :param output_dir: Dossier de sauvegarde des résultats.
        :type output_dir: str
        """

        # Conversion du chemin reçu en objet Path.
        # Path facilite la gestion des chemins de fichiers en Python.
        self.output_dir = Path(output_dir)

        # Création du dossier de sortie s'il n'existe pas déjà.
        # parents=True permet aussi de créer les dossiers parents si nécessaire.
        # exist_ok=True évite une erreur si le dossier existe déjà.
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_csv(self, noise_levels, receptor_grid, output_path=None):
        """
        Exporte les niveaux de bruit calculés dans un fichier CSV.

        Cette méthode reçoit les niveaux de bruit calculés pour chaque
        récepteur au sol et les coordonnées correspondantes. Elle crée ensuite
        un fichier CSV contenant trois colonnes principales : latitude,
        longitude et lden_db.

        :param noise_levels: Niveaux de bruit calculés, en dB(A).
        :type noise_levels: list or numpy.ndarray
        :param receptor_grid: Coordonnées des récepteurs au sol sous la forme
            [(latitude, longitude), ...].
        :type receptor_grid: list or numpy.ndarray
        :param output_path: Chemin optionnel du fichier CSV à créer. Si aucune
            valeur n'est fournie, le fichier est créé dans le dossier de sortie.
        :type output_path: str or None
        :return: Chemin du fichier CSV généré.
        :rtype: str
        :raises ValueError: Si le nombre de niveaux de bruit ne correspond pas
            au nombre de récepteurs.
        """

        # Vérification que les deux listes ont la même longueur.
        # Chaque niveau de bruit doit correspondre à un récepteur précis.
        if len(noise_levels) != len(receptor_grid):
            raise ValueError(
                "Le nombre de niveaux de bruit doit correspondre "
                "au nombre de récepteurs."
            )

        # Si aucun chemin n'est fourni, on crée un nom de fichier par défaut
        # dans le dossier de sortie défini à l'initialisation.
        if output_path is None:
            output_path = self.output_dir / "noise_levels.csv"
        else:
            output_path = Path(output_path)

        # Construction du tableau de données.
        # Chaque ligne contient la latitude, la longitude et le niveau Lden.
        data = []

        for receptor, noise_level in zip(receptor_grid, noise_levels):
            latitude = receptor[0]
            longitude = receptor[1]

            data.append(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "lden_db": noise_level,
                }
            )

        # Conversion des données en DataFrame pandas.
        # Pandas facilite ensuite l'écriture propre du fichier CSV.
        df = pd.DataFrame(data)

        # Création du dossier parent si l'utilisateur fournit un chemin
        # vers un dossier qui n'existe pas encore.
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Export du DataFrame vers un fichier CSV.
        # index=False évite d'ajouter une colonne d'index inutile.
        df.to_csv(output_path, index=False)

        # Retourne le chemin du fichier sous forme de texte.
        return str(output_path)

    def export_map(self, noise_levels, receptor_grid, output_path=None):
        """
        Exporte les niveaux de bruit sur une carte HTML interactive.

        Cette méthode crée une carte interactive avec Folium. Chaque récepteur
        est représenté par un marqueur circulaire placé à sa latitude et sa
        longitude. La couleur du marqueur dépend du niveau de bruit Lden.

        :param noise_levels: Niveaux de bruit calculés, en dB(A).
        :type noise_levels: list or numpy.ndarray
        :param receptor_grid: Coordonnées des récepteurs au sol sous la forme
            [(latitude, longitude), ...].
        :type receptor_grid: list or numpy.ndarray
        :param output_path: Chemin optionnel du fichier HTML à créer. Si aucune
            valeur n'est fournie, le fichier est créé dans le dossier de sortie.
        :type output_path: str or None
        :return: Chemin du fichier HTML généré.
        :rtype: str
        :raises ValueError: Si le nombre de niveaux de bruit ne correspond pas
            au nombre de récepteurs.
        """

        # Vérification que chaque niveau de bruit correspond à un récepteur.
        if len(noise_levels) != len(receptor_grid):
            raise ValueError(
                "Le nombre de niveaux de bruit doit correspondre "
                "au nombre de récepteurs."
            )

        # Si aucun chemin de sortie n'est fourni, on sauvegarde la carte
        # dans le dossier de sortie par défaut.
        if output_path is None:
            output_path = self.output_dir / "noise_map.html"
        else:
            output_path = Path(output_path)

        # Création du dossier parent si nécessaire.
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Calcul du centre de la carte.
        # On prend la moyenne des latitudes et longitudes des récepteurs.
        latitudes = [point[0] for point in receptor_grid]
        longitudes = [point[1] for point in receptor_grid]

        center_latitude = sum(latitudes) / len(latitudes)
        center_longitude = sum(longitudes) / len(longitudes)

        # Création de la carte Folium centrée sur la zone étudiée.
        noise_map = folium.Map(
            location=[center_latitude, center_longitude],
            zoom_start=11,
            tiles="OpenStreetMap",
        )

        # Ajout des récepteurs sur la carte.
        for receptor, noise_level in zip(receptor_grid, noise_levels):
            latitude = receptor[0]
            longitude = receptor[1]

            # Choix de la couleur selon le niveau sonore.
            # Ces seuils sont cohérents avec les cartes de bruit Lden :
            # vert  : bruit faible
            # orange: bruit modéré
            # rouge : bruit élevé
            if noise_level < 55:
                color = "green"
            elif noise_level < 65:
                color = "orange"
            else:
                color = "red"

            # Création d'un marqueur circulaire.
            # radius contrôle la taille du point affiché.
            # popup affiche le niveau de bruit lorsqu'on clique sur le point.
            folium.CircleMarker(
                location=[latitude, longitude],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.7,
                popup=f"Lden : {noise_level:.2f} dB(A)",
            ).add_to(noise_map)

        # Sauvegarde de la carte dans un fichier HTML.
        noise_map.save(output_path)

        # Retourne le chemin du fichier sous forme de texte.
        return str(output_path)

    def export_animation_gif(self, frames, output_path=None, fps=2):
        """
        Exporte une animation GIF à partir d'une liste d'images.

        Cette méthode reçoit une liste d'images représentant l'évolution du
        bruit dans le temps. Chaque image correspond à un instant ou à une
        période, par exemple une heure de la journée. Les images sont ensuite
        assemblées dans un fichier GIF animé.

        :param frames: Liste d'images à assembler dans l'animation.
        :type frames: list
        :param output_path: Chemin optionnel du fichier GIF à créer. Si aucune
            valeur n'est fournie, le fichier est créé dans le dossier de sortie.
        :type output_path: str or None
        :param fps: Nombre d'images par seconde dans le GIF.
        :type fps: int
        :return: Chemin du fichier GIF généré.
        :rtype: str
        :raises ValueError: Si la liste d'images est vide.
        :raises ValueError: Si fps est inférieur ou égal à zéro.
        """

        # Vérifie que la liste contient au moins une image.
        if len(frames) == 0:
            raise ValueError("La liste des images ne peut pas être vide.")

        # Vérifie que la vitesse d'animation est valide.
        if fps <= 0:
            raise ValueError("Le nombre d'images par seconde doit être positif.")

        # Si aucun chemin n'est fourni, on crée un nom de fichier par défaut.
        if output_path is None:
            output_path = self.output_dir / "noise_animation.gif"
        else:
            output_path = Path(output_path)

        # Crée le dossier parent si nécessaire.
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Calcule la durée d'affichage de chaque image.
        duration = 1 / fps

        # Crée le fichier GIF animé à partir des images fournies.
        imageio.mimsave(output_path, frames, duration=duration)

        # Retourne le chemin du fichier sous forme de texte.
        return str(output_path)

    def __str__(self):
        """
        Retourne une représentation lisible de l'objet ResultsExporter.

        Cette méthode facilite le débogage lorsque l'objet est affiché avec
        print().

        :return: Description textuelle de l'objet.
        :rtype: str
        """

        return f"ResultsExporter(output_dir='{self.output_dir}')"