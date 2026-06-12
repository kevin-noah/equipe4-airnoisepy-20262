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
    pass  # TODO


# ---------------------------------------------------------------------------
# Bruit instantané (onglet live)
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    """Distance grand cercle en mètres."""
    pass  # TODO


def _normaliser_avion(a):
    """
    Sortie de OpenSkyFetcher.fetch_realtime() → clés courtes utilisées
    par l'app : icao24, callsign, lat, lon, alt_baro, on_ground,
    vertical_rate (m/s — sert à estimer la phase de vol).
    """
    pass  # TODO


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
    # TODO : SEL calculé vs mesure capteur ADM (WebTrak), verdict
    #        PASS/FAIL ±3 dB (ResultsExporter.validate_webtrak si dispo)
    st.info('À coder : validation modèle vs sonomètres ADM')

with tab_export:
    # TODO : boutons de téléchargement CSV / carte HTML via ResultsExporter
    #        (replis si le module n'est pas encore livré)
    st.info('À coder : exports CSV et carte HTML')

# TODO pied de page : licence MIT, citation, logos locaux (assets/ à la
#      racine — hors-ligne, règle n°1 de la démo)
