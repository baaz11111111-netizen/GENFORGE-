"""Launch the GENFORGE Streamlit application."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit.web.cli as stcli


def main() -> None:
    app_path = Path(__file__).with_name("app.py")
    sys.argv = ["streamlit", "run", str(app_path)]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    main()
