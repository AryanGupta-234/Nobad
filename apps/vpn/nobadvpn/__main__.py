"""`python -m nobadvpn`"""
import sys

if __name__ == "__main__":
    from .boot import early_splash
    early_splash(sys.argv)
    from .app import main
    sys.exit(main())
