# ==========================================================
# CONFIGURATION SPHINX — documentation AirNoisePy
# ==========================================================
# Ce fichier indique à Sphinx comment construire la documentation.
# Il est lu automatiquement par la commande `make html`.
# Doc officielle : https://www.sphinx-doc.org/

import os
import sys
from datetime import datetime

# ----------------------------------------------------------
# Rendre le package « airnoisepy » importable par autodoc.
# conf.py est dans docs/, le code est un niveau au-dessus.
# ----------------------------------------------------------
sys.path.insert(0, os.path.abspath(".."))


# ----------------------------------------------------------
# Informations sur le projet
# ----------------------------------------------------------
project = "AirNoisePy"
author = "Équipe 4 — MGA802, ÉTS Montréal"
copyright = f"{datetime.now().year}, {author}"
release = "0.1.0"
version = "0.1.0"


# ----------------------------------------------------------
# Extensions Sphinx
# ----------------------------------------------------------
# autodoc   : génère la doc à partir des docstrings du code
# napoleon  : comprend les docstrings de style Google / NumPy
# viewcode  : ajoute un lien « [source] » vers le code
# intersphinx : crée des liens vers la doc de numpy, pandas, etc.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]


# ----------------------------------------------------------
# Langue et fichiers
# ----------------------------------------------------------
language = "fr"
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# ----------------------------------------------------------
# Thème HTML — Furo (moderne, mode clair/sombre)
# ----------------------------------------------------------
html_theme = "furo"
html_title = "AirNoisePy"
html_static_path = ["_static"]


# ----------------------------------------------------------
# Comportement d'autodoc
# ----------------------------------------------------------
# - membres documentés dans l'ordre du code source
# - affiche aussi les membres hérités et sans docstring
autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}

# Liens vers les docs des bibliothèques externes utilisées
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
}
