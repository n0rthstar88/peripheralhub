#!/usr/bin/env bash
# PeripheralHub installer. Safe to re-run.
#   ./install.sh              full install (asks for your password once, for the udev rule only)
#   ./install.sh --udev-only  just the device access rule (run as root, e.g. via pkexec from the app)
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RULE_SRC="$REPO/data/70-peripheralhub.rules"
RULE_DST="/etc/udev/rules.d/70-peripheralhub.rules"
APP_ID="dev.hufflabs.PeripheralHub"

install_udev() {
  install -m 0644 "$RULE_SRC" "$RULE_DST"
  udevadm control --reload
  udevadm trigger --subsystem-match=hidraw
  echo "Installed $RULE_DST"
}

if [[ "${1:-}" == "--udev-only" ]]; then
  if [[ $EUID -ne 0 ]]; then
    echo "--udev-only must run as root (sudo or pkexec)" >&2
    exit 1
  fi
  install_udev
  exit 0
fi

if [[ $EUID -eq 0 ]]; then
  echo "Run ./install.sh as your normal user; it asks for root only for the udev rule." >&2
  exit 1
fi

# 1. Device access rule (the only root step).
if cmp -s "$RULE_SRC" "$RULE_DST"; then
  echo "udev rule already installed"
elif [[ -t 0 ]]; then
  echo "Installing the device access rule (needs your password):"
  sudo "$REPO/install.sh" --udev-only
else
  pkexec "$REPO/install.sh" --udev-only
fi

# 2. Launchers.
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
cat > "$BIN/peripheralhub" <<EOF
#!/bin/sh
PYTHONPATH="$REPO/src\${PYTHONPATH:+:\$PYTHONPATH}" exec /usr/bin/python3 -m peripheralhub "\$@"
EOF
cat > "$BIN/phub" <<EOF
#!/bin/sh
exec "$BIN/peripheralhub" cli "\$@"
EOF
chmod 0755 "$BIN/peripheralhub" "$BIN/phub"

# 3. Icon and launcher entry (absolute Exec so it works even if ~/.local/bin isn't on the launcher's PATH).
ICONS="$HOME/.local/share/icons/hicolor"
mkdir -p "$ICONS/scalable/apps" "$HOME/.local/share/applications"
install -m 0644 "$REPO/data/icons/$APP_ID.svg" "$ICONS/scalable/apps/$APP_ID.svg"
sed "s|^Exec=peripheralhub|Exec=$BIN/peripheralhub|" "$REPO/data/$APP_ID.desktop" \
  > "$HOME/.local/share/applications/$APP_ID.desktop"
gtk-update-icon-cache -f -t "$ICONS" >/dev/null 2>&1 || true
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true

# 4. Background service.
UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"
install -m 0644 "$REPO/data/peripheralhub.service" "$UNITS/peripheralhub.service"
systemctl --user daemon-reload
systemctl --user enable --now peripheralhub
systemctl --user restart peripheralhub  # pick up code changes on re-runs

echo "PeripheralHub installed. Launch it from the app launcher, or run: peripheralhub"
