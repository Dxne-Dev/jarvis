"""Point d'entrée du moteur empaqueté (PyInstaller) : le même que `python -m ojarvis`."""

import sys

from ojarvis.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
