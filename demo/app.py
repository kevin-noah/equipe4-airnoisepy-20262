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
    # Modèle simplifié pour la démo Streamlit.
    #
    # L'objectif ici n'est pas de remplacer NoiseCalculator. Cette fonction
    # donne seulement un ordre de grandeur instantané pour l'onglet live.
    #
    # Hypothèses :
    #   - plus l'avion est proche du récepteur, plus il est bruyant ;
    #   - un avion en montée est plus bruyant qu'un avion en descente ;
    #   - les contributions sont combinées en énergie, pas en addition simple.
    # ------------------------------------------------------------------

    for avion in avions:
        lat = avion.get("lat")
        lon = avion.get("lon")

        if lat is None or lon is None:
            continue

        altitude_m = avion.get("alt_baro") or 1000.0
        vertical_rate = avion.get("vertical_rate") or 0.0

        distance_sol_m = _haversine_m(lat_rec, lon_rec, lat, lon)
        distance_3d_m = math.sqrt(distance_sol_m ** 2 + altitude_m ** 2)

        # --------------------------------------------------------------
        # Niveau de base simplifié.
        #
        # À 1 km, on part d'environ 75 dB(A), puis on applique une
        # décroissance logarithmique avec la distance. On limite la
        # distance minimale à 200 m pour éviter des valeurs irréalistes.
        # --------------------------------------------------------------

        distance_ref_m = max(distance_3d_m, 200.0)
        niveau_db = 75 - 20 * math.log10(distance_ref_m / 1000)

        # --------------------------------------------------------------
        # Correction très simplifiée selon la phase de vol.
        # Le taux vertical est utilisé comme proxy :
        #   > 1 m/s  : montée
        #   < -1 m/s : descente
        #   sinon    : palier
        # --------------------------------------------------------------

        if vertical_rate > 1:
            phase = "montée"
            niveau_db += 3
        elif vertical_rate < -1:
            phase = "descente"
            niveau_db -= 2
        else:
            phase = "palier"

        contributions.append(
            {
                "callsign": avion.get("callsign", "Inconnu"),
                "distance_m": distance_3d_m,
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

def carte_contours(contours, center=YUL, zoom=10):
    """Carte folium avec les polygones isophoniques (NoiseContour requis)."""
    pass  # TODO


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

tab_chez_vous, tab_anim, tab_live, tab_valid, tab_export = st.tabs([
    '🏠 Le bruit chez vous', '🕐 Journée 24h', '📡 Avions en direct',
    '✅ Validation WebTrak', '💾 Exports',
])

with tab_chez_vous:
    st.subheader("🏠 Le bruit chez vous")

    st.markdown(
        """
        Cette section permet d'estimer le niveau sonore autour de YUL
        à partir d'un point choisi sur la carte.

        Pour cette première version Streamlit, le niveau affiché est une
        estimation simplifiée basée sur la distance à l'aéroport. La version
        finale utilisera les résultats calculés par `NoiseCalculator`.
        """
    )

    # ------------------------------------------------------------------
    # Carte interactive centrée sur Montréal-Trudeau.
    #
    # Le cercle de 25 km correspond à la zone d'étude définie dans le
    # projet. L'utilisateur peut cliquer sur la carte pour choisir un
    # récepteur au sol.
    # ------------------------------------------------------------------

    carte = folium.Map(location=YUL, zoom_start=10)

    folium.Marker(
        location=YUL,
        popup="Aéroport Montréal-Trudeau (YUL)",
        tooltip="YUL",
    ).add_to(carte)

    folium.Circle(
        location=YUL,
        radius=25000,
        popup="Zone d'étude : 25 km",
        tooltip="Rayon de 25 km",
        fill=False,
    ).add_to(carte)

    resultat_carte = st_folium(carte, width=1100, height=550)

    # ------------------------------------------------------------------
    # Si l'utilisateur clique sur la carte, Streamlit-Folium retourne
    # les coordonnées du dernier point cliqué.
    #
    # On calcule ensuite une estimation simplifiée du Lden :
    # plus le point est éloigné de YUL, plus le niveau diminue.
    # Ce n'est pas encore le modèle scientifique final, mais cela permet
    # de tester l'interface et le parcours utilisateur.
    # ------------------------------------------------------------------

    if resultat_carte and resultat_carte.get("last_clicked"):
        lat = resultat_carte["last_clicked"]["lat"]
        lon = resultat_carte["last_clicked"]["lng"]

        distance_km = _haversine_m(YUL[0], YUL[1], lat, lon) / 1000

        lden_estime = max(35, 70 - 1.15 * distance_km)

        st.metric("Lden estimé", f"{lden_estime:.1f} dB")
        st.write(comparaison_parlante(lden_estime))

        if lden_estime >= 65:
            st.error("Seuil 65 dB dépassé : isolation acoustique recommandée.")
        elif lden_estime >= 55:
            st.warning("Seuil 55 dB dépassé : information des riverains.")
        else:
            st.success("Niveau inférieur aux principaux seuils réglementaires.")

    else:
        st.info("Cliquez sur la carte pour estimer le bruit à un point donné.")

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
