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
import base64
import inspect
import datetime

# ---------------------------------------------------------------------------
# Bibliothèques tierces utilisées par la démo Streamlit
# ---------------------------------------------------------------------------

import numpy as np
import pandas as pd
import folium
import requests
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

# Les 7 capteurs de bruit ADM / WebTrak autour de YUL (coordonnées relevées sur
# les emplacements physiques des sonomètres). Servent de points de validation
# (Lden calculé vs mesuré, tolérance ECAC ±3 dB) et sont affichés en petits
# cercles gris sur les cartes de la démo. Ajouter 'lden_mesure' par capteur
# quand les valeurs mesurées seront disponibles, pour automatiser le PASS/FAIL.
CAPTEURS_ADM = [
    {'nom': 'Dollard-des-Ormeaux',          'lat': 45.484016, 'lon': -73.808965},
    {'nom': 'Dorval (Goldfinch)',           'lat': 45.454440, 'lon': -73.773712},
    {'nom': 'Saint-Laurent (Marcel-Laurin)', 'lat': 45.507180, 'lon': -73.682075},
    {'nom': 'Montréal (Chester)',           'lat': 45.466662, 'lon': -73.650561},
    {'nom': 'Pointe-Claire (Winthrop)',     'lat': 45.464802, 'lon': -73.808135},
    {'nom': 'Dorval (Dawson)',              'lat': 45.441824, 'lon': -73.758733},
    {'nom': 'Saint-Laurent (H4R 1T4)',      'lat': 45.508961, 'lon': -73.703225},
]

st.set_page_config(page_title='AirNoisePy — bruit aérien YUL',
                   page_icon='✈️', layout='wide')


# ---------------------------------------------------------------------------
# Habillage visuel (maquette de présentation) : zone principale claire, barre
# latérale sombre (voir .streamlit/config.toml). Le CSS ci-dessous stylise les
# éléments sur mesure que Streamlit ne fournit pas tels quels : cartes de
# mesures, sous-titre à puces, marque de la barre latérale, cartes de seuils.
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* Système typographique IBM Plex : Sans pour l'UI (config.toml), Mono pour
       les valeurs chiffrées/techniques (règles ci-dessous). @import en premier. */
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
    /* ---- En-tête principal ---- */
    .titre-app {
        font-size: 2.15rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        margin: 0;
        line-height: 1.1;
    }
    .sous-titre {
        color: #6b7280;
        font-size: 0.95rem;
        margin: 0.15rem 0 0.4rem;
    }
    .sous-titre code {
        background: #eceef1;
        color: #3a3d42;
        padding: 0.05rem 0.4rem;
        border-radius: 6px;
        font-size: 0.82em;
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
    }
    /* intitulé de section en petites capitales grises */
    .section-label {
        text-transform: uppercase;
        letter-spacing: 0.13em;
        font-size: 0.78rem;
        font-weight: 700;
        color: #9aa1ad;
        margin: 1.5rem 0 0.85rem;
    }
    /* ---- Grille de cartes de mesures ---- */
    .cartes-metriques {
        display: grid;
        gap: 1rem;
        margin-bottom: 0.5rem;
    }
    .carte-metrique {
        background: #ffffff;
        border: 1px solid #e6e8ec;
        border-radius: 14px;
        padding: 1.1rem 1.2rem;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    }
    .carte-metrique .label {
        color: #6b7280;
        font-size: 0.85rem;
        margin-bottom: 0.55rem;
    }
    .carte-metrique .valeur {
        font-size: 2.4rem;
        font-weight: 700;
        line-height: 1;
        display: flex;
        align-items: baseline;
        gap: 0.25rem;
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
    }
    /* carte « texte » (ex. Classe d'exposition) : pas un nombre → reste en Sans,
       un peu plus petite pour éviter les débordements (« Très élevée »). */
    .carte-metrique .valeur.valeur--texte {
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 1.75rem;
        font-weight: 700;
    }
    .carte-metrique .unite {
        font-size: 1rem;
        font-weight: 500;
        color: #9aa1ad;
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
    }
    .carte-metrique .sous {
        color: #6b7280;
        font-size: 0.82rem;
        margin-top: 0.6rem;
    }
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.78rem;
        font-weight: 600;
        padding: 0.3rem 0.65rem;
        border-radius: 999px;
        margin-top: 0.65rem;
    }
    .badge .point { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
    .badge--amber { background: #fbf0d5; color: #d98a00; }
    .badge--red   { background: #fdecec; color: #dc3a34; }
    .badge--green { background: #e3f5e9; color: #16a34a; }
    /* ---- Puces de fichiers (onglet Exports) ---- */
    .chip-fichier {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        background: #eef0f3;
        border: 1px solid #e6e8ec;
        border-radius: 9px;
        padding: 0.35rem 0.6rem;
        margin: 0.25rem 0.4rem 0 0;
        font-size: 0.85rem;
    }
    .chip-fichier code { background: #e6e8ec; border-radius: 5px; padding: 0 0.3rem; font-size: 0.8em; font-family: 'IBM Plex Mono', ui-monospace, monospace; }
    /* ---- Marque de la barre latérale ---- */
    .marque { display: flex; align-items: center; gap: 0.7rem; padding: 0.1rem 0 0.4rem; }
    .marque-logo {
        width: 44px; height: 44px; border-radius: 13px;
        background: linear-gradient(135deg, #e8554d, #c92f29);
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 6px 16px rgba(220, 58, 52, 0.40);
    }
    .marque-nom { font-weight: 800; font-size: 1.15rem; line-height: 1.1; }
    .marque-sous { font-size: 0.78rem; color: #9098a6; }
    /* ---- Cartes de seuils (barre latérale) ---- */
    .seuils-titre {
        text-transform: uppercase; letter-spacing: 0.12em;
        font-size: 0.74rem; font-weight: 700; color: #9098a6;
        margin: 0.4rem 0 0.6rem;
    }
    .seuil-carte {
        background: #1e222a;
        border: 1px solid #2b303a;
        border-radius: 11px; padding: 0.6rem 0.75rem; margin-bottom: 0.55rem;
        display: flex; gap: 0.6rem; align-items: flex-start;
    }
    .seuil-dot { width: 11px; height: 11px; border-radius: 50%; margin-top: 0.3rem; flex: none; }
    .seuil-titre { font-weight: 600; font-size: 0.92rem; font-family: 'IBM Plex Mono', ui-monospace, monospace; }
    .seuil-desc { font-size: 0.8rem; color: #9098a6; }
    .seuil-note { font-size: 0.78rem; color: #9098a6; margin-top: 0.3rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Marque (logo + nom) tout en haut de la barre latérale.
st.sidebar.markdown(
    """
    <div class="marque">
      <div class="marque-logo">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="#ffffff"
             xmlns="http://www.w3.org/2000/svg">
          <path d="M2.5 19h19v2h-19v-2zm19.57-9.36c-.21-.8-1.04-1.28-1.84-1.06L14.92
                   10l-6.9-6.43-1.93.51 4.14 7.17-4.97 1.33-1.97-1.54-1.45.39 2.59
                   4.49 1.97-.53L8.99 16l-1.94.52 2.59 4.49 1.45-.39.39-1.45
                   1.97-.53 8.55-2.29c.81-.23 1.28-1.05 1.07-1.86z"/>
        </svg>
      </div>
      <div>
        <div class="marque-nom">AirNoisePy</div>
        <div class="marque-sous">Bruit aérien · YUL</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Image de fond de la barre latérale (coucher de soleil depuis un hublot),
# encodée base64 pour rester hors-ligne / sur Streamlit Cloud. Voile dégradé
# léger en haut (l'image reste bien visible, opacité élevée) puis plus dense
# vers le bas pour garder les réglages et les seuils lisibles.
_FOND_SIDEBAR = os.path.join(RACINE, 'assets', 'fond_sidebar.jpg')
if os.path.exists(_FOND_SIDEBAR):
    with open(_FOND_SIDEBAR, 'rb') as _f:
        _b64 = base64.b64encode(_f.read()).decode()
    st.markdown(
        f"""
        <style>
        section[data-testid="stSidebar"] > div:first-child {{
            background-image:
                linear-gradient(rgba(22, 25, 31, 0.18), rgba(22, 25, 31, 0.74)),
                url("data:image/jpeg;base64,{_b64}");
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }}
        /* cartes de seuils en verre dépoli translucide : on voit l'image
           derrière tout en gardant le texte lisible */
        section[data-testid="stSidebar"] .seuil-carte {{
            background: rgba(20, 24, 30, 0.55);
            border-color: rgba(255, 255, 255, 0.10);
            -webkit-backdrop-filter: blur(4px);
            backdrop-filter: blur(4px);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Chargement de la bibliothèque (mis en cache par Streamlit)
# ---------------------------------------------------------------------------

@st.cache_resource
def charger_bibliotheque():
    """ANPDatabase (réelle si le fichier NPD est lisible, sinon table
    synthétique de secours) + NoiseCalculator prêt à l'emploi.

    Le repli synthétique couvre aussi le cas où openpyxl n'est pas installé
    (ex. déploiement Streamlit Cloud sans la dépendance) : la lecture du
    .xlsx lève alors une erreur, rattrapée ici pour ne pas casser la démo.
    """
    anp = None
    if os.path.exists(NPD_XLSX):
        try:
            anp = ANPDatabase(NPD_XLSX)
        except Exception:
            anp = None  # openpyxl manquant / fichier illisible → synthétique
    if anp is None:
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


@st.cache_data(show_spinner="Construction de l'animation 24h…")
def construire_gif_24h(grid_size, duree_s):
    """
    Construit une animation GIF de l'accumulation du bruit sur 24 h.

    Une image par heure (0h → 23h) : pour chaque heure on agrège le Lden
    de TOUS les vols partis jusque-là, puis on rend une carte de chaleur.
    L'échelle de couleur est FIXÉE sur le maximum de la journée complète,
    de sorte que les couleurs soient comparables d'une image à l'autre et
    que l'on VOIE réellement le bruit monter aux heures de pointe.

    Paramètres
    ----------
    grid_size : int
        Côté de la grille carrée de récepteurs (grid_size² points).
    duree_s : float
        Durée totale souhaitée de l'animation, en secondes. Les 24 images
        sont réparties uniformément (durée par image = duree_s / 24).

    Retour
    -------
    bytes
        Le GIF animé prêt à être affiché par st.image (boucle infinie).

    Notes
    -----
    Pour la fluidité et la robustesse, l'animation utilise une grille
    CARRÉE dédiée (grille_recepteurs) affichée en imshow, indépendamment
    de NoiseContour : 24 images se calculent en quelques secondes et le
    résultat est mis en cache (une seule construction par scénario).
    """

    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import imageio.v2 as imageio

    _, calc_local = charger_bibliotheque()
    vols = charger_vols()
    grille = grille_recepteurs(grid_size)

    # Étendue géographique pour l'axe de la carte.
    etendue = (grille[:, 1].min(), grille[:, 1].max(),
               grille[:, 0].min(), grille[:, 0].max())

    # Étape 1 : 24 surfaces de Lden cumulé, calculées de façon ADDITIVE.
    # Le Lden est une agrégation d'énergie en log (calculator.py:149-152) :
    # on calcule donc CHAQUE heure une seule fois (vols de cette heure-là),
    # puis on cumule les énergies. C'est ~10× plus rapide que de recalculer
    # tous les vols à chaque heure, et le résultat est identique au dB près.
    surfaces = []
    compteurs = []
    energie = np.zeros(len(grille))
    total_vols = 0
    for h in range(24):
        vols_h = [v for v in vols
                  if calc_local._utc_hour(v.waypoints[0]['time']) == h]
        total_vols += len(vols_h)
        if vols_h:
            lden_h = calc_local.compute_grid(vols_h, grille)
            # Lden == 0 (np.zeros) = cellule sans énergie → on n'ajoute rien ;
            # cellule valide (Lden éventuellement négatif) → 10^(Lden/10).
            energie += np.where(lden_h != 0.0, 10 ** (lden_h / 10.0), 0.0)
        lden_cumule = np.where(energie > 0, 10 * np.log10(energie), np.nan)
        surfaces.append(lden_cumule.reshape(grid_size, grid_size))
        compteurs.append(total_vols)

    # Échelle de couleur fixe : la dernière image (= journée complète) donne
    # la borne haute commune, pour que les couleurs soient comparables.
    vmax = max(float(np.nanmax(surfaces[-1])), 41.0)

    # Étape 2 : une SEULE figure (et une seule colorbar) réutilisée pour
    # les 24 images — on ne met à jour que les données et le titre. C'est
    # bien plus rapide que de recréer une figure par image.
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(
        surfaces[0], origin='lower', cmap='inferno',
        vmin=40, vmax=vmax, extent=etendue, aspect='auto')
    fig.colorbar(im, ax=ax, label='Lden dB(A)', shrink=0.8)
    ax.plot(YUL[1], YUL[0], 'w*', markersize=12)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    images = []
    for h in range(24):
        im.set_data(surfaces[h])
        ax.set_title(f"Bruit accumulé 0h00 → {h:02d}h59 — "
                     f"{compteurs[h]} vols")
        fig.canvas.draw()
        largeur, hauteur = fig.canvas.get_width_height()
        image = np.frombuffer(
            fig.canvas.buffer_rgba(), dtype=np.uint8
        ).reshape(hauteur, largeur, 4)[:, :, :3].copy()
        images.append(image)
    plt.close(fig)

    sortie = io.BytesIO()
    # imageio >= 2.34 : duration = MILLISECONDES par image ; loop=0 = boucle
    # infinie. 24 images réparties sur duree_s → duree_s/24*1000 ms par image.
    imageio.mimsave(sortie, images, format="GIF",
                    duration=duree_s / 24.0 * 1000.0, loop=0)
    return sortie.getvalue()


def explorer_journee(grid_size):
    """Vue interactive à l'heure choisie (curseur + cartes + carte de bruit).

    Utilise les variables globales calc / grid / lden calculées une fois
    pour toute l'application (résolues à l'appel, pendant le rendu des
    onglets).
    """

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

    # ------------------------------------------------------------------
    # Bruit cumulé de 0h à l'heure choisie : on garde les vols dont le
    # décollage a déjà eu lieu, puis on recalcule le Lden sur la grille.
    # ------------------------------------------------------------------

    vols = charger_vols()
    vols_jusqua = [v for v in vols
                   if calc._utc_hour(v.waypoints[0]['time']) <= heure]

    lden_h = calc.compute_grid(vols_jusqua, grid) if vols_jusqua else None
    lden_max_h = f"{lden_h.max():.0f}" if lden_h is not None else "—"

    # Contexte horaire : pastille de la première carte.
    if 7 <= heure <= 9 or 17 <= heure <= 19:
        contexte = _badge("pointe de trafic", "red")
    elif heure >= 23 or heure < 6:
        contexte = _badge("période nocturne", "amber")
    else:
        contexte = _badge("trafic modéré", "green")

    rendre_cartes([
        {"label": "Mouvements à cette heure", "valeur": f"{mouvements}",
         "unite": "vols", "badge": contexte},
        {"label": "Vols cumulés depuis 00h", "valeur": f"{len(vols_jusqua)}",
         "sous": "sur la journée type"},
        {"label": "Lden cumulé (max grille)", "valeur": lden_max_h,
         "unite": "dB", "sous": "cellule la plus exposée"},
    ])

    # ------------------------------------------------------------------
    # Carte (contour) inchangée — laissée pour la passe « cartes ».
    # ------------------------------------------------------------------
    if vols_jusqua:
        import matplotlib.pyplot as plt

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


@st.cache_data(ttl=3600, show_spinner=False)
def geocoder_adresse(adresse):
    """
    Convertit une adresse saisie librement en coordonnées géographiques.

    On interroge le service public Nominatim (OpenStreetMap). La recherche
    est biaisée sur la grande région de Montréal (countrycodes=ca + cadre
    géographique autour de YUL) afin qu'une adresse partielle (« 100 rue
    Sainte-Catherine ») tombe au bon endroit plutôt qu'ailleurs au Canada.

    Paramètres
    ----------
    adresse : str
        Adresse, intersection ou lieu saisi par l'utilisateur.

    Retour
    -------
    tuple(float, float, str) ou None
        (latitude, longitude, nom complet retourné) si une correspondance
        est trouvée, sinon None (adresse vide, introuvable ou réseau
        injoignable — la démo continue alors sans planter).

    Notes
    -----
    Le géocodage nécessite internet, comme l'onglet « Avions en direct ».
    Le résultat est mis en cache 1 h (st.cache_data) pour éviter de
    re-solliciter Nominatim à chaque interaction Streamlit.
    """

    adresse = (adresse or "").strip()
    if not adresse:
        return None

    try:
        reponse = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": adresse,
                "format": "json",
                "limit": 1,
                "countrycodes": "ca",
                # Cadre (viewbox) autour de YUL pour prioriser le Grand
                # Montréal : (lon_min, lat_max, lon_max, lat_min).
                "viewbox": "-74.10,45.75,-73.30,45.30",
                "bounded": 0,
            },
            headers={"User-Agent": "AirNoisePy/0.1 (projet MGA802 ETS)"},
            timeout=8,
        )
        reponse.raise_for_status()
        resultats = reponse.json()
    except Exception:
        return None

    if not resultats:
        return None

    premier = resultats[0]
    return (float(premier["lat"]), float(premier["lon"]),
            premier.get("display_name", adresse))


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
# Cartes de mesures (habillage maquette)
# ---------------------------------------------------------------------------

def _badge(texte, type_):
    """Pastille colorée (amber/red/green) avec un point, pour les cartes."""
    return (f'<div class="badge badge--{type_}">'
            f'<span class="point"></span>{texte}</div>')


def _svg_fichier(couleur):
    """Petite icône « document » SVG inline (offline) de la couleur donnée,
    pour les puces de fichiers de l'onglet Exports."""
    return (
        f'<svg width="15" height="15" viewBox="0 0 24 24" fill="{couleur}" '
        f'style="vertical-align:-2px" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 '
        f'0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>'
        f'</svg>')


def _carte_html(label, valeur, unite="", sous="", accent="#1b1e25", badge="",
                mono=True):
    """HTML d'une carte de mesure : intitulé, grande valeur + unité,
    pastille optionnelle, sous-texte optionnel. mono=False pour une valeur
    textuelle (mot) qui doit rester en IBM Plex Sans plutôt qu'en Mono."""
    classe = "valeur" if mono else "valeur valeur--texte"
    sous_html = f'<div class="sous">{sous}</div>' if sous else ""
    return (f'<div class="carte-metrique">'
            f'<div class="label">{label}</div>'
            f'<div class="{classe}" style="color:{accent}">{valeur}'
            f'<span class="unite">{unite}</span></div>'
            f'{badge}{sous_html}</div>')


def rendre_cartes(cartes):
    """Affiche une rangée de cartes de mesures (1 colonne par carte)."""
    cols = max(len(cartes), 1)
    inner = "".join(_carte_html(**c) for c in cartes)
    st.markdown(
        f'<div class="cartes-metriques" '
        f'style="grid-template-columns:repeat({cols},minmax(0,1fr))">'
        f'{inner}</div>',
        unsafe_allow_html=True,
    )


def _classe_exposition(lden):
    """(mot, couleur, sous-texte) décrivant la classe d'exposition Lden."""
    if lden < 55:
        return "Faible", "#16a34a", "Sous le seuil d'information (55 dB)"
    if lden < 65:
        return "Modérée", "#fb923c", "Entre information (55) et isolation (65)"
    if lden < 75:
        return "Élevée", "#f1592a", "Au-delà du seuil d'isolation (65 dB)"
    return "Très élevée", "#c81e1e", "Exposition très forte, atténuation requise"


# ---------------------------------------------------------------------------
# Cartes folium
# ---------------------------------------------------------------------------

def ajouter_capteurs_adm(carte):
    """Ajoute les capteurs ADM/WebTrak en petits cercles gris sur une carte
    folium (un marqueur par emplacement, nom en infobulle)."""
    for capteur in CAPTEURS_ADM:
        folium.CircleMarker(
            location=(capteur['lat'], capteur['lon']),
            radius=5,
            color='gray',
            weight=1,
            fill=True,
            fill_color='gray',
            fill_opacity=0.8,
            tooltip=f"Capteur ADM — {capteur['nom']}",
        ).add_to(carte)
    return carte


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

# En-tête : titre + bouton « Partager », puis sous-titre à puces (chips).
col_titre, col_partage = st.columns([8, 1.5], vertical_alignment="center")

with col_titre:
    st.markdown(
        "<h1 class='titre-app'>Le bruit des avions autour de YUL</h1>",
        unsafe_allow_html=True,
    )

with col_partage:
    st.link_button(
        "Partager",
        "https://github.com/kevin-noah/equipe4-airnoisepy-20262",
        icon=":material/share:",
        use_container_width=True,
    )

st.markdown(
    "<div class='sous-titre'>Modélisation <code>ECAC Doc 29</code> · "
    "données <code>ADS-B OpenSky</code> · base <code>EASA ANP v9</code> "
    "— MGA802 ÉTS Été 2026, Équipe 4</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Barre latérale
#
# Ces paramètres contrôlent la démonstration sans modifier le code source.
# La résolution de grille permet de choisir entre rapidité et finesse
# d'affichage. Le scénario de couvre-feu servira à comparer une journée
# normale avec une journée où les vols nocturnes sont réduits.
# ---------------------------------------------------------------------------

st.sidebar.header(":material/settings: Paramètres")

grid_size = st.sidebar.selectbox(
    "Résolution de la grille",
    options=[40, 60, 80],
    index=1,
    format_func=lambda n: f"{n} × {n} points",
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

st.sidebar.markdown(
    """
    <div class="seuils-titre">Seuils réglementaires</div>
    <div class="seuil-carte">
      <span class="seuil-dot" style="background:#fbbf24"></span>
      <div>
        <div class="seuil-titre">55 dB Lden</div>
        <div class="seuil-desc">Seuil d'information des riverains.</div>
      </div>
    </div>
    <div class="seuil-carte">
      <span class="seuil-dot" style="background:#f1592a"></span>
      <div>
        <div class="seuil-titre">65 dB Lden</div>
        <div class="seuil-desc">Seuil associé à l'isolation acoustique.</div>
      </div>
    </div>
    <div class="seuil-note">Ces seuils servent de repères pour interpréter
    les cartes et les résultats affichés.</div>
    """,
    unsafe_allow_html=True,
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
    ':material/home: Le bruit chez vous',
    ':material/schedule: Journée 24h',
    ':material/rss_feed: Avions en direct',
    ':material/check: Validation WebTrak',
    ':material/download: Exports',
])

with tab_chez_vous:
    st.subheader(":material/home: Le bruit chez vous")

    st.markdown(
        """
        Saisissez votre adresse **ou** cliquez n'importe où sur la carte pour
        connaître le niveau de bruit aérien (Lden) à cet endroit, calculé par
        `NoiseCalculator` sur la journée type de YUL (~565 vols).
        """
    )

    # ------------------------------------------------------------------
    # Saisie d'adresse : géocodage Nominatim -> récepteur.
    #
    # Le point retenu (adresse géocodée OU dernier clic carte) est mémorisé
    # dans st.session_state['pt_chez_vous'] = (lat, lon, libellé source).
    # ------------------------------------------------------------------

    col_adr, col_btn = st.columns([5, 1], vertical_alignment="bottom")
    with col_adr:
        adresse_saisie = st.text_input(
            "Votre adresse",
            placeholder="ex. 975 boulevard de la Côte-Vertu, Saint-Laurent",
            key="adr_chez_vous",
        )
    with col_btn:
        localiser = st.button("Localiser", icon=":material/search:",
                              key="btn_adr_chez_vous",
                              use_container_width=True)

    if localiser:
        geo = geocoder_adresse(adresse_saisie)
        if geo is not None:
            st.session_state["pt_chez_vous"] = (geo[0], geo[1], geo[2])
        else:
            st.warning("Adresse introuvable (ou réseau injoignable). "
                       "Réessayez ou cliquez directement sur la carte.")

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

    # capteurs ADM/WebTrak en petits cercles gris
    ajouter_capteurs_adm(carte)

    # Marqueur sur le point déjà choisi (adresse géocodée ou clic précédent).
    pt_courant = st.session_state.get("pt_chez_vous")
    if pt_courant is not None:
        folium.Marker(
            (pt_courant[0], pt_courant[1]),
            tooltip="Votre point",
            icon=folium.Icon(color="red", icon="home", prefix="fa"),
        ).add_to(carte)

    # ------------------------------------------------------------------
    # Affichage grand format pour la présentation orale.
    #
    # La carte utilise toute la largeur disponible du navigateur et une
    # hauteur importante afin d'éviter de zoomer ou de déplacer la carte
    # pendant la démo.
    # ------------------------------------------------------------------

    resultat_carte = st_folium(
        carte,
        height=780,
        use_container_width=True,
        returned_objects=["last_clicked"],
    )

    # Un clic sur la carte remplace le point courant (s'il a changé).
    clic_chez_vous = (resultat_carte or {}).get("last_clicked")
    if clic_chez_vous:
        cle_clic = (clic_chez_vous["lat"], clic_chez_vous["lng"])
        if st.session_state.get("dernier_clic_chez_vous") != cle_clic:
            st.session_state["dernier_clic_chez_vous"] = cle_clic
            st.session_state["pt_chez_vous"] = (
                cle_clic[0], cle_clic[1], "Point cliqué sur la carte")

    st.markdown("<div class='section-label'>Résultat du point choisi</div>",
                unsafe_allow_html=True)

    pt_chez_vous = st.session_state.get("pt_chez_vous")
    if pt_chez_vous is not None:
        lat, lon, source_pt = pt_chez_vous

        # Lden réel à ce point : agrégation de tous les survols de la journée.
        recepteur = (lat, lon)
        vols = charger_vols()
        lden_point = calc.compute_lden(
            vols, recepteur, datetime.date(2026, 6, 10))
        distance_km = _haversine_m(YUL[0], YUL[1], lat, lon) / 1000

        # SEL de chaque survol : sert au repère « plus bruyant » et au compte
        # des vols qui contribuent réellement (SEL >= 45 dB(A)) à ce point.
        sels = [calc.compute_sel(v, recepteur) for v in vols]
        sel_max = max(sels)
        contributeurs = sum(1 for s in sels if s >= 45)

        # Carte 1 : pastille de seuil selon le niveau Lden.
        if lden_point >= 65:
            badge = _badge("Au-dessus du seuil 65 dB", "red")
        elif lden_point >= 55:
            badge = _badge("Au-dessus du seuil 55 dB", "amber")
        else:
            badge = _badge("Sous les seuils réglementaires", "green")

        classe, couleur, classe_sous = _classe_exposition(lden_point)

        rendre_cartes([
            {"label": "Niveau Lden", "valeur": f"{lden_point:.0f}",
             "unite": "dB", "badge": badge},
            {"label": "Classe d'exposition", "valeur": classe,
             "accent": couleur, "sous": classe_sous, "mono": False},
            {"label": "Distance à YUL", "valeur": f"{distance_km:.1f}",
             "unite": "km", "sous": "Centre de Montréal-Trudeau"},
            {"label": "Vols contributeurs", "valeur": f"{contributeurs}",
             "sous": f"sur ~{n_vols} mouvements / jour"},
        ])

        st.caption(
            f"{comparaison_parlante(lden_point)}  \n"
            f"Survol le plus bruyant de la journée : SEL {sel_max:.1f} dB(A) — "
            f"{source_pt} (latitude {lat:.5f}, longitude {lon:.5f})"
        )

    else:
        st.info("Saisissez votre adresse ou cliquez sur la carte pour "
                "estimer le bruit à un point donné.")

with tab_anim:
    st.subheader(":material/schedule: Journée 24h")

    st.markdown(
        """
        L'accumulation du bruit heure par heure : on voit les pointes du
        matin (7h–9h) et du soir (17h–19h) dessiner les couloirs de trafic.
        Lancez l'**animation** pour voir la journée se dérouler d'un coup,
        ou utilisez le **curseur** pour explorer une heure précise.
        """
    )

    mode_anim = st.radio(
        "Affichage",
        ["▶ Animation 24h", "Curseur (exploration)"],
        horizontal=True,
        key="mode_journee",
    )

    if mode_anim == "▶ Animation 24h":
        # --------------------------------------------------------------
        # Animation : un GIF de 24 images (une par heure) joué en boucle.
        # La durée totale est réglable (10–15 s). Le GIF est mis en cache,
        # donc seul le premier rendu prend quelques secondes.
        # --------------------------------------------------------------
        duree = st.slider("Durée de l'animation (s)", 10, 15, 12)
        gif = construire_gif_24h(grid_size, duree)
        st.image(gif, use_container_width=True)
        st.caption(
            "Lecture en boucle : le bruit cumulé s'étend aux heures de "
            f"pointe puis sature. Échelle de couleur fixée sur le maximum "
            f"de la journée ({grid_size} × {grid_size} récepteurs)."
        )

    else:
        explorer_journee(grid_size)


with tab_live:
    st.subheader(":material/rss_feed: Avions en direct")

    st.markdown(
        """
        **Le bruit en direct, n'importe où** : actualisez la position des
        avions, puis saisissez votre adresse ou cliquez sur la carte — le
        niveau instantané estimé au point choisi est comparable à la lecture
        d'un sonomètre ADM sur WebTrak au même moment.

        Vous pouvez aussi **ajouter un avion virtuel** (position, altitude,
        phase) pour voir son effet sonore combiné aux avions réels.

        **Optionnel** : seul l'ajout des avions réels a besoin d'internet ;
        l'avion virtuel et le reste de la démo fonctionnent hors-ligne.
        """
    )

    # ------------------------------------------------------------------
    # Récupération à la demande (bouton) : on ne contacte JAMAIS OpenSky
    # au chargement de la page, et tout échec réseau est rattrapé pour ne
    # pas casser la démo en salle.
    # ------------------------------------------------------------------

    if st.button("Actualiser les avions (OpenSky)", icon=":material/sync:"):
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

    # Saisie d'adresse : point retenu dans st.session_state['pt_live']
    # = (lat, lon, libellé), partagé avec le clic carte ci-dessous.
    col_adr_live, col_btn_live = st.columns([5, 1],
                                            vertical_alignment="bottom")
    with col_adr_live:
        adresse_live = st.text_input(
            "Votre adresse",
            placeholder="ex. 975 boulevard de la Côte-Vertu, Saint-Laurent",
            key="adr_live",
        )
    with col_btn_live:
        localiser_live = st.button("Localiser", icon=":material/search:",
                                   key="btn_adr_live",
                                   use_container_width=True)

    if localiser_live:
        geo_live = geocoder_adresse(adresse_live)
        if geo_live is not None:
            st.session_state["pt_live"] = (geo_live[0], geo_live[1],
                                           geo_live[2])
        else:
            st.warning("Adresse introuvable (ou réseau injoignable). "
                       "Réessayez ou cliquez directement sur la carte.")

    # ------------------------------------------------------------------
    # Avion virtuel : l'utilisateur place un appareil fictif (position,
    # altitude, phase) pour voir son effet sonore COMBINÉ aux avions réels.
    # Les avions virtuels sont stockés dans st.session_state['avions_virtuels']
    # et passent par le même modèle (niveau_instantane). Avantage : ça marche
    # MÊME sans OpenSky → l'onglet reste démontrable hors-ligne.
    # ------------------------------------------------------------------
    pt_live_defaut = st.session_state.get("pt_live")
    lat_defaut = pt_live_defaut[0] if pt_live_defaut else YUL[0]
    lon_defaut = pt_live_defaut[1] if pt_live_defaut else YUL[1]

    with st.expander("Ajouter un avion virtuel (simulation A320)",
                     icon=":material/add_circle:"):
        st.caption(
            "Placez un avion fictif et observez son effet sur le niveau au "
            "point choisi, additionné aux avions réels. Position par défaut : "
            "au-dessus de votre point. Type A320 supposé (comme le modèle live)."
        )
        with st.form("form_avion_virtuel"):
            cva, cvb = st.columns(2)
            with cva:
                v_lat = st.number_input("Latitude", value=float(lat_defaut),
                                        format="%.5f", step=0.001)
                v_alt = st.slider("Altitude au-dessus du sol (m)",
                                  100, 4000, 500, step=50)
            with cvb:
                v_lon = st.number_input("Longitude", value=float(lon_defaut),
                                        format="%.5f", step=0.001)
                v_phase = st.selectbox(
                    "Phase de vol",
                    ["Montée (décollage)", "Palier", "Descente (approche)"])
            v_nom = st.text_input("Indicatif", value="VIRTUEL")
            ajouter_avion = st.form_submit_button(
                "Ajouter l'avion", icon=":material/flight:")

        if ajouter_avion:
            # La phase fixe le taux vertical, dont niveau_instantane déduit
            # l'opération et la poussée (donc la courbe SEL).
            vr_phase = {"Montée (décollage)": 5.0, "Palier": 0.0,
                        "Descente (approche)": -5.0}[v_phase]
            virtuels = st.session_state.setdefault("avions_virtuels", [])
            virtuels.append({
                "icao24": "VIRT",
                "callsign": (v_nom or "VIRTUEL").strip(),
                "lat": float(v_lat),
                "lon": float(v_lon),
                "alt_baro": float(v_alt),
                "on_ground": False,
                "vertical_rate": vr_phase,
                "virtuel": True,
            })

        if st.session_state.get("avions_virtuels"):
            st.write(f"**{len(st.session_state['avions_virtuels'])}** "
                     "avion(s) virtuel(s) actif(s).")
            if st.button("Effacer les avions virtuels",
                         icon=":material/delete:"):
                st.session_state["avions_virtuels"] = []

    # ------------------------------------------------------------------
    # Fusion avions réels (OpenSky) + avions virtuels pour la carte et le
    # calcul. L'onglet fonctionne dès qu'il y a AU MOINS un avion (réel ou
    # virtuel), même si OpenSky n'a pas été sollicité.
    # ------------------------------------------------------------------
    avions = st.session_state.get("avions_live")
    en_vol_reels = [a for a in (avions or [])
                    if not a["on_ground"] and a["lat"] is not None]
    avions_virtuels = st.session_state.get("avions_virtuels", [])
    en_vol = en_vol_reels + avions_virtuels

    if avions is not None:
        st.success(
            f"{len(en_vol_reels)} avions réels en vol autour de YUL "
            f"(snapshot de {st.session_state['avions_live_heure']})"
            + (f" + {len(avions_virtuels)} virtuel(s)"
               if avions_virtuels else "")
        )
    elif avions_virtuels:
        st.info(f"{len(avions_virtuels)} avion(s) virtuel(s) — mode hors-ligne "
                "(OpenSky non sollicité). Actualisez pour ajouter les réels.")

    if en_vol:
        col_live_carte, col_live_info = st.columns([3, 2])

        with col_live_carte:
            # Carte des avions, colorée par phase estimée (vertical_rate).
            # Les avions virtuels sont en orange pour les distinguer.
            m = folium.Map(location=YUL, zoom_start=10)
            for a in en_vol:
                vr = a.get("vertical_rate") or 0.0
                etat = "↗ monte" if vr > 2 else ("↘ descend" if vr < -2
                                                 else "→ palier")
                est_virtuel = a.get("virtuel")
                folium.Marker(
                    (a["lat"], a["lon"]),
                    tooltip=(("VIRTUEL · " if est_virtuel else "")
                             + f"{a['callsign'] or a['icao24']} — "
                             f"{(a['alt_baro'] or 0):.0f} m {etat}"),
                    icon=folium.Icon(
                        color="orange" if est_virtuel else "blue",
                        icon="plane", prefix="fa"),
                ).add_to(m)
            # capteurs ADM/WebTrak en petits cercles gris
            ajouter_capteurs_adm(m)
            # Marqueur sur le point choisi (adresse géocodée ou clic).
            pt_live_courant = st.session_state.get("pt_live")
            if pt_live_courant is not None:
                folium.Marker(
                    (pt_live_courant[0], pt_live_courant[1]),
                    tooltip="Votre point",
                    icon=folium.Icon(color="red", icon="home", prefix="fa"),
                ).add_to(m)
            retour_live = st_folium(m, height=480, use_container_width=True,
                                    key="carte_live")

        # Un clic sur la carte remplace le point courant (s'il a changé).
        clic = (retour_live or {}).get("last_clicked")
        if clic:
            cle_clic_live = (clic["lat"], clic["lng"])
            if st.session_state.get("dernier_clic_live") != cle_clic_live:
                st.session_state["dernier_clic_live"] = cle_clic_live
                st.session_state["pt_live"] = (
                    cle_clic_live[0], cle_clic_live[1],
                    "Point cliqué sur la carte")

        with col_live_info:
            pt_live = st.session_state.get("pt_live")
            if pt_live:
                lat_live, lon_live, source_live = pt_live
                total, contribs = niveau_instantane(
                    en_vol, (lat_live, lon_live), anp)
                st.metric("Niveau instantané estimé (avions seulement)",
                          f"{total:.1f} dB(A)")
                st.caption(f"{source_live} — latitude {lat_live:.5f}, "
                           f"longitude {lon_live:.5f}")

                # Effet propre de l'avion virtuel : écart avec / sans.
                if avions_virtuels:
                    total_sans, _ = niveau_instantane(
                        en_vol_reels, (lat_live, lon_live), anp)
                    if total_sans > 0:
                        st.caption(
                            f"Sans le(s) avion(s) virtuel(s) : "
                            f"{total_sans:.1f} dB(A) → effet : "
                            f"**{total - total_sans:+.1f} dB**")
                    else:
                        st.caption(
                            "Aucun autre avion ne contribue ici : le niveau "
                            "provient du seul avion virtuel.")

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
            else:
                st.markdown("👈 *Saisissez votre adresse ou cliquez sur la "
                            "carte pour estimer le bruit instantané à cet "
                            "endroit.*")
    else:
        st.info("Cliquez sur **Actualiser les avions** (internet) ou ajoutez "
                "un **avion virtuel** ci-dessus pour estimer le bruit.")

with tab_valid:
    st.subheader(":material/check: Validation WebTrak / ADM")

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

    capteurs = {c['nom']: (c['lat'], c['lon']) for c in CAPTEURS_ADM}

    nom_point = st.selectbox("Capteur ADM / WebTrak", list(capteurs.keys()))
    recepteur_valid = capteurs[nom_point]

    vols = charger_vols()
    niveau_calcule = calc.compute_lden(
        vols, recepteur_valid, datetime.date(2026, 6, 10))

    niveau_mesure = st.number_input(
        "Niveau mesuré par WebTrak / ADM (dB)",
        value=61.5,
        step=0.5,
    )

    ecart = abs(niveau_calcule - niveau_mesure)

    if ecart <= 3:
        badge_valid = _badge("Dans la tolérance ±3 dB", "green")
        accent_ecart = "#16a34a"
    else:
        badge_valid = _badge("Hors tolérance ±3 dB", "red")
        accent_ecart = "#dc3a34"

    rendre_cartes([
        {"label": "Lden calculé (AirNoisePy)",
         "valeur": f"{niveau_calcule:.1f}", "unite": "dB", "sous": nom_point},
        {"label": "Lden mesuré (WebTrak / ADM)",
         "valeur": f"{niveau_mesure:.1f}", "unite": "dB",
         "sous": "valeur saisie ci-dessus"},
        {"label": "Écart modèle / mesure", "valeur": f"{ecart:.1f}",
         "unite": "dB", "accent": accent_ecart, "badge": badge_valid},
    ])

    st.caption(
        "Le Lden calculé est obtenu par NoiseCalculator à ce point ; "
        "ajustez la mesure WebTrak/ADM pour comparer."
    )

with tab_export:
    st.markdown("<div class='section-label'>Export des résultats</div>",
                unsafe_allow_html=True)

    st.markdown(
        "Partagez les résultats obtenus après calcul. La classe "
        "`ResultsExporter` produit les exports complets du projet — "
        "grille Lden (CSV), carte interactive (HTML) et animation 24 h (GIF)."
    )

    st.markdown(
        f"""
        <div class="carte-metrique" style="margin-top:0.6rem">
          <div class="label">Exports de la session courante</div>
          <div style="font-weight:700;font-size:1.05rem;margin:0.1rem 0 0.7rem">
            Résolution {grid_size}×{grid_size} · journée type · ~{n_vols} vols
          </div>
          <span class="chip-fichier">{_svg_fichier('#6b7280')} lden_grid<code>.csv</code></span>
          <span class="chip-fichier">{_svg_fichier('#6b7280')} carte<code>.html</code></span>
          <span class="chip-fichier">{_svg_fichier('#6b7280')} animation<code>.gif</code></span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Afin d'éviter que l'onglet Exports ne génère automatiquement
    # des fichiers au chargement de l'application, nous demandons
    # explicitement à l'utilisateur de lancer la démonstration.
    #
    # Cette approche améliore également la robustesse de l'application :
    # chaque onglet reste indépendant des autres.
    # ------------------------------------------------------------------

    if st.button("Générer les exports", type="primary", icon=":material/download:"):

        # --------------------------------------------------------------
        # Jeu de données simplifié utilisé uniquement à des fins
        # de démonstration Streamlit.
        #
        # Ces valeurs représentent trois vols fictifs présentant
        # différents niveaux d'exposition sonore.
        # --------------------------------------------------------------

        donnees_demo = pd.DataFrame(
            {
                "latitude": grid[:, 0],
                "longitude": grid[:, 1],
                "lden_db": lden,
            }
        )

        donnees_demo["zone"] = donnees_demo["lden_db"].apply(
            lambda x: (
                "Inférieure à 55 dB"
                if x < 55
                else "55–65 dB"
                if x < 65
                else "≥ 65 dB"
            )
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

col_lic, col_cit = st.columns(2)

with col_lic:
    st.markdown("<div class='section-label'>Licence</div>",
                unsafe_allow_html=True)
    st.write(
        "Distribué sous licence MIT. "
        "Voir le fichier `LICENSE.md` pour plus de détails."
    )

with col_cit:
    st.markdown("<div class='section-label'>Citation</div>",
                unsafe_allow_html=True)
    st.caption(
        "Kevin, Bouchra, Syndia, Laura. "
        "AirNoisePy: a Python tool for aircraft noise modelling around "
        "Montréal-Trudeau airport (ECAC Doc 29), "
        "MGA802, École de technologie supérieure, Montréal, 2026."
    )
