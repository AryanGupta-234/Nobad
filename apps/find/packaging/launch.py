"""PyInstaller entry point for NobadFind.exe (same as `python -m nobadfind`)."""
import multiprocessing
import sys

from nobadfind.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()          # the text-reading worker processes start this exe again
    sys.exit(main())
