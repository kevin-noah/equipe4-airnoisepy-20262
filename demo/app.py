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

# ---------------------------------------------------------------------------
# Bibliothèques standard Python
# ---------------------------------------------------------------------------

import os
import sys
import math
import json
import inspect
import datetime

# ---------------------------------------------------------------------------
# Bibliothèques tierces utilisées par la démo Streamlit
# ---------------------------------------------------------------------------

import numpy as np
import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium

# ---------------------------------------------------------------------------
# app.py vit dans demo/ : streamlit run ajoute demo/ au sys.path, pas la
# racine du dépôt. On ajoute donc explicitement la racine afin de pouvoir
# importer airnoisepy sans avoir à faire pip install .
# ---------------------------------------------------------------------------

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

# ---------------------------------------------------------------------------
# Imports de la bibliothèque AirNoisePy
#
# La démo Streamlit est une couche de présentation au-dessus du package.
# Certains modules peuvent encore être en intégration sur les branches des
# autres membres. Pour éviter que l'application complète plante à cause
# d'un seul module manquant, on protège ces imports avec try/except.
# ---------------------------------------------------------------------------

try:
    from airnoisepy import ANPDatabase, NoiseCalculator, OpenSkyFetcher
except (ImportError, AttributeError):
    ANPDatabase = None
    NoiseCalculator = None
    OpenSkyFetcher = None

try:
    from airnoisepy import NoiseContour
except (ImportError, AttributeError):
    NoiseContour = None

try:
    from airnoisepy import ResultsExporter
except (ImportError, AttributeError):
    ResultsExporter = None

# Modules optionnels : si une coéquipière n'a pas encore livré le sien, la
# démo bascule sur un affichage de repli au lieu de planter.
CONTOUR_DISPONIBLE = NoiseContour is not None
EXPORTER_DISPONIBLE = ResultsExporter is not None
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(RACINE, 'data')
NPD_XLSX = os.path.join(DATA_DIR, 'anp', 'EASA_ANP_database_NPD_Data_v9.xlsx')
TRACK_JSON = os.path.join(DATA_DIR, 'sample_track.json')
FLIGHTS_JSON = os.path.join(DATA_DIR, 'sample_flights.json')

YUL = (45.4706, -73.7408)
RAYON_GRILLE_KM = 25.0

# La base ANP ne charge que la métrique SEL (choix ECAC Doc 29 d'ANPDatabase).
# Pour un survol de jet commercial, LAmax ≈ SEL − 10·log10(durée effective),
# durée typique ~8 s → écart ≈ 9 dB. Estimation, pas une mesure.
LAMAX_OFFSET_DB = 9.0

# Convention de poussée d'ANPDatabase.interpolate : l'ANPDatabase de Bouchra
# (main) attend des LIVRES nettes (paramètre `thrust`), le prototype local_all
# attendait une fraction N1 (paramètre `thrust_pct`). On détecte l'unité via
# le nom du paramètre pour rester compatible avec les deux.
if ANPDatabase is not None:
    THRUST_EN_LBS = ('thrust_pct'
                     not in inspect.signature(ANPDatabase.interpolate).parameters)
else:
    THRUST_EN_LBS = True

# Poussée par phase de vol : (fraction N1, livres nettes) — table NPD A320
# (CFM56-5B), correspondances documentées dans airnoisepy/database/anp.py
_PHASES_POUSSEE = {
    'decollage': (0.94, 23000.0),
    'montee':    (0.86, 18000.0),
    'palier':    (0.80, 13000.0),
    'approche':  (0.68, 4500.0),
}


def _poussee(phase):
    """Poussée de la phase dans l'unité attendue par ANPDatabase.interpolate."""
    n1, lbs = _PHASES_POUSSEE[phase]
    return lbs if THRUST_EN_LBS else n1


# Profil horaire typique de YUL : nombre de mouvements (départs + arrivées)
# par heure, calibré sur ~565 mouvements/jour (statistiques ADM ~240 000
# mouvements/an). Pointes du matin (7h-9h) et du soir (17h-19h), creux
# nocturne avec quelques vols cargo.
PROFIL_HORAIRE_YUL = {
    0: 3,  1: 2,  2: 1,  3: 1,  4: 2,  5: 6,
    6: 18, 7: 35, 8: 40, 9: 38, 10: 30, 11: 28,
    12: 30, 13: 30, 14: 32, 15: 34, 16: 38, 17: 42,
    18: 44, 19: 38, 20: 30, 21: 22, 22: 14, 23: 8,
}

st.set_page_config(page_title='AirNoisePy — bruit aérien YUL',
                   page_icon='✈️', layout='wide')


# ---------------------------------------------------------------------------
# Chargement de la bibliothèque (mis en cache par Streamlit)
# ---------------------------------------------------------------------------

@st.cache_resource
def charger_bibliotheque():
    """ANPDatabase (réelle si le fichier NPD est là, sinon table synthétique
    de secours) + NoiseCalculator prêt à l'emploi."""
    if os.path.exists(NPD_XLSX):
        anp = ANPDatabase(NPD_XLSX)
    else:
        anp = ANPDatabase()  # table synthétique : la démo marche quand même
    return anp, NoiseCalculator(anp)


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
    → classification départ/arrivée faussée, et 115 segments au lieu de ~30.
    """
    fetcher = OpenSkyFetcher()  # hors-ligne : seul le pipeline de nettoyage sert
    # 'to_flight_operation' chez Syndia (main), pluriel sur le prototype local_all
    convertir = getattr(fetcher, 'to_flight_operation',
                        getattr(fetcher, 'to_flight_operations', None))

    with open(TRACK_JSON) as f:
        track = json.load(f)
    with open(FLIGHTS_JSON) as f:
        flights_meta = json.load(f)

    base_path = track['path']
    t0 = base_path[0][0]
    # arrivée = même géométrie que le départ, mais parcourue à l'envers
    path_arrivee = [
        [p[0], q[1], q[2], q[3], q[4], q[5]]
        for p, q in zip(base_path, reversed(base_path))
    ]

    vols = []
    compteur = 0
    for hour, n_mouvements in PROFIL_HORAIRE_YUL.items():
        for k in range(n_mouvements):
            meta = flights_meta[compteur % len(flights_meta)]
            is_departure = compteur % 2 == 0
            chemin = base_path if is_departure else path_arrivee
            # timestamps répartis dans l'heure, cadence d'origine conservée
            depart = datetime.datetime(
                2026, 6, 10, hour, 0, tzinfo=datetime.timezone.utc
            ).timestamp() + k * 3600 // max(n_mouvements, 1)
            shift = int(depart) - t0
            chemin = [[p[0] + shift] + p[1:] for p in chemin]
            vols.append(convertir(meta['icao24'], {
                'icao24':   meta['icao24'],
                'callsign': (meta.get('callsign') or '').strip(),
                'path':     chemin,
            }))
            compteur += 1
    return vols


def grille_recepteurs(grid_size):
    """
    Grille (N, 2) de récepteurs [lat, lon] dans un carré de ±25 km
    autour de YUL — repli utilisé tant que NoiseContour n'est pas livré
    (sinon on prend la grille interne de NoiseContour).
    """

    # ------------------------------------------------------------------
    # Conversion du rayon (km) en degrés.
    # 1° de latitude ≈ 111.32 km partout ; 1° de longitude se resserre
    # vers les pôles, d'où le facteur cos(latitude).
    # ------------------------------------------------------------------
    dlat = RAYON_GRILLE_KM / 111.32
    dlon = RAYON_GRILLE_KM / (111.32 * math.cos(math.radians(YUL[0])))

    # Axes régulièrement espacés, puis produit cartésien (grid_size²) points.
    lats = np.linspace(YUL[0] - dlat, YUL[0] + dlat, grid_size)
    lons = np.linspace(YUL[1] - dlon, YUL[1] + dlon, grid_size)
    return np.column_stack([np.repeat(lats, grid_size),
                            np.tile(lons, grid_size)])


@st.cache_data
def calculer_grille(curfew_actif, grid_size):
    """
    Lden réel sur la grille YUL, avec ou sans couvre-feu 23h–7h.
    Mis en cache : le calcul n'est fait qu'une fois par scénario.

    Retourne (grid, lden, n_vols) : la grille (N, 2) des récepteurs, le
    tableau Lden (N,) en dB(A), et le nombre de vols pris en compte.
    """
    # ------------------------------------------------------------------
    # Vrai calcul ECAC Doc 29.
    #
    # On part de la journée type (~565 vols) et on agrège le bruit de
    # chaque survol sur tous les récepteurs au sol via NoiseCalculator.
    # Le résultat dépend donc réellement du trafic, plus d'une formule
    # de distance simplifiée.
    # ------------------------------------------------------------------

    _, calc = charger_bibliotheque()
    vols = charger_vols()

    # Scénario de couvre-feu : au lieu d'un abattement forfaitaire, on
    # RETIRE vraiment les vols dont le décollage tombe entre 23h et 7h.
    # L'effet sur le Lden émerge alors du calcul, pas d'une constante.
    if curfew_actif:
        vols = [v for v in vols
                if not (calc._utc_hour(v.waypoints[0]['time']) >= 23
                        or calc._utc_hour(v.waypoints[0]['time']) < 7)]

    # Grille de récepteurs : celle de NoiseContour si le module est livré
    # (forme « os » alignée sur les pistes), sinon le repli carré local.
    if CONTOUR_DISPONIBLE:
        grid = NoiseContour(calc, grid_size=grid_size).get_receptor_grid()
    else:
        grid = grille_recepteurs(grid_size)

    lden = calc.compute_grid(vols, grid)
    return grid, lden, len(vols)


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

        # fetch_realtime() de Syndia renvoie des clés longues
        # (latitude/longitude/baro_altitude) ; le prototype local_all
        # utilisait des clés courtes (lat/lon/alt_baro). On accepte les deux,
        # sinon lat=None → tous les avions filtrés (« 0 avion en vol »).
        "lat": a.get("latitude", a.get("lat")),

        "lon": a.get("longitude", a.get("lon")),

        "alt_baro": float(a.get("baro_altitude", a.get("alt_baro")) or 0.0),

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
    # ------------------------------------------------------------------
    # Sécurité de démonstration :
    # si aucun avion n'est fourni, on retourne immédiatement un niveau nul.
    # Cela évite de faire planter l'interface lorsque le mode live OpenSky
    # n'est pas activé ou lorsque l'API ne retourne aucun avion.
    # ------------------------------------------------------------------

    if not avions:
        return 0.0, []

    lat_rec, lon_rec = recepteur
    contributions = []

    # ------------------------------------------------------------------
    # Vrai modèle : on interroge la base NPD (ANPDatabase) pour CHAQUE
    # avion, exactement comme NoiseCalculator. La phase de vol est estimée
    # à partir du taux de montée ADS-B, qui détermine la poussée (donc la
    # courbe SEL à utiliser). La distance employée est la distance oblique
    # 3D (slant range) entre l'avion et le récepteur au sol.
    # ------------------------------------------------------------------

    for avion in avions:
        lat = avion.get("lat")
        lon = avion.get("lon")

        # On ignore les avions au sol ou sans position : leur bruit de
        # roulage n'est pas modélisé par les courbes NPD en survol.
        if lat is None or lon is None or avion.get("on_ground"):
            continue

        # Altitude AGL approximée : élévation de YUL ≈ 30 m, plancher 10 m
        # pour éviter une distance oblique nulle juste au-dessus du point.
        alt_agl = max((avion.get("alt_baro") or 0.0) - 30.0, 10.0)
        vertical_rate = avion.get("vertical_rate") or 0.0

        distance_sol_m = _haversine_m(lat_rec, lon_rec, lat, lon)
        distance_3d_m = math.sqrt(distance_sol_m ** 2 + alt_agl ** 2)

        # --------------------------------------------------------------
        # Phase de vol via le taux vertical (m/s), qui fixe la poussée :
        #   > 2 m/s  : montée  → décollage (< 305 m AGL) ou montée
        #   < -2 m/s : descente → approche
        #   sinon    : palier
        # _poussee() renvoie la valeur dans l'unité attendue par la base
        # (livres pour l'ANPDatabase de main, fraction N1 pour le prototype).
        # --------------------------------------------------------------

        if vertical_rate > 2.0:
            phase = "montée"
            op = "departure"
            thrust = _poussee("decollage" if alt_agl < 305 else "montee")
        elif vertical_rate < -2.0:
            phase = "descente"
            op, thrust = "arrival", _poussee("approche")
        else:
            phase = "palier"
            op, thrust = "departure", _poussee("palier")

        # SEL de la base NPD à la distance oblique, ramené à un ordre de
        # grandeur LAmax instantané (− LAMAX_OFFSET_DB).
        sel = anp.interpolate("A320", op, distance_3d_m, thrust)
        niveau_db = round(float(sel) - LAMAX_OFFSET_DB, 1)

        contributions.append(
            {
                "callsign": avion.get("callsign") or avion.get("icao24")
                or "Inconnu",
                "distance_m": round(distance_3d_m),
                "niveau_db": niveau_db,
                "phase": phase,
            }
        )

    if not contributions:
        return 0.0, []

    # ------------------------------------------------------------------
    # Addition logarithmique des contributions.
    #
    # Les décibels ne s'additionnent pas directement :
    # on convertit chaque niveau en énergie, on additionne les énergies,
    # puis on revient en dB.
    # ------------------------------------------------------------------

    energie_totale = sum(
        10 ** (contribution["niveau_db"] / 10)
        for contribution in contributions
    )

    niveau_total = 10 * math.log10(energie_totale)

    contributions.sort(
        key=lambda contribution: contribution["niveau_db"],
        reverse=True,
    )

    return niveau_total, contributions


def comparaison_parlante(lden):
    """
    Retourne une comparaison du quotidien permettant à un utilisateur
    non spécialiste de mieux interpréter un niveau Lden.

    L'objectif n'est pas de fournir une équivalence scientifique exacte,
    mais un ordre de grandeur parlant pour faciliter la compréhension
    des résultats présentés dans la démo.
    """

    # ------------------------------------------------------------------
    # Les seuils choisis correspondent à des ambiances sonores
    # généralement reconnues dans la littérature grand public.
    # ------------------------------------------------------------------

    if lden < 40:
        return (
            "Très calme : comparable à une bibliothèque ou à un quartier "
            "résidentiel paisible pendant la nuit."
        )

    elif lden < 55:
        return (
            "Calme à modéré : comparable à une conversation normale "
            "à l'intérieur d'une maison."
        )

    elif lden < 65:
        return (
            "Bruit soutenu : comparable à une rue urbaine animée. "
            "C'est le seuil à partir duquel l'information des riverains "
            "est généralement recommandée."
        )

    elif lden < 75:
        return (
            "Bruit élevé : comparable à une circulation routière dense. "
            "Une exposition prolongée peut devenir gênante."
        )

    else:
        return (
            "Très bruyant : comparable à une avenue très fréquentée "
            "ou à la proximité immédiate d'une importante source de bruit. "
            "Des mesures d'atténuation sont recommandées."
        )


# ---------------------------------------------------------------------------
# Cartes folium
# ---------------------------------------------------------------------------

def carte_contours(lden_values, grid_size, calc):
    """
    Carte folium avec les contours isophoniques 55/60/65/70 dB.

    Délègue à NoiseContour.plot_interactive() (classe de Syndia), qui
    interpole la surface Lden et trace les polygones réglementaires.
    """
    nc = NoiseContour(calc, grid_size=grid_size)
    return nc.plot_interactive(
        lden_values, title="Contours Lden — journée type YUL")


def carte_heatmap(lden, grid, grid_size, center=YUL, zoom=10):
    """
    Repli sans NoiseContour : surface Lden en surimpression semi-
    transparente.

    Cette fonction sert de solution de secours lorsque la classe
    NoiseContour n'est pas encore disponible. Elle ne trace pas de
    vrais contours isophoniques, mais elle permet quand même de
    visualiser les zones les plus exposées sur une carte Folium.
    """

    # ------------------------------------------------------------------
    # Création de la carte centrée sur YUL.
    # ------------------------------------------------------------------

    carte = folium.Map(location=center, zoom_start=zoom)

    folium.Marker(
        location=center,
        popup="Aéroport Montréal-Trudeau (YUL)",
        tooltip="YUL",
    ).add_to(carte)

    # ------------------------------------------------------------------
    # Affichage simplifié des niveaux de bruit.
    #
    # Chaque point de la grille est représenté par un petit cercle.
    # La couleur dépend du niveau Lden estimé :
    #   - < 55 dB  : exposition faible
    #   - 55-65 dB : seuil d'information
    #   - >= 65 dB : zone fortement exposée
    # ------------------------------------------------------------------

    for (lat, lon), niveau in zip(grid, lden):
        if niveau >= 65:
            couleur = "red"
        elif niveau >= 55:
            couleur = "orange"
        else:
            couleur = "green"

        folium.CircleMarker(
            location=[lat, lon],
            radius=3,
            color=couleur,
            fill=True,
            fill_opacity=0.45,
            popup=f"Lden estimé : {niveau:.1f} dB",
        ).add_to(carte)

    # ------------------------------------------------------------------
    # Cercle de référence : zone d'étude de 25 km autour de YUL.
    # ------------------------------------------------------------------

    folium.Circle(
        location=center,
        radius=RAYON_GRILLE_KM * 1000,
        tooltip="Zone d'étude : 25 km",
        fill=False,
    ).add_to(carte)

    return carte


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

st.title('✈️ AirNoisePy — le bruit des avions autour de YUL')
st.caption('Modélisation ECAC Doc 29 · données ADS-B OpenSky · base EASA '
           'ANP v9 — MGA802 ÉTS Été 2026, Équipe 4')

# ---------------------------------------------------------------------------
# Barre latérale
#
# Ces paramètres contrôlent la démonstration sans modifier le code source.
# La résolution de grille permet de choisir entre rapidité et finesse
# d'affichage. Le scénario de couvre-feu servira à comparer une journée
# normale avec une journée où les vols nocturnes sont réduits.
# ---------------------------------------------------------------------------

st.sidebar.header("⚙️ Paramètres de démonstration")

grid_size = st.sidebar.selectbox(
    "Résolution de la grille",
    options=[40, 60, 80],
    index=1,
    help=(
        "40 = rapide, 80 = plus détaillé. "
        "Cette valeur sera utilisée par les cartes et les calculs de grille."
    ),
)

curfew_actif = st.sidebar.toggle(
    "Scénario couvre-feu 23h–7h",
    value=False,
    help=(
        "Active un scénario de démonstration où les vols nocturnes "
        "sont réduits entre 23h et 7h."
    ),
)

st.sidebar.markdown("---")

st.sidebar.markdown("### Seuils réglementaires")

st.sidebar.info(
    "55 dB Lden : seuil d'information des riverains.\n\n"
    "65 dB Lden : seuil associé à l'isolation acoustique."
)

st.sidebar.caption(
    "Ces seuils servent de repères pour interpréter les cartes "
    "et les résultats affichés dans la démo."
)

if not CONTOUR_DISPONIBLE:
    st.sidebar.caption(
        "⏳ NoiseContour en cours d'intégration : surface Lden affichée "
        "en attendant les contours isophoniques."
    )

# ---------------------------------------------------------------------------
# Calcul partagé par les onglets
#
# La bibliothèque et la grille Lden sont calculées UNE fois ici (mise en
# cache Streamlit), puis réutilisées par tous les onglets. Les paramètres
# grid_size et couvre-feu de la barre latérale pilotent réellement le calcul.
# ---------------------------------------------------------------------------

anp, calc = charger_bibliotheque()

with st.spinner(f"Calcul du Lden sur {grid_size ** 2:,} récepteurs…"):
    grid, lden, n_vols = calculer_grille(curfew_actif, grid_size)

# Comparaison chiffrée quand le scénario couvre-feu est actif.
if curfew_actif:
    _, lden_ref, n_ref = calculer_grille(False, grid_size)
    st.info(
        f"🌙 Couvre-feu actif : {n_ref - n_vols} vols de nuit retirés "
        f"({n_vols} vols restants). "
        f"Lden max : {lden_ref.max():.1f} → {lden.max():.1f} dB(A)."
    )

tab_chez_vous, tab_anim, tab_live, tab_valid, tab_export = st.tabs([
    '🏠 Le bruit chez vous', '🕐 Journée 24h', '📡 Avions en direct',
    '✅ Validation WebTrak', '💾 Exports',
])

with tab_chez_vous:
    st.subheader("🏠 Le bruit chez vous")

    st.markdown(
        """
        Cliquez n'importe où sur la carte pour connaître le niveau de bruit
        aérien (Lden) à cet endroit, calculé par `NoiseCalculator` sur la
        journée type de YUL (~565 vols).
        """
    )

    # ------------------------------------------------------------------
    # Carte interactive centrée sur Montréal-Trudeau.
    #
    # Si NoiseContour est livré, on affiche les vrais contours isophoniques
    # 55/60/65/70 dB ; sinon on retombe sur une surface Lden colorée. Dans
    # les deux cas l'utilisateur peut cliquer pour choisir un récepteur.
    # ------------------------------------------------------------------

    if CONTOUR_DISPONIBLE:
        try:
            carte = carte_contours(lden, grid_size, calc)
        except Exception:
            carte = carte_heatmap(lden, grid, grid_size)
    else:
        carte = carte_heatmap(lden, grid, grid_size)

    resultat_carte = st_folium(
        carte,
        width=1000,
        height=420,
        returned_objects=["last_clicked"],
    )

    st.markdown("### Résultat du point choisi")

    if resultat_carte and resultat_carte.get("last_clicked"):
        lat = resultat_carte["last_clicked"]["lat"]
        lon = resultat_carte["last_clicked"]["lng"]

        # Lden réel à ce point : agrégation de tous les survols de la journée.
        recepteur = (lat, lon)
        vols = charger_vols()
        lden_point = calc.compute_lden(
            vols, recepteur, datetime.date(2026, 6, 10))
        distance_km = _haversine_m(YUL[0], YUL[1], lat, lon) / 1000

        col1, col2 = st.columns(2)

        with col1:
            st.metric("Lden à cet endroit", f"{lden_point:.1f} dB(A)")

        with col2:
            st.metric("Distance à YUL", f"{distance_km:.1f} km")

        st.write(comparaison_parlante(lden_point))

        if lden_point >= 65:
            st.error("Seuil 65 dB dépassé : isolation acoustique recommandée.")
        elif lden_point >= 55:
            st.warning("Seuil 55 dB dépassé : information des riverains.")
        else:
            st.success("Niveau inférieur aux principaux seuils réglementaires.")

        # Survol le plus bruyant de la journée à ce point (repère SEL).
        sel_max = max(calc.compute_sel(v, recepteur) for v in vols)
        st.caption(
            f"Survol le plus bruyant de la journée : SEL {sel_max:.1f} dB(A) — "
            f"point cliqué : latitude {lat:.5f}, longitude {lon:.5f}"
        )

    else:
        st.info("Cliquez sur la carte pour estimer le bruit à un point donné.")

with tab_anim:
    st.subheader("🕐 Journée 24h")

    st.markdown(
        """
        L'accumulation du bruit heure par heure : on voit les pointes du
        matin (7h–9h) et du soir (17h–19h) dessiner les couloirs de trafic.
        Le curseur ajoute les vols jusqu'à l'heure choisie et recalcule le
        Lden cumulé sur la grille.
        """
    )

    # ------------------------------------------------------------------
    # Le profil horaire réel de YUL (PROFIL_HORAIRE_YUL) sert à la fois à
    # afficher le nombre de mouvements de l'heure et à filtrer les vols
    # déjà partis pour le calcul cumulé.
    # ------------------------------------------------------------------

    heure = st.slider(
        "Heure de la journée",
        min_value=0,
        max_value=23,
        value=8,
        format="%dh00",
    )

    mouvements = PROFIL_HORAIRE_YUL[heure]

    st.metric(
        "Mouvements à cette heure",
        f"{mouvements} vols",
    )

    if 7 <= heure <= 9:
        st.warning("Pointe du matin : trafic élevé autour de YUL.")
    elif 17 <= heure <= 19:
        st.warning("Pointe du soir : trafic élevé autour de YUL.")
    elif 23 <= heure or heure < 6:
        st.info("Période nocturne : trafic réduit.")
    else:
        st.success("Trafic modéré.")

    # ------------------------------------------------------------------
    # Bruit cumulé de 0h à l'heure choisie : on garde les vols dont le
    # décollage a déjà eu lieu, puis on recalcule le Lden sur la grille.
    # ------------------------------------------------------------------

    vols = charger_vols()
    vols_jusqua = [v for v in vols
                   if calc._utc_hour(v.waypoints[0]['time']) <= heure]

    if vols_jusqua:
        import matplotlib.pyplot as plt

        lden_h = calc.compute_grid(vols_jusqua, grid)
        titre = f"Bruit accumulé de 0h00 à {heure}h59 — {len(vols_jusqua)} vols"

        if CONTOUR_DISPONIBLE:
            # plot() interpole la surface (griddata) → robuste à la grille
            # circulaire de NoiseContour. basemap=False pour rester hors-ligne.
            fig, _ = NoiseContour(calc, grid_size=grid_size).plot(
                lden_h, title=titre, basemap=False)
        else:
            surf = lden_h.reshape(grid_size, grid_size)
            fig, ax = plt.subplots(figsize=(7, 6))
            im = ax.imshow(
                surf, origin='lower', cmap='inferno',
                vmin=40, vmax=max(float(lden.max()), 41),
                extent=(grid[:, 1].min(), grid[:, 1].max(),
                        grid[:, 0].min(), grid[:, 0].max()),
                aspect='auto')
            fig.colorbar(im, ax=ax, label='Lden dB(A)', shrink=0.8)
            ax.plot(YUL[1], YUL[0], 'w*', markersize=12)
            ax.set_title(titre)

        st.pyplot(fig)
        plt.close(fig)
    else:
        st.info("Aucun vol avant cette heure dans la journée simulée.")

with tab_live:
    st.subheader("📡 Avions en direct")

    st.markdown(
        """
        **Le bruit en direct, n'importe où** : actualisez la position des
        avions, puis cliquez sur la carte — le niveau instantané estimé au
        point choisi est comparable à la lecture d'un sonomètre ADM sur
        WebTrak au même moment.

        **Optionnel** : c'est le seul onglet qui a besoin d'internet ; le
        reste de la démo fonctionne hors-ligne avec les données locales.
        """
    )

    # ------------------------------------------------------------------
    # Récupération à la demande (bouton) : on ne contacte JAMAIS OpenSky
    # au chargement de la page, et tout échec réseau est rattrapé pour ne
    # pas casser la démo en salle.
    # ------------------------------------------------------------------

    if st.button("📡 Actualiser les avions (OpenSky)"):
        try:
            from airnoisepy.flight.opensky import OpenSkyFetcher
            bruts = OpenSkyFetcher().fetch_realtime()
            st.session_state["avions_live"] = [_normaliser_avion(a)
                                               for a in bruts]
            st.session_state["avions_live_heure"] = \
                datetime.datetime.now().strftime("%H:%M:%S")
        except Exception as exc:
            st.error(f"API OpenSky injoignable ({exc}) — "
                     "la démo continue avec les données locales.")

    avions = st.session_state.get("avions_live")

    if avions is not None:
        en_vol = [a for a in avions
                  if not a["on_ground"] and a["lat"] is not None]
        st.success(
            f"{len(en_vol)} avions en vol autour de YUL "
            f"(snapshot de {st.session_state['avions_live_heure']} — "
            "réactualisez à volonté)"
        )

        col_live_carte, col_live_info = st.columns([3, 2])

        with col_live_carte:
            # Carte des avions, colorée par phase estimée (vertical_rate).
            m = folium.Map(location=YUL, zoom_start=10)
            for a in en_vol:
                vr = a.get("vertical_rate") or 0.0
                etat = "↗ monte" if vr > 2 else ("↘ descend" if vr < -2
                                                 else "→ palier")
                folium.Marker(
                    (a["lat"], a["lon"]),
                    tooltip=(f"{a['callsign'] or a['icao24']} — "
                             f"{(a['alt_baro'] or 0):.0f} m {etat}"),
                    icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
                ).add_to(m)
            retour_live = st_folium(m, height=480, use_container_width=True,
                                    key="carte_live")

        with col_live_info:
            clic = (retour_live or {}).get("last_clicked")
            if clic and en_vol:
                total, contribs = niveau_instantane(
                    en_vol, (clic["lat"], clic["lng"]), anp)
                st.metric("Niveau instantané estimé (avions seulement)",
                          f"{total:.1f} dB(A)")
                st.dataframe(contribs[:5], use_container_width=True)
                st.caption(
                    "⚠️ Contribution des avions uniquement : un sonomètre "
                    "mesure aussi le bruit de fond urbain (~45-55 dB). "
                    "Estimation LAmax dérivée des courbes SEL (−9 dB). La "
                    "comparaison n'a de sens que pendant un survol."
                )
                mesure_live = st.number_input(
                    "Niveau lu sur WebTrak au même endroit (dB)",
                    value=0.0, step=0.5, key="mesure_webtrak_live")
                if mesure_live > 0:
                    ecart = total - mesure_live
                    if abs(ecart) <= 3.0:
                        st.success(f"Écart modèle/mesure : {ecart:+.1f} dB "
                                   "— dans la tolérance ECAC ±3 dB ✅")
                    else:
                        st.warning(f"Écart modèle/mesure : {ecart:+.1f} dB "
                                   "— hors tolérance (bruit de fond ? "
                                   "avion hors zone ?)")
            elif not en_vol:
                st.info("Aucun avion en vol dans la zone en ce moment.")
            else:
                st.markdown("👈 *Cliquez sur la carte pour estimer le "
                            "bruit instantané à cet endroit.*")
    else:
        st.info("Cliquez sur **📡 Actualiser les avions** pour récupérer "
                "les vols en direct autour de YUL (nécessite internet).")

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

    # ------------------------------------------------------------------
    # Quelques points représentatifs autour de YUL (proches de capteurs
    # ADM). Le Lden « calculé » n'est plus saisi à la main : il provient
    # du vrai calcul NoiseCalculator à l'endroit choisi.
    # ------------------------------------------------------------------

    capteurs = {
        "Centre YUL": (45.4706, -73.7408),
        "Dorval": (45.450, -73.750),
        "Pointe-Claire": (45.448, -73.800),
        "Saint-Laurent": (45.500, -73.700),
    }

    nom_point = st.selectbox("Point de validation", list(capteurs.keys()))
    recepteur_valid = capteurs[nom_point]

    vols = charger_vols()
    niveau_calcule = calc.compute_lden(
        vols, recepteur_valid, datetime.date(2026, 6, 10))

    niveau_mesure = st.number_input(
        "Niveau mesuré par WebTrak / ADM (dB)",
        value=61.5,
        step=0.5,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Lden calculé par AirNoisePy", f"{niveau_calcule:.1f} dB")
    with col2:
        st.metric("Écart modèle / mesure",
                  f"{abs(niveau_calcule - niveau_mesure):.1f} dB")

    ecart = abs(niveau_calcule - niveau_mesure)

    if ecart <= 3:
        st.success(
            "PASS : l'écart respecte la tolérance ECAC Doc 29 (±3 dB)."
        )
    else:
        st.error(
            "FAIL : l'écart dépasse la tolérance ECAC Doc 29 (±3 dB)."
        )

    st.caption(
        "Le Lden calculé est obtenu par NoiseCalculator à ce point ; "
        "ajustez la mesure WebTrak/ADM pour comparer."
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

# ---------------------------------------------------------------------
# Pied de page
#
# La démonstration doit rester entièrement fonctionnelle hors-ligne.
# Les logos sont donc chargés depuis le dossier local assets/
# plutôt qu'à partir d'URLs externes.
# ---------------------------------------------------------------------

st.divider()

st.markdown("### 📄 Licence")

st.write(
    "Distribué sous licence MIT. "
    "Voir le fichier LICENSE.md pour plus de détails."
)

st.markdown("### 📚 Citation")

st.caption(
    "Kevin, Bouchra, Syndia, Laura. "
    "AirNoisePy: a Python tool for aircraft noise modelling around "
    "Montréal-Trudeau airport (ECAC Doc 29), "
    "MGA802, École de technologie supérieure, Montréal, 2026."
)

st.markdown("### 🔧 Technologies utilisées")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.image("assets/numpy.svg", width=80)

with col2:
    st.image("assets/pandas.svg", width=80)

with col3:
    st.image("assets/folium.png", width=80)

with col4:
    st.image("assets/github.png", width=80)
