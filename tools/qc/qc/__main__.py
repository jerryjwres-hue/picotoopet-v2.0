"""Module execution entrypoint for `python -m qc ...`"""

import sys
from qc.cli import main

if __name__ == "__main__":
    sys.exit(main())
