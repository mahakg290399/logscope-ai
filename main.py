"""Root entrypoint for running LogScope AI."""

import os
import sys

# Ensure src/ is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from logscope.cli import main

if __name__ == "__main__":
    main()
