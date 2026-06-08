# Responsable : Kevin
# status      : in progress
# Classe NoiseCalculator — calcul SEL + Lden par récepteur (ECAC Doc 29), grille 400x400

import math
import datetime

import numpy as np


class NoiseCalculator:
    """
    Calcule les niveaux de bruit SEL et Lden selon ECAC Doc 29, Vol. 2.

    Pipeline pour un récepteur au sol :
      1. Slant-range 3D de chaque segment de vol
      2. Niveau NPD interpolé depuis ANPDatabase
      3. Trois corrections : durée, latérale, atmosphérique
      4. Agrégation logarithmique → SEL du vol
      5. Pondération jour/soir/nuit → Lden
    """

    _V_REF_MS = 82.3    # 160 nœuds — vitesse de référence des tables NPD
    _D_REF_M = 1000.0   # distance de référence des tables NPD (m)

    def __init__(self, anp_db, temperature=15.0, humidity=70.0):
        """
        Paramètres
        ----------
        anp_db      : ANPDatabase — instance de la base NPD
        temperature : float — °C (correction atmosphérique)
        humidity    : float — % humidité relative
        """
        self.anp_db = anp_db
        self.temperature = temperature
        self.humidity = humidity
        # Pré-calculé une fois pour éviter 160 000 recalculs sur la grille
        self.alpha = self._compute_alpha(temperature, humidity)

    # ------------------------------------------------------------------
    # Méthodes publiques
    # ------------------------------------------------------------------

    def compute_sel(self, flight_op, receptor, aircraft_type='A320'):
        """
        SEL (Sound Exposure Level) en dB(A) pour un vol à un récepteur.

        Paramètres
        ----------
        flight_op    : FlightOperation — trajectoire 3D segmentée
        receptor     : tuple (lat, lon) — coordonnées du récepteur au sol
        aircraft_type: str — code OACI de l'avion (ex: 'A320')

        Retourne
        --------
        float — SEL total du vol en dB(A)
        """
        op = flight_op.operation_type
        sel_segments = []

        for seg in flight_op.segments:
            d = max(self._slant_range(seg, receptor), 1.0)
            sel_npd = self.anp_db.interpolate(aircraft_type, op, d, seg['thrust_pct'])
            sel_seg = (sel_npd
                       + self._correction_duration(seg)
                       + self._correction_lateral(seg, receptor)
                       + self._correction_atmospheric(d))
            sel_segments.append(sel_seg)

        return self._aggregate_sel(sel_segments) if sel_segments else 0.0

    def compute_lden(self, flights, receptor, date, aircraft_type='A320'):
        """
        Lden (Level Day-Evening-Night) en dB(A) pour un récepteur.

        Paramètres
        ----------
        flights      : list[FlightOperation] — tous les vols du jour
        receptor     : tuple (lat, lon)
        date         : datetime.date — jour à calculer
        aircraft_type: str — code OACI

        Retourne
        --------
        float — Lden en dB(A)

        Formule (directive 2002/49/CE) :
          Lden = 10·log10[(E_jour + E_soir·10^0.5 + E_nuit·10^1.0) / 86400]
          Pénalités : soir (19h–23h) +5 dB, nuit (23h–07h) +10 dB.
        """
        energy_day = energy_eve = energy_night = 0.0

        for fl in flights:
            if not fl.waypoints:
                continue
            sel = self.compute_sel(fl, receptor, aircraft_type)
            e = 10 ** (sel / 10.0)
            hour = self._utc_hour(fl.waypoints[0]['time'])
            if 7 <= hour < 19:
                energy_day += e
            elif 19 <= hour < 23:
                energy_eve += e
            else:
                energy_night += e

        total = energy_day + energy_eve * 10 ** 0.5 + energy_night * 10 ** 1.0
        return 10 * math.log10(total / 86400) if total > 0 else 0.0

    def compute_grid(self, flights, receptor_grid, aircraft_type='A320'):
        """
        Lden vectorisé pour une grille de récepteurs.

        Paramètres
        ----------
        flights       : list[FlightOperation]
        receptor_grid : np.ndarray shape (N, 2) — colonnes [lat, lon]
        aircraft_type : str — code OACI

        Retourne
        --------
        np.ndarray shape (N,) — Lden en dB(A) pour chaque récepteur
        """
        n = len(receptor_grid)
        energy_day   = np.zeros(n)
        energy_eve   = np.zeros(n)
        energy_night = np.zeros(n)

        for fl in flights:
            if not fl.waypoints:
                continue
            hour = self._utc_hour(fl.waypoints[0]['time'])
            sel_all = self._compute_sel_grid(fl, receptor_grid, aircraft_type)
            e = 10 ** (sel_all / 10.0)

            if 7 <= hour < 19:
                energy_day += e
            elif 19 <= hour < 23:
                energy_eve += e
            else:
                energy_night += e

        total = energy_day + energy_eve * 10 ** 0.5 + energy_night * 10 ** 1.0
        lden = np.zeros(n)
        mask = total > 0
        lden[mask] = 10 * np.log10(total[mask] / 86400)
        return lden

    # ------------------------------------------------------------------
    # Corrections ECAC Doc 29
    # ------------------------------------------------------------------

    def _correction_duration(self, segment):
        """
        ΔL_dur = 10·log10(v_ref / v_avion)   [ECAC Doc 29 §3.5]
        La table NPD suppose 160 nœuds. Un avion plus rapide passe plus vite
        au-dessus du récepteur → exposition plus courte → correction négative.
        """
        v = segment['speed_ms'] if segment['speed_ms'] >= 1.0 else self._V_REF_MS
        return 10 * math.log10(self._V_REF_MS / v)

    def _correction_lateral(self, segment, receptor):
        """
        ΔL_lat — directivité moteur, ECAC Doc 29 Annexe D simplifié.
        ΔL_lat = max(-10·log10(sin²β + 0.0038), 0)
        β = angle d'élévation du segment au-dessus du plan horizontal du récepteur.
        Récepteur directement sous l'avion (β = 90°) : correction nulle.
        """
        d_hor = self._horizontal_distance(segment, receptor)
        alt_m = (segment['alt_start'] + segment['alt_end']) / 2.0
        slant = math.sqrt(d_hor ** 2 + alt_m ** 2)
        sin_beta = alt_m / slant if slant > 0 else 1.0
        return max(-10 * math.log10(sin_beta ** 2 + 0.0038), 0.0)

    def _correction_atmospheric(self, distance):
        """
        ΔL_atm = -α · (d − 1000)   [α en dB/m, d en m, ECAC Doc 29 §3.7]
        Nul à 1000 m (distance de référence NPD), croissant avec la distance.
        """
        return -self.alpha * (distance - self._D_REF_M)

    # ------------------------------------------------------------------
    # Helpers scalaires
    # ------------------------------------------------------------------

    @staticmethod
    def _slant_range(segment, receptor):
        """Distance 3D oblique entre le milieu d'un segment et un récepteur au sol."""
        lat_r, lon_r = receptor
        lat_m = (segment['lat_start'] + segment['lat_end']) / 2.0
        lon_m = (segment['lon_start'] + segment['lon_end']) / 2.0
        alt_m = (segment['alt_start'] + segment['alt_end']) / 2.0
        lat_rad = math.radians((lat_r + lat_m) / 2.0)
        dx = (lon_m - lon_r) * math.radians(1) * 6_371_000 * math.cos(lat_rad)
        dy = (lat_m - lat_r) * math.radians(1) * 6_371_000
        return math.sqrt(dx ** 2 + dy ** 2 + alt_m ** 2)

    @staticmethod
    def _horizontal_distance(segment, receptor):
        """Distance horizontale (projection au sol) entre segment et récepteur."""
        lat_r, lon_r = receptor
        lat_m = (segment['lat_start'] + segment['lat_end']) / 2.0
        lon_m = (segment['lon_start'] + segment['lon_end']) / 2.0
        lat_rad = math.radians((lat_r + lat_m) / 2.0)
        dx = (lon_m - lon_r) * math.radians(1) * 6_371_000 * math.cos(lat_rad)
        dy = (lat_m - lat_r) * math.radians(1) * 6_371_000
        return math.sqrt(dx ** 2 + dy ** 2)

    @staticmethod
    def _aggregate_sel(sel_list):
        """
        Somme logarithmique ECAC Doc 29 : 10·log10(Σ 10^(SEL_i/10))
        Les dB NE s'additionnent PAS directement : 70+70 dB = 73 dB (pas 140).
        """
        return 10 * math.log10(sum(10 ** (s / 10.0) for s in sel_list))

    @staticmethod
    def _utc_hour(unix_timestamp):
        """Heure UTC (0-23) depuis un timestamp Unix."""
        return datetime.datetime.fromtimestamp(
            unix_timestamp, tz=datetime.timezone.utc
        ).hour

    # ------------------------------------------------------------------
    # Vectorisé — grille numpy
    # ------------------------------------------------------------------

    def _compute_sel_grid(self, flight_op, receptor_grid, aircraft_type):
        """SEL pour un vol sur toute la grille — géométrie vectorisée (numpy)."""
        lats = receptor_grid[:, 0]
        lons = receptor_grid[:, 1]
        energy_total = np.zeros(len(receptor_grid))
        op = flight_op.operation_type

        for seg in flight_op.segments:
            d_vec = self._slant_range_vec(seg, lats, lons)
            np.maximum(d_vec, 1.0, out=d_vec)

            sel_npd = np.array([
                self.anp_db.interpolate(aircraft_type, op, float(d), seg['thrust_pct'])
                for d in d_vec
            ])
            delta_dur = self._correction_duration(seg)
            delta_lat = self._correction_lateral_vec(seg, lats, lons, d_vec)
            delta_atm = -self.alpha * (d_vec - self._D_REF_M)

            energy_total += 10 ** ((sel_npd + delta_dur + delta_lat + delta_atm) / 10.0)

        result = np.zeros(len(receptor_grid))
        mask = energy_total > 0
        result[mask] = 10 * np.log10(energy_total[mask])
        return result

    @staticmethod
    def _slant_range_vec(segment, lats, lons):
        """Slant-range vectorisé vers une grille de récepteurs."""
        lat_m = (segment['lat_start'] + segment['lat_end']) / 2.0
        lon_m = (segment['lon_start'] + segment['lon_end']) / 2.0
        alt_m = (segment['alt_start'] + segment['alt_end']) / 2.0
        lat_avg = np.radians((lats + lat_m) / 2.0)
        dx = (lon_m - lons) * np.radians(1) * 6_371_000 * np.cos(lat_avg)
        dy = (lat_m - lats) * np.radians(1) * 6_371_000
        return np.sqrt(dx ** 2 + dy ** 2 + alt_m ** 2)

    @staticmethod
    def _correction_lateral_vec(segment, lats, lons, d_slant):
        """Correction latérale vectorisée pour une grille de récepteurs."""
        lat_m = (segment['lat_start'] + segment['lat_end']) / 2.0
        lon_m = (segment['lon_start'] + segment['lon_end']) / 2.0
        alt_m = (segment['alt_start'] + segment['alt_end']) / 2.0
        lat_avg = np.radians((lats + lat_m) / 2.0)
        dx = (lon_m - lons) * np.radians(1) * 6_371_000 * np.cos(lat_avg)
        dy = (lat_m - lats) * np.radians(1) * 6_371_000
        d_hor = np.sqrt(dx ** 2 + dy ** 2)
        slant = np.sqrt(d_hor ** 2 + alt_m ** 2)
        sin_beta = np.where(slant > 0, alt_m / slant, 1.0)
        return np.maximum(-10 * np.log10(sin_beta ** 2 + 0.0038), 0.0)

    # ------------------------------------------------------------------
    # Coefficient α — ISO 9613-1
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_alpha(temperature, humidity):
        """
        Coefficient d'absorption atmosphérique en dB/m (ISO 9613-1, éq. 1-4).
        Calculé à 1000 Hz, représentatif du spectre A-pondéré des avions civils.
        Valeurs typiques Montréal : 0.001 à 0.002 dB/m.
        """
        T_K = temperature + 273.15
        # Pression de vapeur saturante (formule de Magnus) en hPa
        e_sat = 6.1078 * 10 ** (7.5 * temperature / (237.3 + temperature))
        # Humidité molaire (%)
        h = (humidity / 100.0 * e_sat) / 1013.25 * 100.0
        # Fréquences de relaxation O₂ et N₂ (ISO 9613-1, éq. 3 & 4)
        frO = 24 + 4.04e4 * h * (0.02 + h) / (0.391 + h)
        frN = T_K ** -0.5 * (
            9 + 280 * h * math.exp(-4.17 * ((T_K / 293.15) ** (-1 / 3) - 1))
        )
        # Absorption à 1000 Hz (ISO 9613-1, éq. 1)
        f = 1000.0
        alpha = 8.686 * f ** 2 * (
            1.84e-11 * (T_K / 293.15) ** 0.5
            + (T_K / 293.15) ** -2.5 * (
                0.01275 * math.exp(-2239.1 / T_K) / (frO + f ** 2 / frO)
                + 0.1068 * math.exp(-3352.0 / T_K) / (frN + f ** 2 / frN)
            )
        )
        # Correction empirique pour le spectre A-pondéré large bande des avions
        return alpha * 0.7
