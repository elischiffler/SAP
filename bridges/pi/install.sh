#!/bin/bash
# First installation only. Never overwrite an unknown existing client/service.
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ $EUID -ne 0 ]]; then
    echo 'Run: sudo bash install.sh' >&2
    exit 1
fi
if [[ ! -f /etc/rpi-issue ]]; then
    echo 'This installer expects Raspberry Pi OS.' >&2
    exit 1
fi
if systemctl cat sap-pager.service >/dev/null 2>&1 || [[ -e /opt/sap-pager ]]; then
    echo 'Existing installation found; inspect it before updating.' >&2
    exit 1
fi
apt-get update
apt-get install -y python3-venv python3-gpiozero python3-lgpio alsa-utils ca-certificates
getent group gpio >/dev/null
getent group audio >/dev/null
if ! id sap-pager >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/sap-pager --no-create-home \
        --shell /usr/sbin/nologin sap-pager
fi
install -d -m 0755 /opt/sap-pager
install -m 0644 client.py led.py download_only.py /opt/sap-pager/
python3 -m venv --system-site-packages /opt/sap-pager/venv
/opt/sap-pager/venv/bin/pip install 'httpx==0.28.1'
install -m 0644 sap-pager.service /etc/systemd/system/sap-pager.service
if [[ ! -e /etc/default/sap-pager ]]; then
    install -m 0644 pager.env /etc/default/sap-pager
fi
systemctl daemon-reload
systemctl enable sap-pager.service
systemctl restart sap-pager.service
sleep 3
systemctl is-enabled sap-pager.service
systemctl is-active sap-pager.service
systemctl status sap-pager.service --no-pager
echo 'Installed. Polling only; playback and pending ACK retries require the button.'
