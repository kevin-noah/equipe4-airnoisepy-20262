Installation
============

AirNoisePy requiert **Python 3.10 ou plus récent**.

Depuis le dépôt
---------------

Clonez le dépôt puis installez le package en mode standard :

.. code-block:: bash

   git clone https://github.com/kevin-noah/equipe4-airnoisepy-20262.git
   cd equipe4-airnoisepy-20262
   pip install .

Cette commande installe automatiquement toutes les dépendances listées dans
``pyproject.toml`` (numpy, pandas, scipy, matplotlib, folium, requests,
openpyxl, imageio, streamlit…).

Mode développement
------------------

Pour travailler sur le code sans réinstaller à chaque modification :

.. code-block:: bash

   pip install -e .

Construire la documentation
---------------------------

La documentation (ce site) se génère avec Sphinx. Installez les outils puis
lancez la construction :

.. code-block:: bash

   pip install sphinx furo
   cd docs
   make html

Le site HTML est alors disponible dans ``docs/_build/html/index.html``.

Lancer les tests
----------------

.. code-block:: bash

   python -m pytest tests/ -v

La démo interactive (Streamlit) se lance depuis la racine du dépôt :

.. code-block:: bash

   streamlit run demo/app.py
