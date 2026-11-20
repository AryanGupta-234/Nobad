"""PyInstaller entry point for NobadFind.exe (same as `python -m nobadfind`)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()          # the text-reading worker processes start this exe again
    # After freeze_support, not at the top: a worker runs this file too, and the app's imports (numpy, the models)
    # would cost every text reader about 500 MB of commit (docs/measurements.md).
    from nobadfind.app import main
    sys.exit(main())
