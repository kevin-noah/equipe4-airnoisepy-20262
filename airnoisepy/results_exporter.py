# Responsable : Laura
# Classe ResultsExporter — carte folium HTML, animation 24h MP4/GIF, export CSV
"""
Module d'exportation des résultats pour AirNoisePy.

Ce module contient la classe ResultsExporter. Cette classe est responsable
de sauvegarder les résultats produits par le programme sous différents formats :
CSV, carte HTML, animation et rapport de validation.
"""

from pathlib import Path


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

    def __str__(self):
        """
        Retourne une représentation lisible de l'objet ResultsExporter.

        Cette méthode facilite le débogage lorsque l'objet est affiché avec
        print().

        :return: Description textuelle de l'objet.
        :rtype: str
        """

        return f"ResultsExporter(output_dir='{self.output_dir}')"