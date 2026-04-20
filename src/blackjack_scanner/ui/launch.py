"""Entry point that launches the Streamlit UI via ``streamlit run``.

Exposed as the console script ``blackjack-scanner-ui`` (installed via the
``[ui]`` extra). Equivalent to ``streamlit run <path-to-streamlit_app.py>``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:  # pragma: no cover - import error branch
        raise SystemExit(
            "streamlit is not installed. Install the UI extra:\n"
            "    pip install 'blackjack-scanner[ui]'"
        ) from exc

    app_path = Path(__file__).resolve().parent / "streamlit_app.py"
    sys.argv = ["streamlit", "run", os.fspath(app_path), *sys.argv[1:]]
    raise SystemExit(stcli.main())


if __name__ == "__main__":  # pragma: no cover
    main()
