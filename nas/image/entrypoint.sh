#!/bin/sh
# Start the agent. When REMOTE_VIEW=1, also start a virtual screen with a browser view
# that a person can open in a web page (noVNC) to finish a captcha by hand.
if [ "$REMOTE_VIEW" = "1" ] && [ -z "$VNC_PASSWORD" ]; then
  echo "REMOTE_VIEW=1 needs VNC_PASSWORD; browser view not started" >&2
elif [ "$REMOTE_VIEW" = "1" ]; then
  export DISPLAY=:99
  Xvfb :99 -screen 0 1366x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
  sleep 1
  fluxbox >/tmp/fluxbox.log 2>&1 &
  x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vncpass >/dev/null 2>&1
  x11vnc -display :99 -forever -shared -localhost -rfbport 5900 -rfbauth /tmp/vncpass >/tmp/x11vnc.log 2>&1 &
  websockify --web /usr/share/novnc "${VIEW_PORT:-16080}" localhost:5900 >/tmp/novnc.log 2>&1 &
fi
exec python /app/bootstrap.py
