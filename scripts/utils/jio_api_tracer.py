"""Backward-compatible launcher for the Jio master tracer preset."""

import sys

from master_http_tracer import main


if __name__ == "__main__":
    sys.argv.insert(1, "jio")
    main()
