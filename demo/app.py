"""
AirNoisePy — démo Streamlit pour la présentation orale (MGA802, Équipe 4).

Couche de présentation AU-DESSUS de la bibliothèque : ce fichier appelle les
classes du package airnoisepy sans en modifier aucune. Les modules pas encore
livrés (NoiseContour, ResultsExporter) seront détectés à l'import : l'app
doit fonctionner quand même, avec un affichage de repli.

Lancement (depuis la racine du dépôt) :
    pip install streamlit streamlit-folium
    streamlit run demo/app.py

Fiabilité démo : tout doit fonctionner HORS-LIGNE avec les données locales
(data/sample_track.json + base EASA ANP v9). Le mode « live OpenSky »
est un bouton optionnel — la démo ne dépend jamais du wifi de la salle.
"""

import os
import sys

import streamlit as st
import pandas as pd
import numpy as np
import math
import folium
from streamlit_folium import st_folium

# app.py vit dans demo/ : streamlit run ajoute demo/ au sys.path, pas la
# racine du dépôt — on l'ajoute pour importer airnoisepy sans pip install .
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

# TODO imports à ajouter au fur et à mesure : datetime, json, math,
#      folium, numpy, st_folium (streamlit_folium), ANPDatabase,
#      NoiseCalculator, OpenSkyFetcher (+ NoiseContour / ResultsExporter
#      en try/except tant qu'ils ne sont pas sur main)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(RACINE, 'data')
NPD_XLSX = os.path.join(DATA_DIR, 'anp', 'EASA_ANP_database_NPD_Data_v9.xlsx')
TRACK_JSON = os.path.join(DATA_DIR, 'sample_track.json')
FLIGHTS_JSON = os.path.join(DATA_DIR, 'sample_flights.json')

YUL = (45.4706, -73.7408)
RAYON_GRILLE_KM = 25.0

# TODO constantes à définir ensemble :
#   - LAMAX_OFFSET_DB : passage SEL → LAmax estimé (la base ne charge que SEL)
#   - poussée par phase de vol (lbs, table NPD A320 — voir database/anp.py)
#   - PROFIL_HORAIRE_YUL : mouvements par heure (~565/jour, pointes 7h-9h
#     et 17h-19h, creux nocturne — statistiques ADM ~240 000 mouvements/an)

st.set_page_config(page_title='AirNoisePy — bruit aérien YUL',
                   page_icon='✈️', layout='wide')


# ---------------------------------------------------------------------------
# Chargement de la bibliothèque (mis en cache par Streamlit)
# ---------------------------------------------------------------------------

@st.cache_resource
def charger_bibliotheque():
    """ANPDatabase (réelle si dispo, sinon synthétique) + NoiseCalculator."""
    pass  # TODO


@st.cache_resource
def charger_vols():
    """
    Construit une journée type de ~565 vols suivant le profil horaire
    réel de YUL (PROFIL_HORAIRE_YUL).

    OpenSky historique ne nous a fourni qu'une trajectoire complète (ACA750,
    vol ENTIER CYUL→KBOS). Chaque mouvement de la journée réutilise sa
    géométrie — inversée pour les arrivées — avec les identités des 12 vols
    sample en rotation.

    IMPORTANT : on passe par OpenSkyFetcher.to_flight_operation() (pipeline
    de nettoyage complet), jamais FlightOperation.from_opensky() sur un track
    brut. Sans le filtre zone 25 km, un vol complet commence ET finit au sol
    → classification départ/arrivée faussée.
    """
    pass  # TODO


def grille_recepteurs(grid_size):
    """
    Grille (N, 2) de récepteurs [lat, lon] dans un carré de ±25 km
    autour de YUL — repli tant que NoiseContour n'est pas livré.
    """
    pass  # TODO


@st.cache_data
def calculer_grille(curfew_actif, grid_size):
    """
    Lden sur la grille YUL, avec ou sans couvre-feu 23h–7h.
    Mis en cache : le calcul n'est fait qu'une fois par scénario.
    """
    # ------------------------------------------------------------------
    # Version de démonstration hors-ligne.
    #
    # L'objectif est de produire une grille de niveaux Lden plausible
    # pour tester l'interface Streamlit, même si tous les modules de
    # calcul ne sont pas encore intégrés.
    #
    # Hypothèse simplifiée :
    #   - le bruit est plus élevé près de YUL ;
    #   - il diminue progressivement avec la distance ;
    #   - un couvre-feu 23h–7h réduit le niveau global.
    # ------------------------------------------------------------------

    grid = grille_recepteurs(grid_size)

    niveaux = []

    for lat, lon in grid:
        distance_km = _haversine_m(YUL[0], YUL[1], lat, lon) / 1000

        # Niveau simplifié : fort près de l'aéroport, plus faible loin.
        lden = max(35, 70 - 1.15 * distance_km)

        # Scénario de couvre-feu :
        # on applique une réduction simplifiée de 4 dB pour illustrer
        # l'effet d'une diminution des vols de nuit.
        if curfew_actif:
            lden -= 4

        niveaux.append(lden)

    return np.array(niveaux), grid


# ---------------------------------------------------------------------------
# Bruit instantané (onglet live)
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    """
    Calcule la distance orthodromique (grand cercle) entre deux points
    géographiques exprimés en latitude/longitude.

    Paramètres
    ----------
    lat1, lon1 : float
        Coordonnées du premier point en degrés décimaux.

    lat2, lon2 : float
        Coordonnées du second point en degrés décimaux.

    Retour
    -------
    float
        Distance entre les deux points en mètres.

    Notes
    -----
    La formule de Haversine tient compte de la courbure de la Terre.
    Elle est suffisamment précise pour les besoins de cette démonstration
    autour de YUL (rayon d'étude de 25 km).
    """

    # ------------------------------------------------------------------
    # Rayon moyen de la Terre (en mètres).
    # ------------------------------------------------------------------

    rayon_terre_m = 6_371_000

    # ------------------------------------------------------------------
    # Conversion des coordonnées de degrés vers radians.
    #
    # Les fonctions trigonométriques de Python utilisent les radians.
    # ------------------------------------------------------------------

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # ------------------------------------------------------------------
    # Formule de Haversine.
    #
    # a représente le carré de la moitié de la corde reliant les deux
    # points à travers la sphère terrestre.
    # ------------------------------------------------------------------

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(delta_lambda / 2) ** 2
    )

    # ------------------------------------------------------------------
    # Distance angulaire convertie en distance réelle.
    # ------------------------------------------------------------------

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return rayon_terre_m * c


def _normaliser_avion(a):
    """
    Normalise la sortie de OpenSkyFetcher.fetch_realtime() afin de fournir
    une structure homogène au reste de l'application Streamlit.

    OpenSky peut renvoyer des clés absentes ou des valeurs nulles.
    Cette fonction applique donc des valeurs par défaut afin d'éviter
    les erreurs dans les traitements ultérieurs.

    Retour :
        {
            "icao24": str,
            "callsign": str,
            "lat": float | None,
            "lon": float | None,
            "alt_baro": float,
            "on_ground": bool,
            "vertical_rate": float,
        }
    """

    # ------------------------------------------------------------------
    # Protection contre les entrées invalides.
    # Si l'objet reçu n'est pas un dictionnaire, on retourne une structure
    # vide mais cohérente.
    # ------------------------------------------------------------------

    if not isinstance(a, dict):
        return {
            "icao24": "",
            "callsign": "Inconnu",
            "lat": None,
            "lon": None,
            "alt_baro": 0.0,
            "on_ground": False,
            "vertical_rate": 0.0,
        }

    # ------------------------------------------------------------------
    # Nettoyage et harmonisation des données OpenSky.
    #
    # Les chaînes de caractères sont débarrassées des espaces inutiles.
    # Les valeurs numériques manquantes sont remplacées par des valeurs
    # neutres afin d'assurer la stabilité de l'application.
    # ------------------------------------------------------------------

    return {
        "icao24": str(a.get("icao24", "")).strip(),

        "callsign": (
            str(a.get("callsign", "Inconnu")).strip()
            or "Inconnu"
        ),

        "lat": a.get("lat"),

        "lon": a.get("lon"),

        "alt_baro": float(a.get("alt_baro") or 0.0),

        "on_ground": bool(a.get("on_ground", False)),

        "vertical_rate": float(a.get("vertical_rate") or 0.0),
    }


def niveau_instantane(avions, recepteur, anp):
    """
    Niveau sonore instantané estimé (dB(A)) à un point au sol, à partir
    des avions actuellement en vol.

    Pour chaque avion : phase estimée via le taux de montée/descente →
    poussée → courbe SEL de la base NPD à la distance oblique 3D,
    ramenée à un ordre de grandeur LAmax (− LAMAX_OFFSET_DB).
    Les contributions sont sommées énergétiquement (addition logarithmique).

    Retourne : (niveau_total, contributions) où contributions est une liste
    de dicts {callsign, distance_m, niveau_db} triée du plus bruyant au
    plus discret. niveau_total = 0.0 si aucun avion en vol.
    """
    pass  # TODO


def comparaison_parlante(lden):
    """Équivalent du quotidien pour un niveau Lden donné."""
    pass  # TODO


# ---------------------------------------------------------------------------
# Cartes folium
# ---------------------------------------------------------------------------

def carte_contours(contours, center=YUL, zoom=10):
    """Carte folium avec les polygones isophoniques (NoiseContour requis)."""
    pass  # TODO


def carte_heatmap(lden, grid, grid_size, center=YUL, zoom=10):
    """
    Repli sans NoiseContour : surface Lden en surimpression semi-
    transparente (colormap inferno, transparent sous 40 dB).
    """
    pass  # TODO


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

st.title('✈️ AirNoisePy — le bruit des avions autour de YUL')
st.caption('Modélisation ECAC Doc 29 · données ADS-B OpenSky · base EASA '
           'ANP v9 — MGA802 ÉTS Été 2026, Équipe 4')

# TODO sidebar : résolution de grille (40/60/80) + toggle couvre-feu 23h–7h
#      + rappel des seuils réglementaires (55 dB information, 65 dB isolation)

tab_chez_vous, tab_anim, tab_live, tab_valid, tab_export = st.tabs([
    '🏠 Le bruit chez vous', '🕐 Journée 24h', '📡 Avions en direct',
    '✅ Validation WebTrak', '💾 Exports',
])

with tab_chez_vous:
    # TODO : carte cliquable (st_folium) → Lden au point cliqué,
    #        comparaison parlante, alerte selon les seuils 55/65 dB,
    #        SEL du survol le plus bruyant de la journée
    st.info('À coder : carte cliquable + Lden au point choisi')

with tab_anim:
    # TODO : slider 0-23h → bruit accumulé heure par heure (imshow
    #        matplotlib), pointes du matin et du soir visibles
    st.info('À coder : animation de la journée 24h')

with tab_live:
    # TODO : bouton OpenSky fetch_realtime → carte des avions en vol
    #        (monte/descend/palier via vertical_rate), clic → niveau
    #        instantané + comparaison WebTrak ±3 dB
    st.info('À coder : avions en direct + niveau instantané')

with tab_valid:
    st.subheader("✅ Validation WebTrak / ADM")

    st.markdown(
        """
        Cette section permet de comparer les résultats calculés par AirNoisePy
        avec des mesures réelles provenant des sonomètres ADM/WebTrak.

        Selon les recommandations ECAC Doc 29, un écart inférieur ou égal à
        ±3 dB est généralement considéré comme acceptable.
        """
    )

    niveau_calcule = st.number_input(
        "Niveau sonore calculé par AirNoisePy (dB)",
        value=60.0,
        step=0.5,
    )

    niveau_mesure = st.number_input(
        "Niveau mesuré par WebTrak / ADM (dB)",
        value=61.5,
        step=0.5,
    )

    ecart = abs(niveau_calcule - niveau_mesure)

    st.metric("Écart modèle / mesure", f"{ecart:.1f} dB")

    if ecart <= 3:
        st.success(
            "PASS : l'écart respecte la tolérance ECAC Doc 29 (±3 dB)."
        )
    else:
        st.error(
            "FAIL : l'écart dépasse la tolérance ECAC Doc 29 (±3 dB)."
        )

    st.caption(
        "Cette validation simplifiée illustre le principe utilisé pour "
        "évaluer la fidélité du modèle."
    )

with tab_export:
    st.subheader("💾 Export des résultats")

    st.markdown(
        """
        Cette section illustre comment AirNoisePy permet de partager
        les résultats obtenus après les calculs.

        Dans la version finale, cette fonctionnalité utilisera la classe
        ResultsExporter pour produire automatiquement les exports
        complets du projet.

        En attendant l'intégration finale, nous utilisons un petit jeu
        de données représentatif afin de démontrer le principe.
        """
    )

    # ------------------------------------------------------------------
    # Afin d'éviter que l'onglet Exports ne génère automatiquement
    # des fichiers au chargement de l'application, nous demandons
    # explicitement à l'utilisateur de lancer la démonstration.
    #
    # Cette approche améliore également la robustesse de l'application :
    # chaque onglet reste indépendant des autres.
    # ------------------------------------------------------------------

    if st.button("Générer les exports de démonstration"):

        # --------------------------------------------------------------
        # Jeu de données simplifié utilisé uniquement à des fins
        # de démonstration Streamlit.
        #
        # Ces valeurs représentent trois vols fictifs présentant
        # différents niveaux d'exposition sonore.
        # --------------------------------------------------------------

        donnees_demo = pd.DataFrame(
            {
                "callsign": ["ACA750", "ACA751", "ACA752"],
                "lden_db": [54.8, 61.2, 66.4],
                "zone": [
                    "Inférieure à 55 dB",
                    "55–65 dB",
                    "≥ 65 dB",
                ],
            }
        )

        st.success("Export de démonstration généré avec succès.")

        st.dataframe(donnees_demo)

        # --------------------------------------------------------------
        # Conversion du tableau en CSV.
        #
        # L'encodage UTF-8 garantit la compatibilité avec Excel,
        # LibreOffice et les autres outils d'analyse.
        # --------------------------------------------------------------

        csv = donnees_demo.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="📥 Télécharger le fichier CSV",
            data=csv,
            file_name="airnoisepy_demo.csv",
            mime="text/csv",
        )

    else:
        st.info(
            "Cliquez sur le bouton ci-dessus pour générer "
            "un exemple d'export CSV."
        )

# TODO pied de page : licence MIT, citation, logos locaux (assets/ à la
#      racine — hors-ligne, règle n°1 de la démo)
