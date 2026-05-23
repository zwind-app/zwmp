# ZWMP Production Deployment

This directory provides a minimal Linux deployment shape using systemd and nginx.

## Layout

Recommended paths:

```text
/opt/zwmp                application checkout
/opt/zwmp/data           runtime data, cache, generated rules
/opt/zwmp/.logs          optional service logs
/etc/zwmp/zwmp.env       environment file
/etc/zwmp/zwmp.config.json unified app config
```

## Build

```bash
cd /opt/zwmp/apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e ../../packages/rule-core -e ".[browser]"
python -m playwright install chromium

cd /opt/zwmp/apps/web
npm ci
npm run build
```

## Configure

```bash
sudo install -d -o zwmp -g zwmp /etc/zwmp /opt/zwmp/data /opt/zwmp/.logs
sudo cp deploy/zwmp.env.example /etc/zwmp/zwmp.env
sudo cp config/zwmp.config.json /etc/zwmp/zwmp.config.json
```

Edit `/etc/zwmp/zwmp.config.json` for site SEO, l10n guidance, AI providers, and quota.

## systemd

```bash
sudo cp deploy/systemd/zwmp-api.service /etc/systemd/system/zwmp-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now zwmp-api
sudo systemctl status zwmp-api
```

## nginx

```bash
sudo cp deploy/nginx/zwmp.conf /etc/nginx/sites-available/zwmp.conf
sudo ln -s /etc/nginx/sites-available/zwmp.conf /etc/nginx/sites-enabled/zwmp.conf
sudo nginx -t
sudo systemctl reload nginx
```

Terminate TLS with certbot or your existing certificate automation. The nginx example intentionally does not define `/api/proxy`; media URLs are browser-direct.
