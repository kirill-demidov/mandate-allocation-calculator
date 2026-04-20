# Mandate Allocation Calculator — electoral-calc.org

A web service for comparing parliamentary seat allocation under five methods: **Hare**, **Droop**, **Sainte-Laguë**, **D'Hondt**, and **Imperiali**. The frontend is built with **React (Vite)**; calculations and Excel export run on **Python (FastAPI)**. A legacy Streamlit interface lives in `legacy/`.

## Features

- **Calculator** — enter vote percentages, set total seats and an electoral threshold, get all five methods side by side. Export to Excel.
- **Election reference** — unified list of parliamentary elections from **ParlGov** (~800 elections, ~40 countries) and **CLEA** (constituency-level data aggregated by country). Click any election to prefill the calculator with real vote shares.
- **Electoral thresholds** — legal thresholds for ~46 countries are baked into the reference and pre-filled automatically when you open an election.
- **Electoral System tab** — each election detail includes a 2–3 sentence summary of the country's electoral system (EN + RU). Pre-generated for all threshold countries; regenerate via the UI with your own Anthropic API key.
- **Actual vs. theoretical** — when the reference prefills the calculator, a real seat column appears alongside the five theoretical methods. A collapsible note explains common reasons for divergence (district-level allocation, mixed systems, bonus seats, etc.).
- **i18n** — English and Russian, toggle in the UI.

---

## Quick start (Docker)

```bash
docker compose up --build
```

Open **http://127.0.0.1:9080**. By default Caddy binds only to loopback and does not occupy ports 80/443 on the host — designed for a droplet that already runs nginx for other sites.

---

## Production: electoral-calc.org on DigitalOcean

The standard setup: one droplet, nginx on 80/443 for all sites, this stack on **127.0.0.1:9080**, nginx proxies the calculator domain.

### 1. DNS

At your registrar for `electoral-calc.org`:
- **A** record for `@` → droplet's public IPv4
- **A** for `www` → same IP (or **CNAME** `www` → `electoral-calc.org`)

Verify with `dig +short electoral-calc.org A`.

### 2. Droplet

- Ubuntu LTS, **Docker Engine** + Compose plugin ([official guide](https://docs.docker.com/engine/install/ubuntu/))
- **ufw**: ports **22**, **80**, **443** open

### 3. Clone and configure

```bash
sudo mkdir -p /opt/mandate-allocation-calculator
sudo chown "$USER":"$USER" /opt/mandate-allocation-calculator
cd /opt/mandate-allocation-calculator
git clone https://github.com/YOUR_LOGIN/mandate-allocation-calculator.git .
```

Create `.env` next to `docker-compose.yml`:

```env
# Caddy serves HTTP on :80; only exposed on loopback — no conflict with nginx.
DOMAIN=:80
# CADDY_PUBLISH=127.0.0.1:9080   # default; change only if needed

# Optional: override CORS (defaults already include https://electoral-calc.org)
# CORS_ORIGINS=https://electoral-calc.org,https://www.electoral-calc.org

# Optional: Google Analytics 4
# VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX
```

Start:

```bash
docker compose up -d --build
curl -sS http://127.0.0.1:9080/api/health   # → {"status":"ok"}
```

### 4. Nginx + HTTPS

```bash
sudo cp deploy/nginx-electoral-calc.conf.example /etc/nginx/sites-available/electoral-calc.org
sudo ln -sf /etc/nginx/sites-available/electoral-calc.org /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d electoral-calc.org -d www.electoral-calc.org
```

Then open `https://electoral-calc.org` (landing), `/app` (calculator), `/reference` (election reference).

### 5. GitHub Actions (auto-deploy on push)

Add these secrets in **Settings → Secrets and variables → Actions**:

| Secret | Value |
|--------|-------|
| `DO_HOST` | droplet IP or hostname |
| `DO_USER` | SSH user (`root` or `deploy`) |
| `DO_SSH_KEY` | full PEM private key |
| `DO_DEPLOY_PATH` | e.g. `/opt/mandate-allocation-calculator` |

Workflow (`.github/workflows/ci.yml`) on push to `master`: `git pull` → `docker compose build` → `docker compose up -d`.

### Single-server setup (Caddy handles TLS)

Only if this is the **only** site on the machine and nothing else listens on 80/443. Set `CADDY_PUBLISH=0.0.0.0:80` and `DOMAIN=electoral-calc.org` in `.env`; Caddy will obtain the certificate itself.

---

## Local development (without Docker)

**Backend:**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

**Frontend** (proxies `/api` to port 8001):

```bash
cd frontend
npm install
npm run dev
```

---

## Election reference (ParlGov + CLEA)

On first backend start the app downloads **ParlGov** CSVs and builds a local **DuckDB** file (`reference.duckdb` in the Docker volume `./data/parlgov` — survives restarts). On the reference page you can filter by country, date range, source (ParlGov / CLEA), and open any election directly in the calculator.

**Electoral thresholds** for ~46 countries (ISO alpha-3 codes) are stored in `backend/app/thresholds.json` and baked into `ref_party_election` at build time via a SQL JOIN. They are pre-filled when you open an election from the reference.

### CLEA (constituency-level data)

Place a UTF-8 CSV (standard CLEA layout) and set **`CLEA_CSV_PATH`** or **`CLEA_DATA_DIR`** (see `.env.example`). The backend aggregates it into `ref_party_election` alongside ParlGov:

- valid votes summed per country/election date
- party vote shares and estimated votes
- seats summed across constituencies (if `seat` column present)
- threshold from `tm` / `threshold` column (values 0–1 treated as fractions, converted to %)

Expected column names (case-insensitive, aliases supported): `ctr`, `yr`, `cst` (required), `pv1`, `vv1`, optionally `mn`, `dy`, `pty_n`/`pty`, `seat`, `tm`, `ctr_n`.

---

## Electoral system summaries

The **Electoral System** tab in the election detail shows a 2–3 sentence summary of the country's electoral system in the current language (EN / RU), plus a link to the source law if available.

**Pre-generated summaries** for all ~46 threshold countries are bundled in `backend/app/bundled_summaries.json` and served out-of-the-box without any API key.

**User-generated summaries** (via the "Generate summary" button in the UI) call the Anthropic API with a key the user supplies in the modal. They are stored in `PARLGOV_DATA_DIR/country_summaries.json` and override the bundled ones per country.

### Batch-generate summaries

To pre-generate summaries for all countries at once (hitting the live API):

```bash
python3 generate_all_summaries.py --api-key sk-ant-...
# or against a local instance:
python3 generate_all_summaries.py --api-key sk-ant-... --base-url http://localhost:8000
```

Skips countries that already have a summary. Use `--force` to regenerate all.

### Electoral laws database (optional)

`electoral_laws.py` in the repo root scrapes electoral law URLs from GLOBALCIT, ACE Project, and IFES into a local **SQLite** file (`electoral.db`). When `ELECTORAL_DB_PATH` points to this file in production, the summary generator can fetch and extract law text to give Claude better context.

```bash
python3 electoral_laws.py          # run scraper, creates/updates electoral.db
python3 electoral_laws.py --help   # options
```

Without `electoral.db` the system degrades gracefully: summaries are generated from country name only.

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | liveness check |
| POST | `/api/calculate` | seat allocation for given parties and settings |
| POST | `/api/export.xlsx?lang=ru\|en` | Excel export |
| GET | `/api/reference/status` | `{ parlgov: {...}, clea: {...} }` |
| POST | `/api/reference/refresh?force=false` | check ParlGov (HEAD) and CLEA (mtime); rebuild if updated |
| GET | `/api/reference/countries` | list of countries |
| GET | `/api/reference/unified-elections` | combined ParlGov + CLEA list (`ref_party_election`) |
| GET | `/api/reference/elections` | ParlGov-only list |
| GET | `/api/reference/election/{id}` | parties and metadata |
| GET | `/api/reference/election/{id}/prefill` | calculator prefill JSON |
| GET | `/api/reference/duckdb` | download `reference.duckdb` |
| GET | `/api/reference/summaries` | all stored electoral-system summaries |
| POST | `/api/reference/generate-summary` | generate summary for one country via Claude API |
| GET | `/api/reference/clea/status` | CLEA CSV presence and aggregated DuckDB path |
| GET | `/api/reference/clea/elections` | CLEA-only election list |
| GET | `/api/reference/clea/detail` | CLEA party breakdown |
| GET | `/api/reference/clea/prefill` | CLEA calculator prefill |
| GET | `/api/reference/clea/duckdb` | download `clea_aggregated.duckdb` |

Full schemas in `backend/app/main.py` and `backend/app/reference_api.py`.

---

## Data sources

- **ParlGov** — Döring, Quaas, Hesse, Manow — *Parliaments and governments database*, [parlgov.org](https://www.parlgov.org/). CC-BY-SA. Covers 800+ parliamentary elections across ~40 democracies.
- **CLEA** — Constituency-Level Elections Archive, [electiondataarchive.org](https://electiondataarchive.org/). Constituency-level data aggregated by country.
- **Electoral thresholds** — compiled from constitutions and electoral laws; verify before citing.
- **Electoral system summaries** — generated via Claude (Anthropic); bundled summaries based on established academic knowledge of electoral systems.

---

## Legacy Streamlit

```bash
pip install -r legacy/requirements-streamlit.txt
streamlit run legacy/streamlit_app.py
```

Run from the repo root so `parties.json` is found if used.
