# ZWMP Production Deployment

This directory contains production deployment examples for ZWMP.

Recommended deployment options:

1. Docker Compose: self-contained API, web frontend, nginx static server, Playwright runtime, and persistent data volume.
2. systemd + nginx: install dependencies on the host and run the API as a Linux service.

Media preview is browser-direct. ZWMP intentionally does not expose a backend media proxy endpoint.

## Docker Compose

Docker Compose is the simplest complete deployment path.

### Layout

```text
docker-compose.yml                 compose entrypoint
deploy/docker/api.Dockerfile        FastAPI + Playwright runtime image
deploy/docker/web.Dockerfile        Vite build + nginx static image
deploy/docker/nginx.conf            container nginx config
deploy/docker/compose.env.example   environment template
config/zwmp.config.json             mounted unified app config
zwmp-data                           named Docker volume for runtime data
```

### Configure

From the repository root:

```bash
cp deploy/docker/compose.env.example deploy/docker/compose.env
```

Edit `deploy/docker/compose.env` for runtime paths and legacy AI fallback settings.

Edit `config/zwmp.config.json` for:

- site copy and l10n strings
- SEO metadata
- public project and app links
- AI providers
- global and provider-specific AI quota

If `config/zwmp.config.json` defines AI providers, it overrides the legacy `ZWMP_AI_PROVIDER`, `ZWMP_AI_API_KEY`, and `ZWMP_AI_MODEL` environment variables.

### Build And Start

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:8080/
```

### Logs And Status

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f web
```

The API exposes a health check at:

```text
http://localhost:8080/api/health
```

### Stop And Upgrade

```bash
docker compose down
git pull
docker compose up -d --build
```

`docker compose down` keeps the named `zwmp-data` volume. To intentionally delete runtime data:

```bash
docker compose down -v
```

### Runtime Data

The default Compose file stores all runtime data in the `zwmp-data` named volume mounted at `/app/data`:

```text
/app/data/cache/zwmp.sqlite3
/app/data/generated-rules/
```

To use a host bind mount instead, replace the volume entry in `docker-compose.yml`:

```yaml
volumes:
  - ./data:/app/data
```

### Export Generated Rules

Generated rules are not publicly listed by the API. Export them from the container when you need self-hosted review or future ZWMP-Hub curation:

```bash
docker compose exec api python /app/scripts/export_rules.py \
  --source /app/data/generated-rules \
  --output /app/data/exports/zwmp-rules
```

The export preserves AI/local separation:

```text
/app/data/exports/zwmp-rules/
  ai/
  local/
  manifest.json
```

### Browser Runtime Notes

The API image uses the official Playwright Python base image and installs Chromium during build. The Compose file sets `shm_size: "1gb"` and `seccomp=unconfined` to reduce Chromium crashes in constrained container environments.

### Public HTTPS

For a public deployment, put a TLS reverse proxy in front of the `web` container and forward traffic to port `8080`, or adapt `deploy/nginx/zwmp.conf` for your host.

Example external nginx upstream:

```nginx
server {
    listen 443 ssl http2;
    server_name zwmp.example.com;

    ssl_certificate /etc/letsencrypt/live/zwmp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/zwmp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## systemd + nginx

Use this path when you want to run dependencies directly on a Linux host.

### Layout

Recommended paths:

```text
/opt/zwmp                application checkout
/opt/zwmp/data           runtime data, cache, generated rules
/opt/zwmp/.logs          optional service logs
/etc/zwmp/zwmp.env       environment file
/etc/zwmp/zwmp.config.json unified app config
```

### Build

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

### Configure

```bash
sudo install -d -o zwmp -g zwmp /etc/zwmp /opt/zwmp/data /opt/zwmp/.logs
sudo cp deploy/zwmp.env.example /etc/zwmp/zwmp.env
sudo cp config/zwmp.config.json /etc/zwmp/zwmp.config.json
```

Edit `/etc/zwmp/zwmp.config.json` for site SEO, l10n guidance, AI providers, and quota.

### systemd

```bash
sudo cp deploy/systemd/zwmp-api.service /etc/systemd/system/zwmp-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now zwmp-api
sudo systemctl status zwmp-api
```

### nginx

```bash
sudo cp deploy/nginx/zwmp.conf /etc/nginx/sites-available/zwmp.conf
sudo ln -s /etc/nginx/sites-available/zwmp.conf /etc/nginx/sites-enabled/zwmp.conf
sudo nginx -t
sudo systemctl reload nginx
```

Terminate TLS with certbot or your existing certificate automation. The nginx example intentionally does not define `/api/proxy`.
