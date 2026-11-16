---
name: nobad-ui-preview
description: See the NOBAD VPN UI without launching the real (elevated) app - serves apps/vpn/nobadvpn/ui with a fake backend and takes headless Edge screenshots of any tab, connected or not. Use to check layout, alignment, cards or a new UI feature visually.
---

# Preview the VPN UI

The real app needs UAC and changes firewall and tunnels, so never launch it to look at the UI. Instead:

1. Start the fake backend in the background (state: 2 servers, an Evil Twin report, no TMDB key):
   `python -I .claude/skills/nobad-ui-preview/mock.py apps/vpn/nobadvpn/ui 8791` (add `connected` as a 3rd argument
   for the connected state, with live health and traffic events).
2. Screenshot a tab. Tabs: t2 Servers, t1 Streaming, t5 Network, t6 Intel, t4 Details, t3 Settings.
   ```
   "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --disable-gpu \
     --user-data-dir="C:\Users\aassw\nobad_tmp\prof" --window-size=1280,900 --virtual-time-budget=5000 \
     --screenshot="C:\Users\aassw\nobad_tmp\t5.png" "http://127.0.0.1:8791/?tab=t5"
   ```
   Wrap it in `timeout 60` (the event stream keeps the page busy for a few seconds). Read the PNG to look at it.
3. When done, stop the server (`netstat -ano | grep :8791` → `taskkill //F //PID <pid>`) and delete `C:\Users\aassw\nobad_tmp`.

To preview a specific state (a bad Evil Twin grade, a long list), edit `STATE` in a **copy** of `mock.py` in the
scratch folder. Don't commit screenshots.
