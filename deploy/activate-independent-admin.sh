#!/usr/bin/env bash
# Run on the campaign server with sudo. No secrets are printed or sourced.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
    echo 'Run this script with sudo on the campaign server.' >&2
    exit 1
fi
TGL_ROOT=/home/deploy/apps/thegreatlogout.org
TGL_ROLLBACK=/var/backups/thegreatlogout-cutover-$(date -u +%Y%m%dT%H%M%S)
install -d -m 700 "$TGL_ROLLBACK"
cp /etc/nginx/sites-available/thegreatlogout.org "$TGL_ROLLBACK/public.nginx"
if [[ -f /etc/nginx/sites-available/admin.thegreatlogout.org ]]; then
    cp /etc/nginx/sites-available/admin.thegreatlogout.org "$TGL_ROLLBACK/admin.nginx"
fi
cd "$TGL_ROOT"
chmod 700 data
runuser -u deploy -- .venv/bin/python -m server.bootstrap_admin
for unit in thegreatlogout-admin.service thegreatlogout-maintenance.service thegreatlogout-maintenance.timer thegreatlogout-mail-sync.service thegreatlogout-mail-sync.timer; do
    install -m 644 "deploy/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now thegreatlogout-admin.service
systemctl restart thegreatlogout-admin.service
curl --retry 10 --retry-connrefused --retry-delay 1 --fail --silent http://127.0.0.1:8789/health
# Restore working public routing if TLS or cutover validation fails.
rollback_nginx() {
    cp "$TGL_ROLLBACK/public.nginx" /etc/nginx/sites-available/thegreatlogout.org
    if [[ -f "$TGL_ROLLBACK/admin.nginx" ]]; then
        cp "$TGL_ROLLBACK/admin.nginx" /etc/nginx/sites-available/admin.thegreatlogout.org
    else
        rm -f /etc/nginx/sites-enabled/admin.thegreatlogout.org
    fi
    nginx -t && systemctl reload nginx
    echo "Activation failed; previous nginx routing restored. Snapshot: $TGL_ROLLBACK" >&2
}
trap rollback_nginx ERR
if [[ ! -f /etc/letsencrypt/live/admin.thegreatlogout.org/fullchain.pem ]]; then
    install -m 644 deploy/admin.thegreatlogout.org.http.nginx /etc/nginx/sites-available/admin.thegreatlogout.org
    ln -sfn /etc/nginx/sites-available/admin.thegreatlogout.org /etc/nginx/sites-enabled/admin.thegreatlogout.org
    nginx -t
    systemctl reload nginx
    certbot certonly --webroot -w "$TGL_ROOT" -d admin.thegreatlogout.org --non-interactive --agree-tos
fi
install -m 644 deploy/admin.thegreatlogout.org.nginx /etc/nginx/sites-available/admin.thegreatlogout.org
ln -sfn /etc/nginx/sites-available/admin.thegreatlogout.org /etc/nginx/sites-enabled/admin.thegreatlogout.org
install -m 644 deploy/thegreatlogout.org.nginx /etc/nginx/sites-available/thegreatlogout.org
nginx -t
systemctl reload nginx
curl --fail --silent https://admin.thegreatlogout.org/health
curl --fail --silent https://api.thegreatlogout.org/health
curl --fail --silent --output /dev/null https://thegreatlogout.org/
# A final idempotent catch-up imports only campaign analytics received before cutover.
# This is a migration command, not a runtime dependency.
if [[ -f /home/deploy/apps/backend/data/analytics.db ]]; then
    runuser -u deploy -- .venv/bin/python -m server.bootstrap_admin --analytics-source /home/deploy/apps/backend/data/analytics.db
fi
systemctl enable --now thegreatlogout-maintenance.timer
systemctl start thegreatlogout-maintenance.service
# The mailbox timer is deliberately installed but not enabled without mailbox credentials.
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\n/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/thegreatlogout-admin
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/thegreatlogout-admin
trap - ERR
systemctl is-active thegreatlogout-admin.service thegreatlogout-guide.service thegreatlogout-send-due.timer thegreatlogout-maintenance.timer
echo "Independent campaign admin activated. Rollback snapshot: $TGL_ROLLBACK"
