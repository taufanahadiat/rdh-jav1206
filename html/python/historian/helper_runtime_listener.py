#!/usr/bin/env python3
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from historian.listener import main


if __name__ == "__main__":
    sys.exit(main())
