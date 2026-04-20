"""Streamlit entry point.

Run with::

    streamlit run app.py

The actual UI code lives in :mod:`blackjack_scanner.ui.streamlit_app` so it
can also be launched via the ``blackjack-scanner-ui`` console script
(installed by the ``[ui]`` extra).
"""

from blackjack_scanner.ui import streamlit_app  # noqa: F401  (side-effects render the app)
