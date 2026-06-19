# Tests — AirNoisePy

Cette suite vérifie les six classes de la bibliothèque ainsi que l'intégration
de bout en bout du pipeline (données → vol → calcul → cartographie → export).

## Lancer les tests

Depuis la **racine** du dépôt :

```bash
pip install .            # installe airnoisepy et ses dépendances
python -m pytest tests/ -v
```

Résultat attendu : **283 tests passent** en quelques secondes.

> ⚠️ Lancer `pytest` tout court (sans `tests/`) tenterait aussi de collecter
> `data/test_opensky.py`, qui est un script de démonstration, pas un test.
> Toujours cibler le dossier `tests/`.

## Organisation des cas de test

| Fichier | Classe testée | Cas |
|---|---|---|
| `test_anp_database.py` | `ANPDatabase` | 47 |
| `test_flight_operation.py` | `FlightOperation` | 37 |
| `test_noise_calculator.py` | `NoiseCalculator` | 40 |
| `test_noise_contour.py` | `NoiseContour` | 54 |
| `test_opensky_fetcher.py` | `OpenSkyFetcher` | 77 |
| `test_results_exporter.py` | `ResultsExporter` | 8 |

Chaque suite couvre : la mécanique de calcul (vérifiée contre des valeurs
analytiques exactes via un *mock* de la base NPD), le nettoyage des données
ADS-B, l'intégration avec la vraie base EASA, et la plausibilité physique
(le bruit décroît avec la distance, croît avec la poussée, départ > arrivée).

## Exemple d'exécution du programme

Le scénario ci-dessous reproduit ce que vérifient les tests d'intégration :
calculer le niveau sonore d'un décollage pour un riverain situé près de YUL.

```python
import datetime
from airnoisepy import ANPDatabase, FlightOperation, NoiseCalculator

# 1. Base de courbes Noise-Power-Distance (vraies courbes EASA ANP v9).
#    Sans argument, ANPDatabase() charge plutôt une table synthétique A320.
anp = ANPDatabase("data/anp/EASA_ANP_database_NPD_Data_v9.xlsx")

# 2. Un décollage décrit par quelques points GPS (lat, lon, altitude en m)
waypoints = [
    {"time": 0,  "lat": 45.470, "lon": -73.740, "alt_baro": 100,  "speed": 80},
    {"time": 20, "lat": 45.490, "lon": -73.760, "alt_baro": 600,  "speed": 95},
    {"time": 40, "lat": 45.510, "lon": -73.780, "alt_baro": 1500, "speed": 110},
]
vol = FlightOperation("c07e32", "ACA750", "departure", waypoints)

# 3. Calcul du bruit pour un riverain au sol
calc = NoiseCalculator(anp, temperature=15.0, humidity=70.0)
recepteur = (45.50, -73.77)            # (latitude, longitude)

sel = calc.compute_sel(vol, recepteur)
print(f"SEL  = {sel:.1f} dB(A)")

date = datetime.datetime(2026, 6, 17, tzinfo=datetime.timezone.utc)
lden = calc.compute_lden([vol], recepteur, date)
print(f"Lden = {lden:.1f} dB(A)")
```

Pour une démonstration interactive complète (cartes, animation 24 h,
avions en direct), lancer l'application Streamlit depuis la racine :

```bash
streamlit run demo/app.py
```

La documentation HTML complète de l'API se trouve dans
[`../docs/_build/html/index.html`](../docs/_build/html/index.html).
