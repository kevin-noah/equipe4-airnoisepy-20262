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
    /* ---- Mise en page : contenu collé en haut et au ruban de gauche ----
       Streamlit ajoute par défaut un grand padding (haut + latéral) qui pousse
       le contenu vers le bas et la droite. On le réduit fortement pour que le
       héros monte en haut, que le contenu touche la barre latérale sombre et
       que la carte soit visible sans défiler (comme la maquette). */
    [data-testid="stMainBlockContainer"], .block-container,
    [data-testid="stAppViewBlockContainer"] {
        max-width: 100% !important;
        padding-top: 0 !important;
        padding-left: 1.6rem !important;
        padding-right: 1.6rem !important;
        padding-bottom: 2rem !important;
    }
    /* barre d'en-tête Streamlit (menu Deploy) masquée pour que la bande héros
       couvre tout le haut, jusqu'au bord supérieur */
    [data-testid="stHeader"] { display: none; }
    /* Les blocs `st.markdown("<style>…")` injectés en tête créent des
       conteneurs vides qui ajoutent un écart au-dessus du héros. On les
       replie : leur CSS reste actif (un <style> s'applique globalement même si
       son conteneur est masqué), mais ils ne réservent plus d'espace. */
    [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] style) {
        display: none !important;
    }
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
    /* ---- Grille de cartes de mesures (verre dépoli façon Apple) ---- */
    .cartes-metriques {
        display: grid;
        gap: 1rem;
        margin-bottom: 0.5rem;
    }
    .carte-metrique {
        position: relative;
        background: rgba(255, 255, 255, 0.72);
        -webkit-backdrop-filter: blur(28px) saturate(180%);
        backdrop-filter: blur(28px) saturate(180%);
        border: 0.5px solid rgba(255, 255, 255, 0.8);
        border-radius: 16px;
        padding: 1.15rem 1.15rem 1.05rem;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04),
                    0 10px 30px rgba(16, 24, 40, 0.06);
        transition: transform 0.16s ease, box-shadow 0.16s ease;
    }
    .carte-metrique:hover {
        transform: translateY(-4px);
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05),
                    0 18px 40px rgba(220, 58, 52, 0.18),
                    0 0 0 1px rgba(220, 58, 52, 0.18);
    }
    .carte-metrique .label {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        color: #8a9099;
        font-size: 0.69rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 13px;
    }
    .carte-metrique .label svg { width: 16px; height: 16px; flex: none; }
    .carte-metrique .valeur {
        font-size: 2.6rem;
        font-weight: 500;
        line-height: 0.9;
        display: flex;
        align-items: baseline;
        gap: 5px;
        letter-spacing: -0.03em;
        font-variant-numeric: tabular-nums;
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
    }
    /* carte « texte » (ex. Classe d'exposition) : pas un nombre → reste en Sans,
       un peu plus petite pour éviter les débordements (« Très élevée »). */
    .carte-metrique .valeur.valeur--texte {
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 1.7rem;
        font-weight: 600;
        letter-spacing: -0.02em;
    }
    .carte-metrique .unite {
        font-size: 1rem;
        font-weight: 500;
        color: #8a9099;
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
    }
    .carte-metrique .sous {
        color: #6b7280;
        font-size: 11.5px;
        line-height: 1.45;
        margin-top: 9px;
    }
    /* badge inline (maquette) : pastille sobre alignée à droite de la valeur */
    .carte-metrique .valeur > .badge,
    .carte-metrique .valeur > .carte-badge {
        margin-left: auto; margin-top: 0; align-self: center;
    }
    .carte-badge {
        display: inline-flex; align-items: center;
        padding: 3px 9px; border-radius: 999px;
        font-size: 10.5px; font-weight: 600;
        font-family: 'IBM Plex Sans', sans-serif; letter-spacing: 0;
    }
    /* ---- Carte « Classe d'exposition » : grand mot coloré + barre segmentée ---- */
    .classe-val { font-size: 1.7rem; font-weight: 600; letter-spacing: -0.02em;
                  line-height: 1; }
    .expo-bar { display: flex; gap: 5px; margin-top: 14px; }
    .expo-bar span { flex: 1; height: 6px; border-radius: 999px; }
    .expo-labels { display: flex; justify-content: space-between;
                   font-size: 10px; color: #8a9099; margin-top: 6px; }
    .expo-labels .on { font-weight: 600; }
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
    /* ---- Marque de la barre latérale ---- */
    .marque { display: flex; align-items: center; gap: 12px;
              padding: 2px 6px 0; margin-bottom: 0.9rem; }
    .marque-logo {
        width: 38px; height: 38px; border-radius: 11px; flex: none;
        background: linear-gradient(160deg, #dc3a34, #9e2722);
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 4px 14px rgba(220, 58, 52, 0.45),
                    inset 0 1px 0 rgba(255, 255, 255, 0.25);
    }
    .marque-nom { font-weight: 600; font-size: 16px; line-height: 1.15;
                  letter-spacing: -0.01em; color: #eef1f5; }
    .marque-sous { font-size: 11px; color: rgba(238, 241, 245, 0.62);
                   letter-spacing: 0.02em; }
    /* ---- Intitulés de section de la barre latérale (Réglages / Seuils) ---- */
    .seuils-titre, .reglages-label {
        text-transform: uppercase; letter-spacing: 0.10em;
        font-size: 10.5px; font-weight: 600; color: rgba(238, 241, 245, 0.5);
        margin: 0.3rem 0 0.55rem;
    }
    /* ---- Cartes de seuils (verre dépoli sur le dégradé sidebar) ---- */
    .seuil-carte {
        border-radius: 14px; padding: 13px 15px; margin-bottom: 0.6rem;
        display: flex; gap: 10px; align-items: flex-start;
    }
    .seuil-dot { width: 9px; height: 9px; border-radius: 50%;
                 margin-top: 0.42rem; flex: none; }
    .seuil-titre { font-weight: 600; font-size: 18px; letter-spacing: -0.01em;
                   color: #eef1f5;
                   font-family: 'IBM Plex Mono', ui-monospace, monospace; }
    .seuil-titre .u { font-size: 11px; font-weight: 400;
                      color: rgba(238, 241, 245, 0.6); margin-left: 3px;
                      font-family: 'IBM Plex Mono', ui-monospace, monospace; }
    .seuil-desc { font-size: 11.5px; line-height: 1.4;
                  color: rgba(238, 241, 245, 0.74); }
    .seuil-note { font-size: 0.78rem; color: rgba(238, 241, 245, 0.42);
                  margin-top: 0.3rem; }
    /* ---- Point « live » pulsant sur l'élément de nav « Avions en direct »
       (3e option). Point corail inline + anneau qui pulse via box-shadow. ---- */
    @keyframes anp-pulse {
        0%   { box-shadow: 0 0 0 0 rgba(255, 138, 130, 0.55); }
        70%  { box-shadow: 0 0 0 6px rgba(255, 138, 130, 0); }
        100% { box-shadow: 0 0 0 0 rgba(255, 138, 130, 0); }
    }
    [data-testid="stSidebar"] [role="radiogroup"] > label:nth-of-type(3) p::after {
        content: ""; display: inline-block; width: 7px; height: 7px;
        margin-left: 8px; border-radius: 50%; background: #ff8a82;
        vertical-align: middle;
        animation: anp-pulse 2s ease-out infinite;
    }
    /* ---- En-tête héros (bandeau dégradé ardoise→rouge, surtitre + badges) ---- */
    .hero {
        position: relative;
        border-radius: 0;
        overflow: hidden;
        padding: 1.5rem 1.6rem;
        /* pleine largeur : on déborde sur les côtés pour toucher la barre
           latérale à gauche ; en haut la bande part du bord supérieur */
        margin: 0 -1.6rem 0.8rem -1.6rem;
        background: linear-gradient(110deg, #16191f 0%, #2a2128 42%,
                                    #7a2a2a 78%, #dc3a34 122%);
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.10),
                    0 18px 44px -18px rgba(16, 24, 40, 0.45);
    }
    /* halo rouge diffus en haut à droite */
    .hero::after {
        content: ""; position: absolute; right: -40px; top: -60px;
        width: 300px; height: 300px; border-radius: 50%; pointer-events: none;
        background: radial-gradient(circle, rgba(255, 138, 130, 0.28),
                                    transparent 65%);
    }
    .hero > * { position: relative; z-index: 1; }
    /* ligne : texte à gauche, bouton Partager intégré en haut à droite */
    .hero-row { display: flex; align-items: flex-start;
                justify-content: space-between; gap: 1.5rem; }
    .hero-share {
        flex: none; display: inline-flex; align-items: center; gap: 8px;
        padding: 0.62rem 1.1rem; border-radius: 12px; text-decoration: none;
        background: rgba(255, 255, 255, 0.14); color: #fff;
        border: 0.5px solid rgba(255, 255, 255, 0.26);
        font-size: 0.84rem; font-weight: 600;
        -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18);
        transition: transform 0.14s ease, background 0.14s ease;
    }
    .hero-share:hover { transform: translateY(-2px);
                        background: rgba(255, 255, 255, 0.22); }
    .hero-share svg { width: 15px; height: 15px; fill: currentColor; }
    .hero .overline {
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
        font-size: 0.7rem; font-weight: 500; letter-spacing: 0.14em;
        text-transform: uppercase; color: rgba(255, 255, 255, 0.62);
        margin-bottom: 0.7rem;
    }
    .hero h1 {
        font-size: 2.06rem; font-weight: 600; letter-spacing: -0.022em;
        line-height: 1.08; margin: 0; color: #ffffff;
    }
    .hero .badges { display: flex; flex-wrap: wrap; gap: 0.56rem; margin-top: 1rem; }
    .hero .badge-hero {
        display: inline-flex; align-items: center; gap: 7px;
        font-size: 0.72rem; font-weight: 500; padding: 0.37rem 0.75rem;
        border-radius: 999px; color: rgba(255, 255, 255, 0.92);
        background: rgba(255, 255, 255, 0.12);
        border: 0.5px solid rgba(255, 255, 255, 0.18);
        -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
    }
    .hero .badge-hero::before {
        content: ""; width: 6px; height: 6px; border-radius: 50%;
        background: #ff8a82; flex: none;
    }
    /* ---- Navigation latérale en pilules (radio → menu iPadOS) ---- */
    [data-testid="stSidebar"] [role="radiogroup"] {
        gap: 3px !important;
    }
    [data-testid="stSidebar"] [role="radiogroup"] > label {
        display: flex !important; align-items: center;
        width: 100%; padding: 11px 13px !important; margin: 0 !important;
        border-radius: 13px; cursor: pointer; min-height: 0;
        transition: background 0.14s ease, box-shadow 0.14s ease;
    }
    /* masquer le rond radio natif */
    [data-testid="stSidebar"] [role="radiogroup"] > label > div:first-child {
        display: none !important;
    }
    [data-testid="stSidebar"] [role="radiogroup"] > label p {
        font-size: 14px; font-weight: 500; color: rgba(238, 241, 245, 0.82);
        transition: color 0.14s ease;
    }
    [data-testid="stSidebar"] [role="radiogroup"] > label:hover {
        background: rgba(255, 255, 255, 0.09);
    }
    [data-testid="stSidebar"] [role="radiogroup"] > label:hover p { color: #fff; }
    /* pilule active : dégradé rouge + ombre */
    [data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {
        background: linear-gradient(165deg, #e0463f, #dc3a34);
        box-shadow: 0 6px 16px rgba(220, 58, 52, 0.40);
    }
    [data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) p {
        color: #fff; font-weight: 600;
    }
    /* ---- Sliders : pouce blanc à ombre, piste arrondie ---- */
    [data-testid="stSlider"] div[role="slider"] {
        background-color: #ffffff !important;
        border: 0.5px solid rgba(0, 0, 0, 0.06) !important;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.16),
                    0 4px 12px rgba(0, 0, 0, 0.22) !important;
    }
    [data-testid="stSliderThumbValue"] { font-variant-numeric: tabular-nums; }
    /* ---- Slider de résolution (sidebar) façon maquette ----
       valeur en haut à droite (HTML), piste pleine largeur, pas de pastille
       sur le pouce ni de bornes min/max sous la piste. */
    [data-testid="stSidebar"] [data-testid="stSliderThumbValue"],
    [data-testid="stSidebar"] [data-testid="stSliderTickBar"],
    [data-testid="stSidebar"] [data-testid="stSliderTickBarMin"],
    [data-testid="stSidebar"] [data-testid="stSliderTickBarMax"] {
        display: none !important;
    }
    /* piste un peu plus longue : on annule la marge interne du widget */
    [data-testid="stSidebar"] [data-testid="stSlider"] { padding: 4px 0 2px; }
    .grid-row { display: flex; align-items: baseline;
        justify-content: space-between; margin-bottom: -6px; }
    .grid-lab { font-size: 13px; font-weight: 500;
        color: rgba(238, 241, 245, 0.92); }
    .grid-val { font-family: 'IBM Plex Mono', ui-monospace, monospace;
        font-size: 14px; font-weight: 500; color: #ff8a82;
        font-variant-numeric: tabular-nums; }
    .grid-ends { display: flex; justify-content: space-between;
        font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 9.5px;
        color: rgba(238, 241, 245, 0.42); margin-top: -10px; }
    /* ---- Plus d'air vertical entre les blocs de la barre latérale ---- */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 1.05rem;
    }
    /* sauf à l'intérieur du menu de navigation (pilules resserrées) */
    [data-testid="stSidebar"] [role="radiogroup"] { gap: 4px !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Marque (logo + nom) tout en haut de la barre latérale.
st.sidebar.markdown(
    """
    <div class="marque">
      <div class="marque-logo">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
             stroke="#ffffff" stroke-width="2" stroke-linecap="round"
             stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
          <path d="M2 12h4l3-8 2 8h9"/>
          <path d="M2 16h7l2 5 2-9"/>
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

# Fond de la barre latérale (maquette) : base presque noire — sombre en haut
# ET en bas — avec un halo chaud orange concentré au centre-droit, derrière la
# navigation. 100 % CSS → hors-ligne, pas de dépendance à un fichier image.
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] > div:first-child {
        background:
            radial-gradient(480px 440px at 62% 31%,
                rgba(233, 120, 58, 0.34), rgba(190, 72, 50, 0.12) 46%,
                transparent 70%),
            linear-gradient(180deg, #1b1e24 0%, #17181d 52%, #121215 100%);
        background-attachment: local;
    }
    /* cartes de seuils en verre dépoli clair (maquette) : on voit le dégradé
       derrière tout en gardant le texte lisible */
    section[data-testid="stSidebar"] .seuil-carte {
        background: rgba(255, 255, 255, 0.07);
        border-color: rgba(255, 255, 255, 0.14);
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.22);
        -webkit-backdrop-filter: blur(16px) saturate(160%);
        backdrop-filter: blur(16px) saturate(160%);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Navigation principale (barre latérale) : menu vertical en pilules, comme la
# maquette Claude Design. La pilule active est en dégradé rouge. La vue choisie
# pilote l'affichage du corps de l'app plus bas (un bloc `if vue == ...`).
# Les libellés portent une icône Material gérée nativement par Streamlit.
# ---------------------------------------------------------------------------

NAV = [
    ':material/pin_drop: Le bruit chez vous',
    ':material/schedule: Journée 24h',
    ':material/flight: Avions en direct',
    ':material/fact_check: Validation WebTrak',
    ':material/download: Exports',
]

vue = st.sidebar.radio('Navigation', NAV, label_visibility='collapsed')


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


# Icônes SVG inline (offline) pour les intitulés des cartes de résultat —
# tracés Material (graphic_eq, show_chart, straighten, flight). Couleur via
# currentColor (définie en style inline sur le <svg>).
_ICONES_CARTE = {
    "lden": "M7 18h2V6H7v12zm4 4h2V2h-2v20zm-8-8h2v-4H3v4zm12 4h2V6h-2v12zm"
            "4-8v4h2v-4h-2z",
    "expo": "M3.5 18.49l6-6.01 4 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z",
    "distance": "M21 6H3c-1.1 0-2 .9-2 2v8c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V8c0-"
                "1.1-.9-2-2-2zm0 10H3V8h2v4h2V8h2v4h2V8h2v4h2V8h2v4h2V8h2v8z",
    "vols": "M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-"
            "2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z",
    # cible (point choisi / coordonnées)
    "cible": "M12 8c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm8.94 3"
             "c-.46-4.17-3.77-7.48-7.94-7.94V1h-2v2.06C6.83 3.52 3.52 6.83 3.06"
             " 11H1v2h2.06c.46 4.17 3.77 7.48 7.94 7.94V23h2v-2.06c4.17-.46 7.48"
             "-3.77 7.94-7.94H23v-2h-2.06zM12 19c-3.87 0-7-3.13-7-7s3.13-7 7-7 7"
             " 3.13 7 7-3.13 7-7 7z",
    "info": "M11 7h2v2h-2zm0 4h2v6h-2zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-"
            "4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 "
            "8 8-3.59 8-8 8z",
    "cloud_off": "M19.35 10.04C18.67 6.59 15.64 4 12 4c-1.48 0-2.85.43-4.01 1.17"
                 "l1.46 1.46C10.21 6.23 11.08 6 12 6c3.04 0 5.5 2.46 5.5 5.5v.5H"
                 "19c1.66 0 3 1.34 3 3 0 1.13-.64 2.11-1.56 2.62l1.45 1.45C23.16"
                 " 18.16 24 16.68 24 15c0-2.64-2.05-4.78-4.65-4.96zM3 5.27l2.75 "
                 "2.74C2.56 8.15 0 10.77 0 14c0 3.31 2.69 6 6 6h11.73l2 2L21 20."
                 "73 4.27 4 3 5.27zM7.73 10l8 8H6c-2.21 0-4-1.79-4-4s1.79-4 4-4h"
                 "1.73z",
    # phases de vol (Material : flight_land / flight_takeoff / flight)
    "land": "M2.5 19h19v2h-19v-2zm16.84-5.16c.8.21 1.62-.26 1.84-1.06.21-.8-.26"
            "-1.62-1.06-1.84l-5.31-1.42-2.76-9.02L10.12 0v8.28L5.15 6.95l-.93-2"
            ".32-1.45-.39v5.17l16.42 4.43z",
    "takeoff": "M2.5 19h19v2h-19v-2zm19.57-9.36c-.21-.8-1.04-1.28-1.84-1.06L14.92"
               " 10l-6.9-6.43-1.93.51 4.14 7.17-4.97 1.33-1.97-1.54-1.45.39 2.59"
               " 4.49 1.97-.53L8.99 16l-1.94.52 2.59 4.49 1.45-.39.39-1.45 1.97-"
               ".53 8.55-2.29c.81-.23 1.28-1.05 1.07-1.86z",
    "level": "M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-"
             "2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z",
    # onglet Exports : pastilles de session, icônes de fichiers, etc.
    "grid_on": "M20 2H4c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4c0-1"
               ".1-.9-2-2-2zM8 20H4v-4h4v4zm0-6H4v-4h4v4zm0-6H4V4h4v4zm6 12h-4v-"
               "4h4v4zm0-6h-4v-4h4v4zm0-6h-4V4h4v4zm6 12h-4v-4h4v4zm0-6h-4v-4h4v"
               "4zm0-6h-4V4h4v4z",
    "sun": "M6.76 4.84l-1.8-1.79-1.41 1.41 1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2z"
           "m9-9.95h-2V3.5h2V.55zm7.45 3.91l-1.41-1.41-1.79 1.79 1.41 1.41 1.79-"
           "1.79zm-3.21 13.7l1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2"
           "h-3zm-8-5c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm-1 16"
           ".95h2V19.5h-2v2.95zm-7.45-3.91l1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z",
    "table": "M10 10.02h5V21h-5zM17 21h3c1.1 0 2-.9 2-2v-9h-5v11zm3-18H5c-1.1 0-"
             "2 .9-2 2v3h19V5c0-1.1-.9-2-2-2zM3 19c0 1.1.9 2 2 2h3V10H3v9z",
    "map": "M20.5 3l-.16.03L15 5.1 9 3 3.36 4.9c-.21.07-.36.25-.36.48V20.5c0 .28"
           ".22.5.5.5l.16-.03L9 18.9l6 2.1 5.64-1.9c.21-.07.36-.25.36-.48V3.5c0-"
           ".28-.22-.5-.5-.5zM15 19l-6-2.11V5l6 2.11V19z",
    "movie": "M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 "
             "2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z",
    "bolt": "M11 21h-1l1-7H7.5c-.58 0-.57-.32-.38-.66.19-.34.05-.08.07-.12C8.48 "
            "10.94 10.42 7.54 13 3h1l-1 7h3.5c.49 0 .56.33.47.51l-.07.15C12.96 1"
            "7.55 11 21 11 21z",
    "balance": "M12 3c-1.27 0-2.4.8-2.82 2H3v2h2.95L2 14c-.47 2 1 3 3.5 3s4.01-1"
               " 3.5-3L6.05 7h3.12c.33.85.98 1.5 1.83 1.83V20H2v2h20v-2h-9V8.83c"
               ".85-.33 1.5-.98 1.83-1.83h3.12L15 14c-.47 2 1 3 3.5 3s4.01-1 3.5"
               "-3l-2.95-7H21V5h-6.18C14.4 3.8 13.27 3 12 3zm2.37 12l1.63-3.91L1"
               "7.63 15h-3.26zm-8 0L8 11.09 9.63 15H6.37zM12 7c-.55 0-1-.45-1-1s"
               ".45-1 1-1 1 .45 1 1-.45 1-1 1z",
    "quote": "M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z",
    "download": "M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z",
}


def _ico(cle, couleur):
    """SVG d'icône de carte (16×16) coloré, pour les intitulés."""
    return (f'<svg viewBox="0 0 24 24" fill="{couleur}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<path d="{_ICONES_CARTE[cle]}"/></svg>')


# Style des badges de phase (onglet Avions en direct), fidèle à la maquette :
# (libellé, fond, couleur texte, clé d'icône).
_PHASE_STYLE = {
    "descente": ("Descente", "rgba(67,160,74,.12)",  "#2f8a3c", "land"),
    "montée":   ("Montée",   "rgba(239,139,46,.14)", "#c46a16", "takeoff"),
    "palier":   ("Palier",   "rgba(120,128,140,.12)", "#6b7280", "level"),
}


def _phase_badge(phase):
    """Pastille de phase de vol (Descente/Montée/Palier) avec icône, fidèle
    à la maquette des vols contributeurs."""
    libelle, bg, couleur, cle = _PHASE_STYLE.get(
        (phase or "").lower(), _PHASE_STYLE["palier"])
    svg = (f'<svg viewBox="0 0 24 24" fill="{couleur}" '
           f'xmlns="http://www.w3.org/2000/svg">'
           f'<path d="{_ICONES_CARTE[cle]}"/></svg>')
    return (f'<span class="phase-badge" style="background:{bg};color:{couleur}">'
            f'{svg}{libelle}</span>')


# CSS scopé à l'onglet « Avions en direct » (classes lv-*), fidèle à la maquette.
_CSS_LIVE = """
<style>
.lv-head { display:flex; align-items:flex-start; justify-content:space-between;
    gap:16px; margin:0.2rem 0 0.2rem; }
.lv-titrow { display:flex; align-items:center; gap:11px; }
.lv-titrow h2 { font-size:20px; font-weight:600; letter-spacing:-.015em;
    margin:0; color:#1b1e25; }
.lv-sub { margin:9px 0 0; font-size:13.5px; line-height:1.55; color:#6b7280;
    max-width:760px; }
.badge-live { display:inline-flex; align-items:center; gap:7px; padding:4px 11px;
    border-radius:999px; background:rgba(220,58,52,.10); color:#dc3a34;
    font-size:11px; font-weight:700; letter-spacing:.04em; }
.badge-live .d { width:7px; height:7px; border-radius:50%; background:#dc3a34;
    animation:anp-pulse 2s ease-out infinite; }
.lv-offline { flex:none; display:inline-flex; align-items:center; gap:8px;
    padding:8px 13px; border-radius:11px; background:rgba(67,160,74,.10);
    border:0.5px solid rgba(67,160,74,.22); color:#2f8a3c; font-size:12px;
    font-weight:600; white-space:nowrap; }
.lv-offline svg { width:16px; height:16px; fill:#2f8a3c; }
.lv-status { display:flex; align-items:center; gap:10px; padding:11px 16px;
    border-radius:13px; background:rgba(67,160,74,.08);
    border:0.5px solid rgba(67,160,74,.2); margin:0.3rem 0 0.7rem; }
.lv-status .d { position:relative; width:8px; height:8px; flex:none; }
.lv-status .d::before, .lv-status .d::after { content:""; position:absolute;
    inset:0; border-radius:50%; background:#43a04a; }
.lv-status .d::before { animation:anp-pulse 2s ease-out infinite; }
.lv-status .t { font-size:13.5px; font-weight:600; color:#2f8a3c; }
.lv-status .snap { font-family:'IBM Plex Mono',monospace; font-size:12px;
    color:#6b7280; }
.lv-status .virt { margin-left:auto; display:inline-flex; align-items:center;
    gap:6px; font-size:12px; color:#6b7280; }
.lv-status .virt svg { width:15px; height:15px; fill:#dc3a34; }
/* carte niveau instantané */
.lv-niveau-head { display:flex; align-items:center; justify-content:space-between;
    margin-bottom:10px; }
.lv-niveau-head .lab { font-size:11px; font-weight:600; text-transform:uppercase;
    letter-spacing:.05em; color:#8a9099; }
.lv-pill-gray { display:inline-flex; align-items:center; padding:3px 9px;
    border-radius:999px; background:rgba(120,128,140,.12); color:#6b7280;
    font-size:10.5px; font-weight:600; }
.lv-niveau-val { display:flex; align-items:baseline; gap:7px;
    font-family:'IBM Plex Mono',monospace; font-variant-numeric:tabular-nums; }
.lv-niveau-val .n { font-size:48px; font-weight:500; line-height:.9;
    letter-spacing:-.03em; color:#1b1e25; }
.lv-niveau-val .u { font-size:18px; font-weight:500; color:#8a9099; }
.lv-coord { display:flex; align-items:center; gap:7px; margin-top:13px;
    padding-top:13px; border-top:0.5px solid rgba(60,60,67,.1);
    font-family:'IBM Plex Mono',monospace; font-size:12px; color:#6b7280;
    font-variant-numeric:tabular-nums; }
.lv-coord svg { width:15px; height:15px; fill:#dc3a34; flex:none; }
/* table vols contributeurs */
.vols-title { font-size:11px; font-weight:600; text-transform:uppercase;
    letter-spacing:.05em; color:#8a9099; }
.vols-head { display:grid; grid-template-columns:1.3fr 1fr 0.9fr; gap:4px 8px;
    margin-top:12px; }
.vols-head span { font-size:9.5px; font-weight:600; text-transform:uppercase;
    letter-spacing:.04em; color:#a3a8b0; }
.vols-head .r { text-align:right; }
.vols-row { display:grid; grid-template-columns:1.3fr 1fr 0.9fr; gap:8px;
    align-items:center; padding:9px 0; border-top:0.5px solid rgba(60,60,67,.08); }
.vols-row .cs { display:flex; align-items:center; gap:7px;
    font-family:'IBM Plex Mono',monospace; font-size:13px; font-weight:500;
    color:#1b1e25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.vols-row .cs .sim { width:7px; height:7px; border-radius:50%; background:#fff;
    border:1.5px dashed #dc3a34; box-sizing:border-box; flex:none; }
.vols-row .dn { text-align:right; font-family:'IBM Plex Mono',monospace;
    font-size:12px; color:#6b7280; font-variant-numeric:tabular-nums;
    line-height:1.3; }
.vols-row .dn b { color:#1b1e25; font-weight:500; }
.phase-badge { justify-self:end; display:inline-flex; align-items:center; gap:4px;
    padding:4px 9px; border-radius:999px; font-size:10.5px; font-weight:600;
    white-space:nowrap; }
.phase-badge svg { width:13px; height:13px; }
.lv-note { display:flex; gap:10px; padding:13px 15px; border-radius:14px;
    background:rgba(243,196,26,.1); border:0.5px solid rgba(243,196,26,.28);
    margin-top:0.3rem; }
.lv-note svg { width:19px; height:19px; fill:#c99700; flex:none; }
.lv-note span { font-size:12px; line-height:1.5; color:#7a6310; }
</style>
"""


# CSS scopé à l'onglet « Exports » (classes exp-* / lic-*), fidèle à la maquette.
_CSS_EXPORT = """
<style>
.exp-sub-code { font-family:'IBM Plex Mono',monospace; font-size:12.5px;
    color:#dc3a34; background:rgba(220,58,52,.08); padding:1px 6px;
    border-radius:6px; }
.exp-sess-lab { font-size:11px; font-weight:600; text-transform:uppercase;
    letter-spacing:.06em; color:#8a9099; }
.exp-chips { display:flex; gap:8px; flex-wrap:wrap; margin-top:9px; }
.exp-chip { display:inline-flex; align-items:center; gap:6px; padding:5px 11px;
    border-radius:999px; background:rgba(120,128,140,.1); font-size:12px;
    font-weight:600; color:#3a3a3c; }
.exp-chip svg { width:15px; height:15px; fill:#6b7280; }
.exp-chip .m { font-family:'IBM Plex Mono',monospace; }
.exp-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px;
    margin-top:14px; }
.exp-card { padding:16px; background:#fff; border:0.5px solid rgba(60,60,67,.12);
    border-radius:14px; box-shadow:0 1px 2px rgba(16,24,40,.04); display:flex;
    flex-direction:column; gap:11px; min-height:150px;
    transition:transform .16s ease, box-shadow .16s ease; }
.exp-card:hover { transform:translateY(-3px);
    box-shadow:0 1px 2px rgba(16,24,40,.05), 0 14px 30px rgba(16,24,40,.10); }
.exp-card .top { display:flex; align-items:center; justify-content:space-between; }
.exp-ico { width:40px; height:40px; border-radius:11px; display:flex;
    align-items:center; justify-content:center; }
.exp-ico svg { width:22px; height:22px; }
.exp-ext { font-family:'IBM Plex Mono',monospace; font-size:11px; font-weight:600;
    letter-spacing:.04em; text-transform:uppercase; padding:3px 8px;
    border-radius:7px; }
.exp-name { font-family:'IBM Plex Mono',monospace; font-size:14.5px;
    font-weight:500; color:#1b1e25; }
.exp-desc { font-size:11.5px; line-height:1.45; color:#6b7280; margin-top:5px; }
.exp-foot { display:flex; align-items:center; justify-content:space-between;
    margin-top:auto; padding-top:9px; border-top:0.5px solid rgba(60,60,67,.08); }
.exp-size { font-family:'IBM Plex Mono',monospace; font-size:11px; color:#a3a8b0; }
.exp-dl { display:inline-flex; align-items:center; gap:6px; padding:6px 11px;
    border-radius:9px; background:rgba(120,128,140,.1); color:#3a3a3c;
    font-size:12px; font-weight:600; }
.exp-dl svg { width:15px; height:15px; fill:#3a3a3c; }
.exp-hint { display:flex; align-items:center; gap:10px; margin-top:14px;
    padding:12px 15px; border-radius:13px; background:rgba(220,58,52,.05);
    border:0.5px solid rgba(220,58,52,.16); }
.exp-hint svg { width:18px; height:18px; fill:#dc3a34; flex:none; }
.exp-hint span { font-size:12.5px; color:#6b7280; }
.exp-hint b { color:#3a3a3c; }
/* licence + citation */
.lic-grid { display:grid; grid-template-columns:1fr 1.3fr; gap:14px;
    margin-top:16px; }
.lic-card { padding:18px 20px; background:rgba(255,255,255,.6);
    -webkit-backdrop-filter:blur(20px) saturate(160%);
    backdrop-filter:blur(20px) saturate(160%);
    border:0.5px solid rgba(255,255,255,.7); border-radius:16px;
    box-shadow:0 1px 2px rgba(16,24,40,.04), 0 6px 20px rgba(16,24,40,.05); }
.lic-head { display:flex; align-items:center; gap:8px; margin-bottom:11px; }
.lic-head svg { width:18px; height:18px; fill:#6b7280; }
.lic-head .t { font-size:11px; font-weight:600; text-transform:uppercase;
    letter-spacing:.06em; color:#8a9099; }
.lic-card p { margin:0; font-size:13px; line-height:1.55; color:#3a3a3c; }
.code-green { font-family:'IBM Plex Mono',monospace; font-size:12px;
    color:#2f8a3c; background:rgba(67,160,74,.1); padding:1px 6px;
    border-radius:6px; }
</style>
"""


def _carte_html(label, valeur, unite="", sous="", accent="#1b1e25", badge="",
                mono=True, icone=""):
    """HTML d'une carte de mesure : intitulé (icône optionnelle), grande valeur
    + unité, pastille optionnelle (alignée à droite dans la ligne de valeur),
    sous-texte optionnel. mono=False pour une valeur textuelle (mot) en Sans."""
    classe = "valeur" if mono else "valeur valeur--texte"
    sous_html = f'<div class="sous">{sous}</div>' if sous else ""
    return (f'<div class="carte-metrique">'
            f'<div class="label">{icone}{label}</div>'
            f'<div class="{classe}" style="color:{accent}">{valeur}'
            f'<span class="unite">{unite}</span>{badge}</div>'
            f'{sous_html}</div>')


def rendre_cartes(cartes):
    """Affiche une rangée de cartes de mesures. Chaque élément est soit un dict
    (passé à _carte_html), soit une chaîne HTML déjà construite (ex. la carte
    d'exposition à barre segmentée)."""
    cols = max(len(cartes), 1)
    inner = "".join(c if isinstance(c, str) else _carte_html(**c)
                    for c in cartes)
    st.markdown(
        f'<div class="cartes-metriques" '
        f'style="grid-template-columns:repeat({cols},minmax(0,1fr))">'
        f'{inner}</div>',
        unsafe_allow_html=True,
    )


# Échelle d'exposition à 3 crans de la maquette (Faible / Modérée / Élevée) :
# (couleur pleine du segment, couleur du libellé actif).
_EXPO_SEGMENTS = [("Faible", "#43a04a"), ("Modérée", "#ef8b2e"),
                  ("Élevée", "#dc3a34")]

# Pastille inline de la carte « Niveau Lden » : (fond teinté, texte assombri)
# par classe — texte foncé pour rester lisible sur le fond à 14 % d'opacité.
_BADGE_EXPO = {
    "Faible":      ("rgba(67,160,74,.14)",  "#2f7a37"),
    "Modérée":     ("rgba(239,139,46,.14)", "#c46a16"),
    "Élevée":      ("rgba(220,58,52,.14)",  "#b32d28"),
    "Très élevée": ("rgba(220,58,52,.14)",  "#b32d28"),
}


def _classe_exposition(lden):
    """(mot, couleur, sous-texte) décrivant la classe d'exposition Lden."""
    if lden < 55:
        return "Faible", "#43a04a", "Sous le seuil d'information (55 dB)"
    if lden < 65:
        return "Modérée", "#ef8b2e", "Entre information (55) et isolation (65)"
    if lden < 75:
        return "Élevée", "#dc3a34", "Au-delà du seuil d'isolation (65 dB)"
    return "Très élevée", "#c81e1e", "Exposition très forte, atténuation requise"


def _carte_exposition(lden):
    """Carte « Classe d'exposition » fidèle à la maquette : grand mot coloré +
    barre à 3 segments (Faible/Modérée/Élevée), le cran courant mis en avant."""
    classe, couleur, _ = _classe_exposition(lden)
    # cran courant : 0 Faible, 1 Modérée, 2 Élevée (« Très élevée » → Élevée)
    actif = 0 if lden < 55 else (1 if lden < 65 else 2)
    segs = ""
    for i, (_, coul) in enumerate(_EXPO_SEGMENTS):
        # segment atteint = couleur pleine ; au-delà = rouge très atténué
        fond = coul if i <= actif else "rgba(220,58,52,.18)"
        segs += f'<span style="background:{fond}"></span>'
    labels = "".join(
        f'<span class="{"on" if i == actif else ""}"'
        f'{f" style=color:{couleur}" if i == actif else ""}>{mot}</span>'
        for i, (mot, _) in enumerate(_EXPO_SEGMENTS))
    return (f'<div class="carte-metrique">'
            f'<div class="label">{_ico("expo", "#ef8b2e")}'
            f"Classe d'exposition</div>"
            f'<div class="classe-val" style="color:{couleur}">{classe}</div>'
            f'<div class="expo-bar">{segs}</div>'
            f'<div class="expo-labels">{labels}</div></div>')


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

def generer_frames_animation_gif(calc, grid, grid_size):
    """
    Génère les images de l'animation GIF 24 h.

    Chaque frame représente le bruit cumulé jusqu'à une heure donnée.
    On réutilise la même logique que l'onglet "Journée 24h", mais au lieu
    d'afficher la figure avec st.pyplot(), on la convertit en image numpy
    pour pouvoir créer un GIF avec ResultsExporter.
    """

    import matplotlib.pyplot as plt

    vols = charger_vols()
    heures_animation = [0, 6, 8, 12, 18, 23]
    frames = []

    for heure in heures_animation:
        vols_jusqua = [
            v for v in vols
            if calc._utc_hour(v.waypoints[0]["time"]) <= heure
        ]

        if not vols_jusqua:
            continue

        lden_h = calc.compute_grid(vols_jusqua, grid)

        titre = (
            f"Bruit accumulé de 0h00 à {heure}h59 — "
            f"{len(vols_jusqua)} vols"
        )

        if CONTOUR_DISPONIBLE:
            fig, _ = NoiseContour(calc, grid_size=grid_size).plot(
                lden_h,
                title=titre,
                basemap=False,
            )
        else:
            surf = lden_h.reshape(grid_size, grid_size)

            fig, ax = plt.subplots(figsize=(7, 6))

            im = ax.imshow(
                surf,
                origin="lower",
                cmap="inferno",
                vmin=40,
                vmax=max(float(lden_h.max()), 41),
                extent=(
                    grid[:, 1].min(),
                    grid[:, 1].max(),
                    grid[:, 0].min(),
                    grid[:, 0].max(),
                ),
                aspect="auto",
            )

            fig.colorbar(im, ax=ax, label="Lden dB(A)", shrink=0.8)
            ax.plot(YUL[1], YUL[0], "w*", markersize=12)
            ax.set_title(titre)

        fig.canvas.draw()

        frame = np.asarray(fig.canvas.buffer_rgba())
        frames.append(frame[:, :, :3].copy())

        plt.close(fig)

    return frames


def carte_plein_ecran(carte, cle, *, hauteur=780, hauteur_plein=1000,
                      returned_objects=None):
    """Affiche une carte folium avec un bouton « Plein écran » / « Revenir ».

    `cle` est un identifiant unique de la carte (ex. "chez_vous", "live") :
    il sert à la fois aux clés des widgets Streamlit et aux sélecteurs CSS.

    En mode plein écran, le conteneur de la carte est fixé sur toute la
    fenêtre du navigateur et la carte est agrandie (`hauteur_plein`). Un
    bouton flottant en haut à droite rétablit la vue normale. L'état est
    mémorisé dans st.session_state pour survivre aux reruns.

    Renvoie le dictionnaire produit par st_folium (clics, etc.), comme un
    appel direct à st_folium.
    """
    etat = f"plein_ecran_{cle}"
    st.session_state.setdefault(etat, False)
    actif = st.session_state[etat]

    # Bouton bascule, isolé dans un conteneur identifiable pour pouvoir le
    # faire flotter au-dessus de la carte en CSS lorsqu'on est en plein écran.
    with st.container(key=f"barre_carte_{cle}"):
        if actif:
            if st.button("Revenir", icon=":material/fullscreen_exit:",
                         key=f"btn_quitter_{cle}"):
                st.session_state[etat] = False
                st.rerun()
        else:
            if st.button("Plein écran", icon=":material/fullscreen:",
                         key=f"btn_plein_{cle}"):
                st.session_state[etat] = True
                st.rerun()

    # En plein écran : on fixe le conteneur de la carte sur toute la fenêtre,
    # on masque le reste de l'interface (en-tête + barre latérale) et on garde
    # le bouton « Revenir » au-dessus de la carte.
    if actif:
        st.markdown(
            f"""
            <style>
            .st-key-conteneur_carte_{cle} {{
                position: fixed; inset: 0; z-index: 9990;
                background: #fff; padding: 0 !important; margin: 0;
                overflow: hidden;
            }}
            .st-key-barre_carte_{cle} {{
                position: fixed; top: 14px; right: 22px; z-index: 10000;
                width: auto !important;
            }}
            header[data-testid="stHeader"],
            section[data-testid="stSidebar"] {{ display: none !important; }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    # La carte Leaflet ne se redimensionne pas via le seul CSS de l'iframe :
    # on passe donc une hauteur concrète plus grande en plein écran.
    with st.container(key=f"conteneur_carte_{cle}"):
        return st_folium(
            carte,
            height=hauteur_plein if actif else hauteur,
            use_container_width=True,
            returned_objects=returned_objects,
            key=f"stfolium_{cle}",
        )

# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

# En-tête héros : bandeau dégradé pleine largeur (surtitre + titre + badges)
# avec le bouton « Partager » intégré en haut à droite, comme la maquette. Les
# badges reprennent les références techniques. Icône partage en SVG inline
# (hors-ligne, pas de police d'icônes externe).
st.markdown(
    """
    <div class="hero">
      <div class="hero-row">
        <div>
          <div class="overline">MGA802 · ÉTS · Été 2026</div>
          <h1>Le bruit des avions autour de YUL</h1>
          <div class="badges">
            <span class="badge-hero">ECAC Doc 29</span>
            <span class="badge-hero">ADS-B OpenSky</span>
            <span class="badge-hero">EASA ANP v9</span>
          </div>
        </div>
        <a class="hero-share"
           href="https://github.com/kevin-noah/equipe4-airnoisepy-20262"
           target="_blank" rel="noopener">
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 7.81C7.5 7.31 6.79 7 6 7c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/>
          </svg>
          Partager
        </a>
      </div>
    </div>
    """,
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

st.sidebar.markdown('<div class="reglages-label">Réglages</div>',
                    unsafe_allow_html=True)

# Slider de résolution façon maquette : on place le label + la valeur sur une
# même ligne (via un emplacement rempli APRÈS lecture de la valeur), la piste
# pleine largeur (label du widget masqué), puis trois légendes sous la piste.
_ph_grid = st.sidebar.empty()
grid_size = st.sidebar.select_slider(
    "Résolution de la grille",
    options=[40, 60, 80],
    value=60,
    format_func=lambda n: f"{n}×{n}",
    label_visibility="collapsed",
)
_ph_grid.markdown(
    f'<div class="grid-row"><span class="grid-lab">Résolution de grille</span>'
    f'<span class="grid-val">{grid_size} × {grid_size}</span></div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    '<div class="grid-ends"><span>40×40</span><span>fine</span>'
    '<span>80×80</span></div>',
    unsafe_allow_html=True,
)

curfew_actif = st.sidebar.toggle(
    "Couvre-feu 23 h – 7 h",
    value=False,
)

st.sidebar.markdown(
    """
    <div class="seuils-titre" style="margin-top:1.1rem;">Seuils réglementaires</div>
    <div class="seuil-carte">
      <span class="seuil-dot" style="background:#f3c41a;
            box-shadow:0 0 0 4px rgba(243,196,26,.18)"></span>
      <div>
        <div class="seuil-titre">55<span class="u">dB</span></div>
        <div class="seuil-desc">Information aux riverains — signalement
        recommandé au-delà du seuil.</div>
      </div>
    </div>
    <div class="seuil-carte">
      <span class="seuil-dot" style="background:#dc3a34;
            box-shadow:0 0 0 4px rgba(220,58,52,.20)"></span>
      <div>
        <div class="seuil-titre">65<span class="u">dB</span></div>
        <div class="seuil-desc">Éligibilité à l'isolation acoustique du bâti
        (programme insonorisation).</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if not CONTOUR_DISPONIBLE:
    st.sidebar.caption(
        "⏳ NoiseContour en cours d'intégration : surface Lden affichée "
        "en attendant les contours isophoniques."
    )

# Pied de la barre latérale (maquette) : provenance du modèle, séparé par un
# mince filet, en bas du ruban.
st.sidebar.markdown(
    """
    <div style="margin-top:1.2rem; padding-top:0.9rem;
                border-top:0.5px solid rgba(255,255,255,0.10);
                font-size:10px; line-height:1.5;
                color:rgba(238,241,245,0.42);">
      Modèle de propagation ECAC Doc 29 · trajectoires ADS-B.
    </div>
    """,
    unsafe_allow_html=True,
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

# Vue active = élément choisi dans la navigation latérale (NAV). Chaque bloc
# ci-dessous ne s'affiche que si sa vue est sélectionnée — un seul rendu à la
# fois, comme un routeur de pages.
if vue == NAV[0]:
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

    # Conteneur réservé AU-DESSUS de la carte (comme la maquette) : on le
    # déclare ici, mais on le remplit plus bas, une fois le clic de la carte
    # traité. Streamlit autorise cette écriture différée → les cartes de
    # résultat s'affichent au-dessus tout en reflétant le dernier clic.
    zone_resultats = st.container()

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

    resultat_carte = carte_plein_ecran(
        carte,
        "chez_vous",
        hauteur=780,
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

    # On remplit maintenant le conteneur réservé plus haut : tout ce bloc
    # s'affiche AU-DESSUS de la carte, mais utilise le point fraîchement mis à
    # jour par le clic ci-dessus.
    with zone_resultats:
        st.markdown(
            "<div class='section-label'>Résultat du point choisi</div>",
            unsafe_allow_html=True)

        pt_chez_vous = st.session_state.get("pt_chez_vous")
        if pt_chez_vous is not None:
            lat, lon, source_pt = pt_chez_vous

            # Lden réel à ce point : agrégation de tous les survols du jour.
            recepteur = (lat, lon)
            vols = charger_vols()
            lden_point = calc.compute_lden(
                vols, recepteur, datetime.date(2026, 6, 10))
            distance_km = _haversine_m(YUL[0], YUL[1], lat, lon) / 1000

            # SEL de chaque survol : repère « plus bruyant » + compte des
            # vols qui contribuent réellement (SEL >= 45 dB(A)) à ce point.
            sels = [calc.compute_sel(v, recepteur) for v in vols]
            sel_max = max(sels)
            contributeurs = sum(1 for s in sels if s >= 45)

            # Pastille inline de la carte Lden = classe d'exposition, teintée.
            classe, couleur, _classe_sous = _classe_exposition(lden_point)
            bg_b, txt_b = _BADGE_EXPO.get(
                classe, ("rgba(220,58,52,.14)", "#b32d28"))
            badge_lden = (f'<span class="carte-badge" style="background:{bg_b};'
                          f'color:{txt_b}">{classe}</span>')

            rendre_cartes([
                {"label": "Niveau Lden", "valeur": f"{lden_point:.0f}",
                 "unite": "dB", "badge": badge_lden,
                 "icone": _ico("lden", "#dc3a34"),
                 "sous": "Indicateur jour-soir-nuit (24 h)"},
                _carte_exposition(lden_point),
                {"label": "Distance à YUL", "valeur": f"{distance_km:.1f}",
                 "unite": "km", "sous": "À vol d'oiseau du centre de YUL",
                 "icone": _ico("distance", "#6b7280")},
                {"label": "Vols contributeurs", "valeur": f"{contributeurs}",
                 "sous": f"sur ~{n_vols} mouvements / jour",
                 "icone": _ico("vols", "#6b7280")},
            ])

            st.caption(
                f"{comparaison_parlante(lden_point)}  \n"
                f"Survol le plus bruyant de la journée : "
                f"SEL {sel_max:.1f} dB(A) — "
                f"{source_pt} (latitude {lat:.5f}, longitude {lon:.5f})"
            )

        else:
            st.info("Saisissez votre adresse ou cliquez sur la carte pour "
                    "estimer le bruit à un point donné.")

if vue == NAV[1]:
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


if vue == NAV[2]:
    st.markdown(_CSS_LIVE, unsafe_allow_html=True)

    # En-tête : titre + pastille LIVE pulsante à gauche, pastille « hors-ligne »
    # verte à droite, puis sous-titre — fidèle à la maquette.
    st.markdown(
        f"""
        <div class="lv-head">
          <div>
            <div class="lv-titrow">
              <h2>Avions en direct</h2>
              <span class="badge-live"><span class="d"></span>LIVE</span>
            </div>
            <p class="lv-sub">Actualisez la position des avions, puis cliquez
            sur la carte ou saisissez votre adresse : le niveau instantané
            estimé au point choisi est comparable à la lecture d'un sonomètre
            ADM sur WebTrak au même moment.</p>
          </div>
          <span class="lv-offline">{_ico("cloud_off", "#2f8a3c")}Hors-ligne
          — sauf actualisation OpenSky</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Récupération à la demande (bouton) : on ne contacte JAMAIS OpenSky
    # au chargement de la page, et tout échec réseau est rattrapé pour ne
    # pas casser la démo en salle.
    # ------------------------------------------------------------------

    # Toolbar (maquette) : Actualiser · adresse · Localiser · Avion virtuel.
    # Une seule rangée alignée en bas ; l'avion virtuel passe dans un popover
    # (clic = panneau déroulant) pour rester fidèle au bouton en pointillés.
    col_act, col_adr_live, col_btn_live, col_virt = st.columns(
        [2.1, 4.4, 1.5, 1.8], vertical_alignment="bottom")

    with col_act:
        if st.button("Actualiser les avions", icon=":material/sync:",
                     key="btn_actualiser_live", use_container_width=True):
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
    with col_adr_live:
        adresse_live = st.text_input(
            "Votre adresse",
            placeholder="ex. 975 boulevard de la Côte-Vertu, Saint-Laurent",
            key="adr_live", label_visibility="collapsed",
        )
    with col_btn_live:
        localiser_live = st.button("Localiser", icon=":material/my_location:",
                                   key="btn_adr_live", type="primary",
                                   use_container_width=True)

    # ------------------------------------------------------------------
    # Avion virtuel (popover) : l'utilisateur place un appareil fictif
    # (position, altitude, phase) pour voir son effet sonore COMBINÉ aux
    # avions réels. Stockés dans st.session_state['avions_virtuels'], ils
    # passent par le même modèle (niveau_instantane) → l'onglet reste
    # démontrable MÊME sans OpenSky (hors-ligne).
    # ------------------------------------------------------------------
    pt_live_defaut = st.session_state.get("pt_live")
    lat_defaut = pt_live_defaut[0] if pt_live_defaut else YUL[0]
    lon_defaut = pt_live_defaut[1] if pt_live_defaut else YUL[1]

    with col_virt:
        pop_virt = st.popover("Avion virtuel", icon=":material/add_circle:",
                              use_container_width=True)

    if localiser_live:
        geo_live = geocoder_adresse(adresse_live)
        if geo_live is not None:
            st.session_state["pt_live"] = (geo_live[0], geo_live[1],
                                           geo_live[2])
        else:
            st.warning("Adresse introuvable (ou réseau injoignable). "
                       "Réessayez ou cliquez directement sur la carte.")

    with pop_virt:
        st.caption(
            "Placez un avion fictif (type A320) et observez son effet sur le "
            "niveau au point choisi, additionné aux avions réels. Position "
            "par défaut : au-dessus de votre point."
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

    # Bandeau de statut vert (maquette) : nb d'avions réels + heure du snapshot
    # à gauche, compteur d'avions virtuels à droite.
    n_virt = len(avions_virtuels)
    virt_html = (
        f'<span class="virt">{_ico("vols", "#dc3a34")}{n_virt} avion'
        f'{"s" if n_virt > 1 else ""} virtuel{"s" if n_virt > 1 else ""}</span>'
        if n_virt else "")
    if avions is not None:
        st.markdown(
            f'<div class="lv-status"><span class="d"></span>'
            f'<span class="t">{len(en_vol_reels)} avions réels en vol autour '
            f'de YUL</span>'
            f'<span class="snap">snapshot · '
            f'{st.session_state["avions_live_heure"]}</span>{virt_html}</div>',
            unsafe_allow_html=True)
    elif avions_virtuels:
        st.markdown(
            f'<div class="lv-status"><span class="d"></span>'
            f'<span class="t">{n_virt} avion(s) virtuel(s) — mode hors-ligne'
            f'</span><span class="snap">OpenSky non sollicité — actualisez '
            f'pour les réels</span></div>',
            unsafe_allow_html=True)

    if en_vol:
        col_live_carte, col_live_info = st.columns([1.55, 1])

        with col_live_carte:
            # Carte des avions avec marqueurs façon maquette : pastille ardoise
            # (avion réel) ou cercle blanc à liseré rouge pointillé (virtuel),
            # avion orienté selon son cap. Anneau pointillé autour de YUL.
            m = folium.Map(location=YUL, zoom_start=10)
            # anneau de portée autour de l'aéroport
            folium.Circle(YUL, radius=8000, color="#dc3a34", weight=1.5,
                          opacity=0.35, dash_array="5,5", fill=False).add_to(m)
            for a in en_vol:
                vr = a.get("vertical_rate") or 0.0
                etat = "↗ monte" if vr > 2 else ("↘ descend" if vr < -2
                                                 else "→ palier")
                est_virtuel = a.get("virtuel")
                cap = (a.get("track") or a.get("true_track")
                       or a.get("heading") or 0)
                bg = "#ffffff" if est_virtuel else "#16191f"
                bord = ("2px dashed #dc3a34" if est_virtuel
                        else "2.5px solid #ffffff")
                plane_col = "#dc3a34" if est_virtuel else "#ffffff"
                html_plane = (
                    f'<div style="width:30px;height:30px;border-radius:50%;'
                    f'background:{bg};border:{bord};box-sizing:border-box;'
                    f'display:flex;align-items:center;justify-content:center;'
                    f'box-shadow:0 2px 5px rgba(0,0,0,.3)">'
                    f'<svg viewBox="0 0 24 24" width="15" height="15" '
                    f'fill="{plane_col}" style="transform:rotate({cap}deg)">'
                    f'<path d="{_ICONES_CARTE["vols"]}"/></svg></div>')
                folium.Marker(
                    (a["lat"], a["lon"]),
                    tooltip=(("VIRTUEL · " if est_virtuel else "")
                             + f"{a['callsign'] or a['icao24']} — "
                             f"{(a['alt_baro'] or 0):.0f} m {etat}"),
                    icon=folium.DivIcon(html=html_plane, icon_size=(30, 30),
                                        icon_anchor=(15, 15)),
                ).add_to(m)
            # capteurs ADM/WebTrak en petits cercles gris
            ajouter_capteurs_adm(m)
            # repère YUL : point sombre + étiquette
            folium.Marker(
                YUL, tooltip="Montréal-Trudeau (YUL)",
                icon=folium.DivIcon(
                    html='<div style="display:flex;align-items:center">'
                    '<span style="width:12px;height:12px;border-radius:50%;'
                    'background:#16191f;border:2px solid #fff"></span>'
                    '<span style="margin-left:4px;background:#16191f;color:#fff;'
                    "font:600 11px 'IBM Plex Mono',monospace;padding:2px 7px;"
                    'border-radius:5px">YUL</span></div>',
                    icon_size=(60, 16), icon_anchor=(6, 8))).add_to(m)
            # Marqueur sur le point choisi (adresse géocodée ou clic) : cible.
            pt_live_courant = st.session_state.get("pt_live")
            if pt_live_courant is not None:
                folium.Marker(
                    (pt_live_courant[0], pt_live_courant[1]),
                    tooltip="Votre point",
                    icon=folium.DivIcon(
                        html='<div style="width:24px;height:24px;'
                        'border-radius:50%;background:#dc3a34;'
                        'border:3px solid #fff;box-shadow:0 2px 6px '
                        'rgba(0,0,0,.35);display:flex;align-items:center;'
                        'justify-content:center"><span style="width:7px;'
                        'height:7px;border-radius:50%;background:#fff">'
                        '</span></div>',
                        icon_size=(24, 24), icon_anchor=(12, 12))).add_to(m)
            retour_live = carte_plein_ecran(m, "live", hauteur=470)

            # Légende (maquette) sous la carte.
            st.markdown(
                '<div style="display:flex;gap:18px;flex-wrap:wrap;'
                'font-size:12px;color:#6b7280;margin-top:6px">'
                '<span style="display:inline-flex;align-items:center;gap:7px">'
                '<span style="width:13px;height:13px;border-radius:50%;'
                'background:#16191f"></span>Avion réel</span>'
                '<span style="display:inline-flex;align-items:center;gap:7px">'
                '<span style="width:13px;height:13px;border-radius:50%;'
                'background:#fff;border:2px dashed #dc3a34;box-sizing:border-box">'
                '</span>Avion virtuel</span>'
                '<span style="display:inline-flex;align-items:center;gap:7px">'
                '<span style="width:11px;height:11px;border-radius:50%;'
                'background:#dc3a34"></span>Votre point</span></div>',
                unsafe_allow_html=True)

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

                # Carte « Niveau instantané estimé » (verre dépoli, maquette).
                niveau_html = (
                    f'<div class="carte-metrique" '
                    f'style="padding:20px 20px 18px">'
                    f'<div class="lv-niveau-head">'
                    f'<span class="lab">Niveau instantané estimé</span>'
                    f'<span class="lv-pill-gray">avions seulement</span></div>'
                    f'<div class="lv-niveau-val"><span class="n">{total:.1f}'
                    f'</span><span class="u">dB(A)</span></div>'
                    f'<div class="lv-coord">{_ico("cible", "#dc3a34")}'
                    f'{lat_live:.5f}, {lon_live:.5f}</div></div>')

                # Table « Vols contributeurs » avec badges de phase.
                virt_cs = {(a.get("callsign") or "").strip()
                           for a in avions_virtuels}
                lignes = ""
                for c in contribs[:6]:
                    cs = c["callsign"]
                    sim = '<span class="sim"></span>' if cs in virt_cs else ""
                    lignes += (
                        f'<div class="vols-row"><span class="cs">{sim}{cs}'
                        f'</span><span class="dn">{c["distance_m"] / 1000:.1f}'
                        f' km<br><b>{c["niveau_db"]:.1f} dB</b></span>'
                        f'{_phase_badge(c.get("phase"))}</div>')
                vols_html = (
                    f'<div class="carte-metrique" '
                    f'style="padding:16px 16px 8px">'
                    f'<span class="vols-title">Vols contributeurs</span>'
                    f'<div class="vols-head"><span>Indicatif</span>'
                    f'<span class="r">Dist · niveau</span>'
                    f'<span class="r">Phase</span></div>{lignes}</div>')

                note_html = (
                    f'<div class="lv-note">{_ico("info", "#c99700")}'
                    f'<span>Contribution des avions uniquement. Un sonomètre '
                    f'mesure aussi le bruit de fond urbain (~45–55 dB). '
                    f'Estimation L<sub>Amax</sub> dérivée des courbes SEL '
                    f'(−9 dB) ; comparable seulement pendant un survol.</span>'
                    f'</div>')

                st.markdown(
                    '<div style="display:flex;flex-direction:column;gap:14px">'
                    + niveau_html + vols_html + note_html + '</div>',
                    unsafe_allow_html=True)

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
                st.info("Saisissez votre adresse ou cliquez sur la carte "
                        "pour estimer le bruit instantané à cet endroit.")
    else:
        st.info("Cliquez sur **Actualiser les avions** (internet) ou ajoutez "
                "un **avion virtuel** pour estimer le bruit.")

if vue == NAV[3]:
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

if vue == NAV[4]:
    st.markdown(_CSS_EXPORT, unsafe_allow_html=True)

    # Titre + sous-titre (avec ResultsExporter en code teinté), fidèle maquette.
    st.markdown(
        """
        <div style="margin-bottom:2px">
          <h2 style="margin:0;font-size:20px;font-weight:600;
            letter-spacing:-.015em;color:#1b1e25">Export des résultats</h2>
          <p style="margin:9px 0 0;font-size:13.5px;line-height:1.55;
            color:#6b7280;max-width:760px">Partagez les résultats obtenus après
          calcul. La classe <span class="exp-sub-code">ResultsExporter</span>
          produit les exports complets du projet — grille Lden, carte
          interactive et animation 24 h.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # En-tête de la carte de session : intitulé + pastilles à gauche, bouton
    # « Générer les exports » à droite (vrai widget Streamlit).
    c_lab, c_btn = st.columns([3, 1.15], vertical_alignment="center")
    with c_lab:
        st.markdown(
            f"""
            <div><span class="exp-sess-lab">Exports de la session courante</span>
            <div class="exp-chips">
              <span class="exp-chip">{_ico("grid_on", "#6b7280")}
                <span class="m">{grid_size}×{grid_size}</span></span>
              <span class="exp-chip">{_ico("sun", "#6b7280")}Journée type</span>
              <span class="exp-chip">{_ico("vols", "#6b7280")}
                <span class="m">~{n_vols}</span> vols</span>
            </div></div>
            """,
            unsafe_allow_html=True,
        )
    with c_btn:
        generer = st.button("Générer les exports", type="primary",
                            icon=":material/download:",
                            use_container_width=True)

    # Trois cartes de fichiers (aperçu fidèle à la maquette).
    _fichiers = [
        ("table", "#2f8a3c", "rgba(67,160,74,.14)", "lden_grid", "csv",
         f"Grille Lden complète — une valeur par cellule "
         f"({grid_size}×{grid_size}).", "~412 Ko"),
        ("map", "#c46a16", "rgba(239,139,46,.14)", "carte", "html",
         "Carte isophonique interactive (Folium / Leaflet).", "~2.1 Mo"),
        ("movie", "#dc3a34", "rgba(220,58,52,.12)", "animation", "gif",
         "Animation 24 h — propagation heure par heure.", "~5.8 Mo"),
    ]
    _cartes = ""
    for ic, ec, eb, nom, ext, desc, taille in _fichiers:
        _cartes += (
            f'<div class="exp-card"><div class="top">'
            f'<span class="exp-ico" style="background:{eb}">{_ico(ic, ec)}</span>'
            f'<span class="exp-ext" style="color:{ec};background:{eb}">'
            f'.{ext}</span></div>'
            f'<div><div class="exp-name">{nom}.{ext}</div>'
            f'<div class="exp-desc">{desc}</div></div>'
            f'<div class="exp-foot"><span class="exp-size">{taille}</span>'
            f'<span class="exp-dl">{_ico("download", "#3a3a3c")}Télécharger'
            f'</span></div></div>')
    st.markdown(f'<div class="exp-grid">{_cartes}</div>',
                unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # Afin d'éviter que l'onglet Exports ne génère automatiquement
    # des fichiers au chargement de l'application, nous demandons
    # explicitement à l'utilisateur de lancer la démonstration.
    #
    # Cette approche améliore également la robustesse de l'application :
    # chaque onglet reste indépendant des autres.
    # ------------------------------------------------------------------

    if generer:

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

        st.success("Export généré avec succès.")

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

        # --------------------------------------------------------------
        # Export HTML : carte interactive Folium.
        #
        # On régénère la même carte de contours que dans l'onglet
        # "Le bruit chez vous", puis on la sauvegarde en HTML pour que
        # l'utilisateur puisse l'ouvrir dans un navigateur sans Streamlit.
        # --------------------------------------------------------------

        try:
            carte_export = (
                carte_contours(lden, grid_size, calc)
                if CONTOUR_DISPONIBLE
                else carte_heatmap(lden, grid, grid_size)
            )

            ajouter_capteurs_adm(carte_export)

            chemin_carte = os.path.join(RACINE, "results", "carte.html")
            os.makedirs(os.path.dirname(chemin_carte), exist_ok=True)

            carte_export.save(chemin_carte)

            with open(chemin_carte, "rb") as fichier_html:
                contenu_html = fichier_html.read()

            st.download_button(
                label="🗺️ Télécharger carte.html",
                data=contenu_html,
                file_name="carte.html",
                mime="text/html",
            )

        except Exception as exc:
            st.warning(f"La carte HTML n'a pas pu être générée : {exc}")

        # --------------------------------------------------------------
        # Export GIF : animation 24 h.
        #
        # On génère plusieurs images représentant l'accumulation du bruit
        # au fil de la journée, puis ResultsExporter les assemble en GIF.
        # --------------------------------------------------------------

        try:
            exporter = ResultsExporter(output_dir=os.path.join(RACINE, "results"))

            frames = generer_frames_animation_gif(calc, grid, grid_size)

            chemin_gif = exporter.export_animation_gif(
                frames,
                output_path=os.path.join(RACINE, "results", "animation.gif"),
                fps=1,
            )

            with open(chemin_gif, "rb") as fichier_gif:
                contenu_gif = fichier_gif.read()

            st.download_button(
                label="🎞️ Télécharger animation.gif",
                data=contenu_gif,
                file_name="animation.gif",
                mime="image/gif",
            )

        except Exception as exc:
            st.warning(f"L'animation GIF n'a pas pu être générée : {exc}")
    else:
        st.markdown(
            f'<div class="exp-hint">{_ico("bolt", "#dc3a34")}'
            f'<span>Cliquez sur <b>Générer les exports</b> pour produire les '
            f'fichiers de la session courante.</span></div>',
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------
    # Pied de l'onglet : licence + citation (deux cartes verre dépoli),
    # fidèle à la maquette. Reste 100 % hors-ligne (aucune ressource externe).
    # ------------------------------------------------------------------
    st.markdown(
        f"""
        <div class="lic-grid">
          <div class="lic-card">
            <div class="lic-head">{_ico("balance", "#6b7280")}
              <span class="t">Licence</span></div>
            <p>Distribué sous licence <b>MIT</b>. Voir le fichier
            <span class="code-green">LICENSE.md</span> pour plus de détails.</p>
          </div>
          <div class="lic-card">
            <div class="lic-head">{_ico("quote", "#6b7280")}
              <span class="t">Citation</span></div>
            <p>Kevin, Bouchra, Syndia, Laura. <i>AirNoisePy: a Python tool for
            aircraft noise modelling around Montréal-Trudeau airport
            (ECAC Doc 29)</i>, MGA802, École de technologie supérieure,
            Montréal, 2026.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
