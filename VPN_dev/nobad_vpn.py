"""NOBAD VPN launcher.   Run:  python nobad_vpn.py      (see README.md)"""
import sys

if __name__ == "__main__":
    from nobadvpn.boot import early_splash
    early_splash(sys.argv)          # logo on screen before the heavy imports
    from nobadvpn.app import main
    sys.exit(main())
