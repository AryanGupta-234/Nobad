import multiprocessing
import sys

from .app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()          # text-reading workers in the packaged app
    sys.exit(main())
