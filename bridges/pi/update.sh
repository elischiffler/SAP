#!/bin/bash
# Update code only; preserve the existing service, GPIO, audio and pending ACK.
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ $EUID -ne 0 ]]; then
    echo 'Run: sudo bash update.sh' >&2
    exit 1
fi
test -x /opt/sap-pager/venv/bin/python
systemctl cat sap-pager.service >/dev/null
/opt/sap-pager/venv/bin/python -m py_compile client.py led.py download_only.py
backup=$(mktemp -d /opt/sap-pager/code-backup.XXXXXX)
for name in client.py led.py download_only.py; do
    if [[ -f /opt/sap-pager/$name ]]; then
        cp -p "/opt/sap-pager/$name" "$backup/$name"
    fi
done
rollback() {
    code=$?
    if [[ $code -ne 0 ]]; then
        echo "Update failed; restoring code from $backup" >&2
        cp -p "$backup/"*.py /opt/sap-pager/
        systemctl reset-failed sap-pager.service
        systemctl restart sap-pager.service || true
    fi
}
trap rollback EXIT
systemctl stop sap-pager.service
install -m 0644 client.py led.py download_only.py /opt/sap-pager/
systemctl reset-failed sap-pager.service
systemctl restart sap-pager.service
sleep 5
systemctl is-active --quiet sap-pager.service
systemctl is-enabled sap-pager.service
systemctl status sap-pager.service --no-pager
echo "Updated. Code backup: $backup. GPIO/audio/service settings and ACK journal preserved."
