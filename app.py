"""Streamlit entry point.

Run with::

    streamlit run app.py

The actual UI code lives in :mod:`blackjack_scanner.ui.streamlit_app` so it
can also be launched via the ``blackjack-scanner-ui`` console script
(installed by the ``[ui]`` extra).
"""

from blackjack_scanner.ui.streamlit_app import run

# Streamlit re-executes this file on every interaction, so the render must
# happen via an explicit call — a bare import would hit the module cache on
# reruns and render nothing.
run()
