# Responsable : Kevin
# Classe FlightOperation — trajectoire 3D en segments, classification départ/arrivée, profil de poussée

import math


class FlightOperation:
    """
    Représente une trajectoire de vol réelle sous forme de segments 3D
    exploitables pour le calcul acoustique ECAC Doc 29.

    Un vol OpenSky est une liste de points GPS bruts (~10s d'intervalle).
    Cette classe les convertit en segments rectilignes à vitesse et poussée
    constantes, format requis par NoiseCalculator.
    """

    # % N1 (vitesse rotation compresseur basse pression) par phase de vol
    _THRUST_PROFILE = {
        'takeoff':  0.94,
        'climb':    0.86,
        'cruise':   0.80,
        'approach': 0.68,
        'landing':  0.68,
    }

    # Seuil remise de gaz : 2000 ft AGL en mètres
    _GO_AROUND_ALT_M = 610.0

    def __init__(self, icao24, callsign, operation_type, waypoints):
        """
        Paramètres
        ----------
        icao24         : str  — identifiant hexadécimal unique de l'avion (ex: 'c07e32')
        callsign       : str  — indicatif radio (ex: 'ACA750')
        operation_type : str  — 'departure' ou 'arrival'
        waypoints      : list — liste de dicts {time, lat, lon, alt_baro (m), speed (m/s)}
        """
        self.icao24 = icao24
        self.callsign = (callsign or '').strip()
        self.operation_type = operation_type
        self.waypoints = waypoints
        self.is_go_around = self.detect_go_around()
        self.segments = self.compute_segments()

    # ------------------------------------------------------------------
    # Constructeur alternatif — format brut OpenSky REST API
    # ------------------------------------------------------------------

    @classmethod
    def from_opensky(cls, track_data):
        """
        Construit un FlightOperation depuis la réponse brute de l'API OpenSky.

        Paramètre
        ---------
        track_data : dict — {'icao24', 'callsign', 'path': [[t, lat, lon, alt_m, hdg, on_ground], ...]}

        Retourne
        --------
        FlightOperation
        """
        icao24 = track_data['icao24']
        callsign = track_data.get('callsign', '')
        path = track_data['path']

        waypoints = []
        for i, point in enumerate(path):
            t, lat, lon, alt_baro, _heading, _on_ground = point

            if i > 0:
                prev = path[i - 1]
                dt = t - prev[0]
                speed = cls._haversine(prev[1], prev[2], lat, lon) / dt if dt > 0 else 0.0
            else:
                speed = 0.0

            waypoints.append({
                'time':     t,
                'lat':      lat,
                'lon':      lon,
                'alt_baro': alt_baro,  # mètres
                'speed':    speed,     # m/s
            })

        # Premier waypoint : utilise la vitesse du segment suivant
        if len(waypoints) >= 2:
            waypoints[0]['speed'] = waypoints[1]['speed']

        op_type = cls._classify_from_waypoints(waypoints)
        return cls(icao24, callsign, op_type, waypoints)

    # ------------------------------------------------------------------
    # Méthodes publiques
    # ------------------------------------------------------------------

    def classify_operation(self):
        """
        Retourne 'departure' ou 'arrival' selon la tendance d'altitude globale.
        Altitude finale > altitude initiale → décollage.
        """
        return self._classify_from_waypoints(self.waypoints)

    def detect_go_around(self):
        """
        Détecte une remise de gaz : descente suivie d'une remontée sous 2000 ft AGL.
        Une remise de gaz signifie que l'avion est bas ET remet pleine puissance —
        ce qui est acoustiquement critique et doit être signalé à NoiseCalculator.

        Retourne : bool
        """
        alts = [wp['alt_baro'] for wp in self.waypoints]
        found_descent = False
        for i in range(1, len(alts)):
            if alts[i] < alts[i - 1] and alts[i] < self._GO_AROUND_ALT_M:
                found_descent = True
            elif found_descent and alts[i] > alts[i - 1]:
                return True
        return False

    def compute_segments(self):
        """
        Convertit les waypoints en segments rectilignes consécutifs.

        Chaque segment couvre une paire de waypoints (A → B) et contient
        les attributs requis par NoiseCalculator : position 3D, vitesse,
        durée, phase de vol et poussée estimée.

        Retourne : list de dicts
            {lat_start, lon_start, alt_start (m),
             lat_end,   lon_end,   alt_end   (m),
             speed_ms (m/s), duration_s (s), thrust_pct, phase}
        """
        segments = []
        for i in range(len(self.waypoints) - 1):
            wp0 = self.waypoints[i]
            wp1 = self.waypoints[i + 1]

            duration = wp1['time'] - wp0['time']
            dist = self._haversine(wp0['lat'], wp0['lon'], wp1['lat'], wp1['lon'])
            speed = dist / duration if duration > 0 else 0.0
            alt_mid = (wp0['alt_baro'] + wp1['alt_baro']) / 2.0
            phase = self._get_phase(alt_mid)

            segments.append({
                'lat_start':  wp0['lat'],
                'lon_start':  wp0['lon'],
                'alt_start':  wp0['alt_baro'],
                'lat_end':    wp1['lat'],
                'lon_end':    wp1['lon'],
                'alt_end':    wp1['alt_baro'],
                'speed_ms':   speed,
                'duration_s': duration,
                'thrust_pct': self.get_thrust_profile(phase),
                'phase':      phase,
            })
        return segments

    def get_thrust_profile(self, phase):
        """
        Retourne le % N1 estimé selon la phase de vol.

        Valeurs (ECAC Doc 29, Vol. 2 — profils par défaut) :
          takeoff  = 94 %   climb = 86 %   cruise   = 80 %
          approach = 68 %   landing = 68 %
        """
        return self._THRUST_PROFILE.get(phase, 0.80)

    def to_dict(self):
        """Sérialise l'objet en dict JSON-compatible pour export/debug."""
        return {
            'icao24':         self.icao24,
            'callsign':       self.callsign,
            'operation_type': self.operation_type,
            'is_go_around':   self.is_go_around,
            'waypoints':      self.waypoints,
            'segments':       self.segments,
        }

    # ------------------------------------------------------------------
    # Méthodes internes
    # ------------------------------------------------------------------

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """Distance en mètres entre deux coordonnées GPS (formule haversine)."""
        R = 6_371_000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _classify_from_waypoints(waypoints):
        """Détermine departure/arrival depuis la liste de waypoints."""
        if len(waypoints) < 2:
            return 'departure'
        return 'departure' if waypoints[-1]['alt_baro'] > waypoints[0]['alt_baro'] else 'arrival'

    def _get_phase(self, alt_baro_m):
        """
        Détermine la phase de vol à partir de l'altitude (en mètres).
        La phase détermine la poussée moteur et donc le niveau de bruit NPD.
        """
        alt_ft = alt_baro_m * 3.28084
        if self.operation_type == 'departure':
            if alt_ft < 1000:
                return 'takeoff'
            if alt_ft < 10_000:
                return 'climb'
            return 'cruise'
        else:
            return 'landing' if alt_ft < 1000 else 'approach'
