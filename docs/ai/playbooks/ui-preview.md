# Playbook: preview the VPN UI without running the app

The real app needs admin rights and changes the firewall and tunnels, so never launch it just to look at the UI.
[`docs/ai/tools/ui_preview_mock.py`](../tools/ui_preview_mock.py) serves `apps/vpn/nobadvpn/ui` with a fake backend
(two servers, an Evil Twin report, no TMDB key). Nothing on the PC changes.

1. Start it in the background from the repo root:
   `python -I docs/ai/tools/ui_preview_mock.py apps/vpn/nobadvpn/ui 8791` (add `connected` as a third argument for the
   connected state with live health and traffic).
2. Open `http://127.0.0.1:8791/?tab=t5` in any browser, or screenshot it headless. Tabs: t2 Servers, t1 Streaming,
   t5 Network, t6 Intel, t4 Details, t3 Settings.
   ```
   timeout 60 "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --disable-gpu \
     --user-data-dir="<scratch>\prof" --window-size=1280,900 --virtual-time-budget=5000 \
     --screenshot="<scratch>\t5.png" "http://127.0.0.1:8791/?tab=t5"
   ```
3. To show a particular state (a bad Evil Twin grade, a long list), edit `STATE` in a **copy** of the mock in the
   scratch folder.
4. When done, stop the server (`netstat -ano | grep :8791`, then `taskkill //F //PID <pid>`) and delete the scratch
   folder. Never commit screenshots.
