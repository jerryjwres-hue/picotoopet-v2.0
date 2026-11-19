"""Module execution entrypoint for `python -m edit ...`"""

import sys
from edit.cli import main

if __name__ == "__main__":
    sys.exit(main())
