#!/usr/bin/env bash
# Install cedar-goto as a systemd service (DESIGN.md §9).
#
# Usage (from the repo root, on the target Pi/Linux host):
#   sudo packaging/install.sh [install_dir]
#
# Default install_dir is /opt/cedar-goto. Re-running this script upgrades
# an existing install (code + venv are refreshed; an existing config.toml
# is left untouched).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root (sudo)." >&2
    exit 1
fi

INSTALL_DIR="${1:-/opt/cedar-goto}"
SERVICE_USER="${CEDAR_GOTO_USER:-cedar-goto}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$INSTALL_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"

mkdir -p "$INSTALL_DIR"
# config*.toml examples (config-ascom-sim.toml, config-indi.toml) are dev/
# test references, not meant to be read by the deployed service -- excluded
# so they don't sit in $INSTALL_DIR looking like real config (confirmed
# confusing in practice: config-indi.toml's cedar.backend = "mock" looked
# like a live setting even though it's unused).
rsync -a --delete \
    --exclude='.venv' --exclude='.git' --exclude='__pycache__' --exclude='*.egg-info' \
    --exclude='config.toml' --exclude='config-ascom-sim.toml' --exclude='config-indi.toml' \
    "$REPO_DIR"/ "$INSTALL_DIR"/

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install "$INSTALL_DIR"
# pyindi-client (for [mount].backend = "indi", indi-refactor.md) ships
# prebuilt wheels and needs no compiler -- but it declares dbus-python as a
# hard dependency it doesn't actually import at runtime (confirmed by
# spike), and dbus-python has no wheels anywhere, forcing a meson/
# libdbus-1-dev source build we don't want. --no-deps skips that (and the
# also-unused requests/bottle deps); installed unconditionally since it's a
# small, harmless extra even when backend = "alpyca"/"mock".
"$INSTALL_DIR/.venv/bin/pip" install --no-deps pyindi-client

if [ ! -f "$INSTALL_DIR/config.toml" ]; then
    cp "$REPO_DIR/config.toml" "$INSTALL_DIR/config.toml"
    echo "Wrote default config to $INSTALL_DIR/config.toml -- edit it before starting the service."
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

install -m 644 "$REPO_DIR/packaging/cedar-goto.service" /etc/systemd/system/cedar-goto.service
systemctl daemon-reload
systemctl enable cedar-goto.service

cat <<EOF

Installed to $INSTALL_DIR.
Next steps:
  1. Edit $INSTALL_DIR/config.toml (mount/cedar addresses, backend = "alpyca"/"grpc" for real hardware).
  2. sudo systemctl start cedar-goto
  3. journalctl -u cedar-goto -f
EOF
