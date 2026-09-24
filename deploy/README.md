# Self-hosted deployment

This deployment serves the static site, guide API, scheduler, subscriber database, and first-party analytics from the same server. Postmark is the only service used for email delivery.

## Runtime layout

- Website root: `/home/deploy/apps/thegreatlogout.org`
- Guide API: `127.0.0.1:8788`
- Guide database: `/home/deploy/apps/thegreatlogout.org/data/thegreatlogout.db`
- Analytics API and dashboard: existing backend on `127.0.0.1:8060`
- Public hosts: `thegreatlogout.org`, `www.thegreatlogout.org`, `api.thegreatlogout.org`

## 1. Configure the guide service

The local `.env` file must stay untracked and readable only by `deploy`:

```bash
cd /home/deploy/apps/thegreatlogout.org
chmod 600 .env
```

Set `POSTMARK_SERVER_TOKEN` to the Postmark server token that is authorized to send from `hello@thegreatlogout.org`. Do not paste the token into a command, Git, a log, or a chat message.

The virtual environment is created with:

```bash
cd /home/deploy/apps/thegreatlogout.org
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
```

## 2. Install and start systemd units

```bash
sudo install -m 0644 /home/deploy/apps/thegreatlogout.org/deploy/thegreatlogout-guide.service /etc/systemd/system/thegreatlogout-guide.service
sudo install -m 0644 /home/deploy/apps/thegreatlogout.org/deploy/thegreatlogout-send-due.service /etc/systemd/system/thegreatlogout-send-due.service
sudo install -m 0644 /home/deploy/apps/thegreatlogout.org/deploy/thegreatlogout-send-due.timer /etc/systemd/system/thegreatlogout-send-due.timer
sudo systemctl daemon-reload
sudo systemctl enable --now thegreatlogout-guide.service thegreatlogout-send-due.timer
curl --fail --silent http://127.0.0.1:8788/health
sudo systemctl status --no-pager thegreatlogout-guide.service thegreatlogout-send-due.timer
```

Expected health response: `{"status":"ok"}`.

## 3. Install the HTTP bootstrap site

Confirm that no site with this name already exists before creating the symlink:

```bash
readlink -f /etc/nginx/sites-enabled/thegreatlogout.org || true
sudo install -m 0644 /home/deploy/apps/thegreatlogout.org/deploy/thegreatlogout.org.http.nginx /etc/nginx/sites-available/thegreatlogout.org
sudo ln -s /etc/nginx/sites-available/thegreatlogout.org /etc/nginx/sites-enabled/thegreatlogout.org
sudo nginx -t
sudo systemctl reload nginx
```

## 4. Point DNS directly at the server

The intended direct records are:

| Name | Type | Value |
| --- | --- | --- |
| `@` | A | `46.225.191.50` |
| `@` | AAAA | `2a01:4f8:1c19:134d::1` |
| `www` | CNAME | `thegreatlogout.org` |
| `api` | A | `46.225.191.50` |
| `api` | AAAA | `2a01:4f8:1c19:134d::1` |

When moving authoritative DNS away from Cloudflare, copy all existing MX, SPF, DKIM, DMARC, domain-verification, and other TXT records before changing nameservers. Do not proxy the A or AAAA records.

Verify both public resolver families before requesting the certificate:

```bash
dig +short A thegreatlogout.org @1.1.1.1
dig +short AAAA thegreatlogout.org @1.1.1.1
dig +short A api.thegreatlogout.org @1.1.1.1
dig +short AAAA api.thegreatlogout.org @1.1.1.1
```

## 5. Request TLS and install the final site

Only continue once the records resolve directly to this server and the HTTP bootstrap is active:

```bash
sudo certbot certonly --webroot \
  --webroot-path /home/deploy/apps/thegreatlogout.org \
  --cert-name thegreatlogout.org \
  -d thegreatlogout.org \
  -d www.thegreatlogout.org \
  -d api.thegreatlogout.org

sudo install -m 0644 /home/deploy/apps/thegreatlogout.org/deploy/thegreatlogout.org.nginx /etc/nginx/sites-available/thegreatlogout.org
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
```

## 6. Activate analytics changes

The backend changes add The Great Logout origins, campaign dimensions, conversions, dashboard tables, and backups. Production runs from the clean, merged release worktree at `/home/deploy/apps/backend-release`; the dirty development worktree remains untouched. Install the service override and restart the shared backend:

```bash
sudo install -d -m 0755 /etc/systemd/system/backend.service.d
sudo install -m 0644 /home/deploy/apps/thegreatlogout.org/deploy/backend-thegreatlogout.override.conf /etc/systemd/system/backend.service.d/10-thegreatlogout-release.conf
sudo systemctl daemon-reload
sudo systemctl restart backend.service
curl --fail --silent http://127.0.0.1:8060/health
sudo systemctl status --no-pager backend.service
```

Enable the existing daily backup timer after the updated backup code is active. Its ZIP now contains consistent copies of the business database, analytics database, and The Great Logout guide database when those files exist:

```bash
sudo install -m 0644 /home/deploy/apps/thegreatlogout.org/deploy/netzl-backup.service /etc/systemd/system/netzl-backup.service
sudo install -m 0644 /home/deploy/apps/backend-release/deploy/systemd/netzl-backup.timer /etc/systemd/system/netzl-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now netzl-backup.timer
sudo systemctl start netzl-backup.service
sudo systemctl status --no-pager netzl-backup.timer netzl-backup.service
```

## 7. Verify the public migration

```bash
curl --fail --silent --show-error https://thegreatlogout.org/ >/dev/null
curl --fail --silent --show-error https://thegreatlogout.org/de/ >/dev/null
curl --fail --silent --show-error https://api.thegreatlogout.org/health
curl --head https://www.thegreatlogout.org/
curl --head http://thegreatlogout.org/
```

Confirm in a browser that analytics remain silent before consent, consent creates only `tgl_analytics_*` cookies, guide signup succeeds, the first email arrives, and an unsubscribe link works. Use an address owned by the tester.

After a stable observation period, disable GitHub Pages and remove Cloudflare Worker/D1 routes. Keep the old worker and `CNAME` file until that rollback window has passed.
