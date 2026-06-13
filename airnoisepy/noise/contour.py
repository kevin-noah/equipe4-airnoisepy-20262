"""
airnoisepy.noise.contour : Génération des contours isophoniques Lden sur carte géographique.
Responsable : Syndia Jean
Référence :
- ECAC Doc 29, Vol. 1 — contours de bruit aérien
- Directive européenne 2002/49/CE — seuils réglementaires Lden
- Transport Canada — cartes de bruit YUL (ADM)
"""
import numpy as np
from matplotlib import pyplot as plt
from scipy.interpolate import griddata

#Import conditionnelle de contextily
try:
    import contextily as ctx
    CONTEXTILY_AVAILABLE = True
except ImportError:
    CONTEXTILY_AVAILABLE = False

# Importation conditionnelle de folium
try:
    import folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False

#Données

#Centre de l'aéroport YUL

YUL_LATITUDE = 45.4706
YUL_LONGITUDE = -73.7408

#Seuil réglementaire Lden en dB

CONTOUR_LEVELS = [55, 60, 65, 70]

#Code couleur pour les cartes de bruits

CONTOUR_COLORS = {
    55: "#FFFF00", # Jaune
    60: "#FFA500", # Orange
    65: "#FF0000", # Rouge
    70: "#8B008B", # Violet foncé
}

#Labels pour la légende

CONTOUR_LABELS = {
    55: "55 dB - Zone d'information",
    60: "60 dB - Gêne modérée",
    65: "65 dB - Isolation obligatoire",
    70: "70 dB - Forte contrainte",
}

#Conversion degrés en km
KM_PAR_DEGRE_LATITUDE = 111.0
KM_PAR_DEGRE_LONGITUDE = 78.0


#Classe principale

class NoiseContour:
    """
    Transforme les niveaux Lden calculés par NoiseCalculator en carte visuelle
    avec contours isophoniques.

    NoiseCalculator.compute_grid() produit un tableau de valeurs Lden
    (une par point de la grille de récepteurs). NoiseContour transforme ce
    tableau en carte lisible : lignes de niveau à 55, 60, 65, 70 dB.

    La forme attendue est celle d'un « os » aligné sur les pistes :
    deux lobes elliptiques dans les axes de décollage/atterrissage,
    correspondant aux cartes officielles publiées par ADM.

    Paramètres:
    - calculator : NoiseCalculator (Instance du calculateur de bruit)
    - center_latitude : float (Latitude du centre de l'aéroport - valeur défaut : 45.4706 — YUL)
    - center_longitude : float (Longitude du centre de l'aéroport - valeur défaut : -73.7408)
    - radius_km  : float (Rayon de la zone d'étude en km défaut : 25 km)
    - grid_size  : int (Résolution de la grille. grid_size=400 → 400×400 = 160 000 récepteurs)

    Attributs publics:
    - calculator     : NoiseCalculator
    - center         : tuple — (lat, lon) du centre YUL
    - radius_km      : float
    - grid_size      : int
    - receptor_grid  : np.ndarray shape (N, 2) — tous les (lat, lon) de la grille

    Exemple:
    - from airnoisepy.noise.contour import NoiseContour
    - nc = NoiseContour(calculator=calc, grid_size=400)
    - lden_values = nc.compute_lden_grid(flights, date)
    - nc.plot(lden_values, title='Contours Lden YUL — 31 mai 2026', save_path='results/contours_yul.png')
    """

    def __init__(self, calculator, center_latitude=YUL_LATITUDE, center_longitude=YUL_LONGITUDE, radius_km=25.0, grid_size=400):
        self.calculator = calculator
        self.center = (center_latitude, center_longitude)
        self.radius_km = radius_km
        self.grid_size = grid_size
        self.receptor_grid = self._build_grid()

#Méthodes publiques

    def get_receptor_grid(self):
        """
        Retourne la grille de récepteurs au format attendu par NoiseCalculator.

        Retourne:
        - np.ndarray shape (N, 2)
            Tableau [[lat1, lon1], [lat2, lon2], ...] de tous les récepteurs.
            Compatible directement avec NoiseCalculator.compute_grid()

        Exemple:
        - grid   = nc.get_receptor_grid()
        - lden   = calc.compute_grid(flights, grid)   # NoiseCalculator
        - nc.plot(lden)
        """

        return self.receptor_grid

    def compute_lden_grid(self, flights, date, aircraft_type="A320"):
        """
        Calcule le Lden pour tous les récepteurs de la grille.

        Encapsule l'appel à NoiseCalculator.compute_grid() avec la grille
        interne, pour simplifier l'usage depuis le notebook ou Streamlit.

        Paramètres:
        - flights       : list[FlightOperation] (Liste des vols de la journée — format FlightOperation)
        - date          : datetime.date (Jour à analyser pour la pondération jour/soir/nuit Lden)
        - aircraft_type : str (Code OACI du type d'avion - avion par défaut : 'A320')

        Retourne
        np.ndarray shape (N,)
            Niveau Lden en dB(A) pour chaque récepteur de la grille.

        Exemple:
        - import datetime
        - date  = datetime.date(2026, 5, 31)
        - lden  = nc.compute_lden_grid(flights, date)
        - nc.plot(lden, title='Lden YUL 31 mai 2026')
        """

        return self.calculator.compute_grid(flights, self.receptor_grid, aircraft_type)

    def compute_lden_recepteur(self, flights, recepteur, date, aircraft_type="A320"):
        """
        Calcule le Lden pour un seul récepteur ponctuel.

        Encapsule l'appel à NoiseCalculator.compute_lden() pour un usage
        simple (ex: vérification sur un point de validation ADM).

        Paramètres:
        - flights       : list[FlightOperation]
        - recepteur     : tuple (lat, lon) — coordonnées du récepteur au sol
        - date          : datetime.date
        - aircraft_type : str

        Retourne:
        - float — Lden en dB(A)

        Exemple:
        - recepteur_adm = (45.4706, -73.7408)
        - lden = nc.compute_lden_recepteur(flights, recepteur_adm, date)
        - print(f"Lden au centre YUL : {lden:.1f} dB")
        """

        return self.calculator.compute_lden(flights, recepteur, date, aircraft_type)

    def plot(self, lden_values, title="Contours Lden YUL", basemap=True, save_path=None):
        """
        Trace la carte de bruit avec contours isophoniques sur fond de carte.

        Paramètres:
        - lden_values : np.ndarray shape (N,)
            Niveaux Lden pour chaque récepteur (sortie de compute_lden_grid()).
        - title : str
            Titre de la figure.
        - basemap : bool
            Si True et contextily disponible, ajoute un fond de carte OSM.
        - save_path : str ou None
            Si fourni, sauvegarde la figure en PNG à ce chemin.

        Retourne:
        - tuple (fig, ax) — figure matplotlib

        Exemple
       - fig, ax = nc.plot(lden_values, title='Lden YUL 31 mai 2026', save_path='results/lden_yul.png')
        """

        z_grid, latitude_lin, longitude_lin = self._interpoler_surface(lden_values)
        fig, ax = plt.subplots(figsize=(10, 10))

        for level in reversed(CONTOUR_LEVELS):
            upper = level + 5 if level < max(CONTOUR_LEVELS) else float(np.nanmax(lden_values)) + 1
            cs = ax.contourf(longitude_lin, latitude_lin, z_grid, levels=[level, upper], colors=[CONTOUR_COLORS[level]], alpha=0.6)
        if basemap and CONTEXTILY_AVAILABLE:
            try:
                ctx.add_basemap(ax, crs="EPSG:4326", source="https://tile.openstreetmap.org/{z}/{x}/{y}.png", zoom=11)
            except Exception as e:
                print(f"[NoiseContour] Fond de carte non disponible : {e}")

        center_latitude, center_longitude = self.center
        ax.plot(center_longitude, center_latitude, "k^", markersize=10, label="YUL - Montréal - Trudeau", zorder=5)

        legend_patches = [plt.Rectangle((0,0),1, 1, fc=CONTOUR_COLORS[lvl], alpha=0.6, label=CONTOUR_LABELS[lvl]) for lvl in CONTOUR_LEVELS]
        ax.legend(handles=legend_patches, loc="lower left", fontsize=9, framealpha=0.85)

        ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        ax.set_xlim(center_longitude - self.radius_km / KM_PAR_DEGRE_LONGITUDE,
                    center_longitude + self.radius_km / KM_PAR_DEGRE_LONGITUDE)
        ax.set_ylim(center_latitude - self.radius_km / KM_PAR_DEGRE_LATITUDE,
                    center_latitude + self.radius_km / KM_PAR_DEGRE_LATITUDE)
        ax.set_aspect("equal")
        ax.grid(True, linestyle="--", alpha=0.3)
        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            print(f"[NoiseContour] Carte sauvegardée : {save_path}")

        plt.show()
        return fig, ax


#Méthodes privées

    def _build_grid(self):
        """
        Génère la grille circulaire de récepteurs autour de YUL.

        Retourne:
        np.ndarray shape (N, 2)
            Tableau [[lat, lon], ...] au format attendu par
            NoiseCalculator.compute_grid(flights, receptor_grid).
        """

        center_latitude, center_longitude = self.center

        delta_latitude = self.radius_km / KM_PAR_DEGRE_LATITUDE
        delta_longitude = self.radius_km / KM_PAR_DEGRE_LONGITUDE

        latitudes = np.linspace(center_latitude - delta_latitude, center_latitude + delta_latitude, self.grid_size)
        longitudes = np.linspace(center_longitude - delta_longitude, center_longitude + delta_longitude, self.grid_size)

        latitudes_grid, longitudes_grid = np.meshgrid(latitudes, longitudes)
        latitudes_flat = latitudes_grid.ravel()
        longitudes_flat = longitudes_grid.ravel()

        distance_km = np.sqrt(((latitudes_flat - center_latitude) * KM_PAR_DEGRE_LATITUDE) ** 2 +
                              ((longitudes_flat - center_longitude) * KM_PAR_DEGRE_LONGITUDE) ** 2)
        masque = distance_km <= self.radius_km

        return np.column_stack((latitudes_flat[masque], longitudes_flat[masque]))

    def _interpoler_surface(self, lden_values):
        """
        Interpole les niveaux Lden discrets sur une grille régulière continue.

        Paramètres
        - lden_values : np.ndarray shape (N,)

        Retourne
        - z_grid  : np.ndarray shape (grid_size, grid_size) — Lden interpolés
        - latitude_lin : np.ndarray shape (grid_size,) — latitudes de la grille
        - longitude_lin : np.ndarray shape (grid_size,) — longitudes de la grille
        """

        center_latitude, center_longitude = self.center
        delta_latitude = self.radius_km / KM_PAR_DEGRE_LATITUDE
        delta_longitude = self.radius_km / KM_PAR_DEGRE_LONGITUDE

        latitude_lin = np.linspace(center_latitude - delta_latitude,
                              center_latitude + delta_latitude, self.grid_size)
        longitude_lin = np.linspace(center_longitude - delta_longitude,
                              center_longitude + delta_longitude, self.grid_size)

        longitude_mesh, latitude_mesh = np.meshgrid(longitude_lin, latitude_lin)

        latitudes = self.receptor_grid[:, 0]
        longitudes = self.receptor_grid[:, 1]

        valeur_min = float(np.nanmin(lden_values)) if len(lden_values) > 0 else 30.0

        z_grid = griddata(
            points=(longitudes, latitudes),
            values=lden_values,
            xi=(longitude_mesh, latitude_mesh),
            method="linear",
            fill_value=valeur_min
        )

        return z_grid, latitude_lin, longitude_lin