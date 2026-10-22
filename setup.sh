#!/usr/bin/env bash
# One-shot local setup for watcher-hub (macOS / Linux).
#   ./setup.sh          create .venv, install deps, run tests, show ports + LAN IP
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"' \
  || { echo "Need Python 3.10+ (brew install python / apt install python3)"; exit 1; }

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "== Tests (simulated Watcher) =="
python -m unittest discover -s tests

echo
echo "== Serial ports (plug the Watcher in by USB-C; it usually shows TWO) =="
python watcher/control.py ports || true

echo
echo "== This computer's LAN IP (put http://<IP>:8887 in the app's HTTP Message Block) =="
if command -v ipconfig >/dev/null 2>&1 && [ "$(uname)" = "Darwin" ]; then
  ipconfig getifaddr en0 || ipconfig getifaddr en1 || echo "(not found: check System Settings > Network)"
else
  hostname -I 2>/dev/null | awk '{print $1}' || ip -4 addr | awk '/inet / && !/127.0.0.1/ {print $2; exit}'
fi

cat <<'EOF'

Next:
  source .venv/bin/activate
  python watcher/receiver.py --voice               # terminal 1 (alarms + voice commands)
  python watcher/control.py battery                # terminal 2 (port auto-detected; stop the receiver first)
  python watcher/control.py load gesture
No hardware?  python tools/fake_watcher.py --push http://127.0.0.1:8887
EOF
