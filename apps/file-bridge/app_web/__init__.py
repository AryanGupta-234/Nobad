"""NOBAD File Bridge web UI: a loopback HTTP server + SSE event bus shown in a pywebview window.

The pattern is NOBAD VPN's (apps/vpn/nobadvpn/server.py, logbus.py): the page is served from 127.0.0.1 on a random
port, signs in once with a launch code, calls ``POST /api/<name>`` and listens to ``GET /events``. The backend
services are the same ones the Qt UI uses."""
