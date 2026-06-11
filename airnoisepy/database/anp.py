
#ANPDatabase — Base de courbes NPD (Noise-Power-Distance) Eurocontrol
#Auteure : Bouchra
#MGA 802 — ÉTS Montréal, Été 2026

import warnings
import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

class ANPDatabase:

    #Charge, nettoie et interroge la base de courbes NPD (Noise-Power-Distance)
    #d'Eurocontrol pour le calcul de bruit aérien selon ECAC Doc 29.

    #Format réel du fichier Eurocontrol (v9) :
    #Onglet   : NPD_Data
    #Colonnes : NPD_ID | Noise Metric | Op Mode | Power Setting |
                #L_200ft … L_25000ft
    #Op Mode  : 'A' (arrival) | 'D' (departure)
    #Distances: en PIEDS → converties en mètres à l'import
    #Thrust   : en lbs de poussée (pas en % N1)

    #Distances standard après conversion ft → m (arrondi) :
        #200ft→61m, 400ft→122m, 630ft→192m, 1000ft→305m, 2000ft→610m,
        #4000ft→1219m, 6300ft→1920m, 10000ft→3048m, 16000ft→4877m, 25000ft→7620m

    #Attributs publics
    #_data         : pd.DataFrame — données NPD nettoyées
    #source        : str          — 'eurocontrol' | 'synthetic'
    #distances     : list[float]  — distances en mètres après conversion
    #thrust_levels : list[float]  — niveaux de poussée disponibles (lbs)

    # Colonnes de distance du fichier Eurocontrol (en pieds) → valeurs en mètres
    FT_COLS = [
        "L_200ft", "L_400ft", "L_630ft", "L_1000ft", "L_2000ft",
        "L_4000ft", "L_6300ft", "L_10000ft", "L_16000ft", "L_25000ft",
    ]
    # Distances converties en mètres (arrondi à l'entier)
    DISTANCES_M = [round(float(c.replace("L_", "").replace("ft", "")) * 0.3048)
                   for c in FT_COLS]

    # Niveaux de poussée de la table synthétique A320 (lbs, approx CFMI CFM56-5B)
    # Correspondance indicative % N1 → lbs :
    #   68% N1 ≈  4 500 lbs  (approche)
    #   74% N1 ≈  9 000 lbs
    #   80% N1 ≈ 13 000 lbs
    #   86% N1 ≈ 18 000 lbs
    #   94% N1 ≈ 23 000 lbs  (décollage)
    SYNTHETIC_THRUST_LBS = [4500.0, 9000.0, 13000.0, 18000.0, 23000.0]

    # Mapping NPD_ID Eurocontrol → codes OACI courts
    NPD_ID_MAP = {
        "747400rn":   "B744",
        "7879":       "B789",
        "7673er":     "B763",
        "7773er":     "B773",
        "a320-250n":  "A320",
        "a320-270n":  "A320",
        "a321-270n":  "A321",
        "a330-743l":  "A333",
        "a330-941":   "A339",
        "a350-1041":  "A35K",
        "erj190-300": "E290",
        "erj190-400": "E295",
        "fal900ex":   "FA7X",
        "g650er":     "GLEX",
    }

    def __init__(self, filepath=None):
        #Initialise la base ANP.
        #Paramètre
        #filepath : str | None
            #Chemin vers le fichier Excel ANP Eurocontrol (onglet NPD_Data).
            #Si None, charge la table synthétique A320.
        self.distances = list(self.DISTANCES_M)
        self.thrust_levels = list(self.SYNTHETIC_THRUST_LBS)
        self._data = None
        self._interpolators = {}

        if filepath is not None:
            self.source = "eurocontrol"
            self.load_excel(filepath)
        else:
            self.source = "synthetic"
            self.load_synthetic()

    # ------------------------------------------------------------------ #
    #  Chargement des données                                              #
    # ------------------------------------------------------------------ #

    def load_excel(self, filepath):
        #Charge le fichier Excel ANP Eurocontrol (onglet NPD_Data).

        #Format attendu :
            #NPD_ID | Noise Metric | Op Mode | Power Setting |L_200ft | L_400ft | … | L_25000ft

        #Les distances en pieds sont converties en mètres.
        #Op Mode 'A'/'D' est converti en 'arrival'/'departure'.

        #Paramètre
        #filepath : str
        try:
            df = pd.read_excel(filepath, sheet_name="NPD_Data")
        except Exception as exc:
            raise FileNotFoundError(
                f"Impossible de lire le fichier ANP : {filepath}\n{exc}"
            ) from exc

        df = self._clean_data(df)
        self._validate_monotonicity(df)
        self._data = df

        self.distances = list(self.DISTANCES_M)
        self.thrust_levels = sorted(df["thrust"].unique().tolist())
        self._build_interpolators()

    def load_synthetic(self):
        #Charge la table NPD synthétique A320 intégrée.
        #Modèle analytique basé sur les niveaux réels Eurocontrol A320 :
            #L(d) = L0 - 20·log10(d / 305) - 0.005·(d - 305) / 305
            #L0   = 84.8 + (thrust_lbs - 4500) / (23000 - 4500) * 10
            #(305m = 1000ft, distance de référence Eurocontrol)

        #Couvre departure et arrival, métrique SEL uniquement.
        #Thrust en lbs de poussée.

        records = []
        d_ref = 305.0   # 1000 ft en mètres
        l0_ref = 84.8   # niveau SEL à 1000ft / thrust minimal (approx A320)

        for op in ("departure", "arrival"):
            for thrust in self.SYNTHETIC_THRUST_LBS:
                l0 = l0_ref + (thrust - self.SYNTHETIC_THRUST_LBS[0]) / \
                     (self.SYNTHETIC_THRUST_LBS[-1] - self.SYNTHETIC_THRUST_LBS[0]) * 10.0
                row = {
                    "aircraft_id": "A320",
                    "operation":   op,
                    "metric":      "SEL",
                    "thrust":      thrust,
                }
                for d_m in self.DISTANCES_M:
                    level = (l0
                             - 20.0 * np.log10(d_m / d_ref)
                             - 0.005 * (d_m - d_ref) / d_ref)
                    row[f"{d_m}m"] = round(level, 1)
                records.append(row)

        self._data = pd.DataFrame(records)
        self._build_interpolators()

# ------------------------------------------------------------------
#  Nettoyage et validation                                             #
# ------------------------------------------------------------------ #

    def _clean_data(self, df):
        #Nettoie le DataFrame brut issu du fichier Excel ANP Eurocontrol v9.

        #Étapes :
        #1. Renommer les colonnes vers le format interne normalisé
        #2. Nettoyer les espaces parasites dans les valeurs texte
        #3. Convertir Op Mode 'A'/'D' → 'arrival'/'departure'
        #4. Appliquer _map_icao_codes() sur NPD_ID → aircraft_id
        #5. Renommer les colonnes de distance L_Xft → Ym (pieds→mètres)
        #6. Interpoler les NaN dans les colonnes de distance
        #7. Supprimer les lignes entièrement vides
        #8. Filtrer sur métrique SEL uniquement (pour cohérence interne)

        #Paramètre
        #df : pd.DataFrame — brut depuis Excel

        #Retourne
        #pd.DataFrame nettoyé avec colonnes :
        #    aircraft_id | operation | metric | thrust | 61m | 122m | … | 7620m

        df = df.copy()

        # 1. Renommer les colonnes Eurocontrol → noms internes
        col_rename = {
            "NPD_ID":         "aircraft_id",
            "Noise Metric":   "metric",
            "Op Mode":        "operation",
            "Power Setting":  "thrust",
        }
        df = df.rename(columns=col_rename)

        # 2. Nettoyer les espaces parasites dans les colonnes texte
        for col in ["aircraft_id", "metric", "operation"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        # 3. Convertir Op Mode 'A'/'D' → 'arrival'/'departure'
        op_map = {"A": "arrival", "D": "departure"}
        df["operation"] = df["operation"].map(op_map).fillna(df["operation"])

        # 4. Mapping NPD_ID → code OACI court
        df = self._map_icao_codes(df)

        # 5. Renommer colonnes de distance L_Xft → Ym (pieds → mètres)
        dist_rename = {}
        for ft_col, m_val in zip(self.FT_COLS, self.DISTANCES_M):
            if ft_col in df.columns:
                dist_rename[ft_col] = f"{m_val}m"
        df = df.rename(columns=dist_rename)

        # 6. Supprimer les lignes entièrement vides
        df = df.dropna(how="all")

        # 7. Interpoler les NaN dans les colonnes de distance
        dist_cols = [f"{d}m" for d in self.DISTANCES_M if f"{d}m" in df.columns]
        if dist_cols:
            df[dist_cols] = df[dist_cols].interpolate(axis=1, limit_direction="both")

        # 8. Conserver seulement SEL (métrique principale ECAC Doc 29)
        if "metric" in df.columns:
            df = df[df["metric"] == "SEL"].copy()

        df = df.reset_index(drop=True)
        return df
    #Validation
    def _validate_monotonicity(self, df):
        #Vérifie que chaque courbe NPD est décroissante avec la distance.

        #Émet un UserWarning pour chaque courbe non monotone
        #(erreur de mesure ou de saisie dans les données sources).

        #Paramètre
        #df : pd.DataFrame nettoyé (colonnes Ym)

        dist_cols = [f"{d}m" for d in self.DISTANCES_M if f"{d}m" in df.columns]
        if not dist_cols:
            return

        for _, row in df.iterrows():
            levels = row[dist_cols].values.astype(float)
            if not all(levels[i] >= levels[i + 1] for i in range(len(levels) - 1)):
                aircraft = row.get("aircraft_id", "?")
                op       = row.get("operation",   "?")
                thrust   = row.get("thrust",       "?")
                warnings.warn(
                    f"Courbe NPD non monotone — aircraft={aircraft}, "
                    f"op={op}, thrust={thrust} lbs. "
                    "Vérifiez les données sources.",
                    UserWarning,
                    stacklevel=2,
                )

    def _map_icao_codes(self, df):
        """
        Normalise aircraft_id (colonne NPD_ID) vers des codes OACI courts.

        Exemples :
            'A320-250N' → 'A320'
            '747400RN'  → 'B744'
            'ERJ190-300'→ 'E290'

        Paramètre
        ---------
        df : pd.DataFrame avec colonne aircraft_id

        Retourne
        --------
        pd.DataFrame avec aircraft_id normalisé
        """
        def _map_one(name):
            key = str(name).strip().lower()
            if key in self.NPD_ID_MAP:
                return self.NPD_ID_MAP[key]
            # Correspondance partielle
            for npd_id, code in self.NPD_ID_MAP.items():
                if npd_id in key or key in npd_id:
                    return code
            return str(name).strip()

        df = df.copy()
        df["aircraft_id"] = df["aircraft_id"].apply(_map_one)
        return df
