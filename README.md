# Mandate allocation calculator (electoral-calc.org)

Веб‑сервис для сравнения распределения мандатов по правилам **Хэйра**, **Друпа**, **Сент‑Лагю**, **Д'Ондта** и **Империали**. Фронтенд: **React (Vite)**, расчёты и Excel: **Python (FastAPI)**. Старый интерфейс на Streamlit лежит в каталоге `legacy/`.

## Быстрый старт (Docker)

1. Скопируйте `.env.example` в `.env` при необходимости.
2. Выполните:

```bash
docker compose up --build
```

3. Откройте **http://127.0.0.1:9080** — по умолчанию Caddy снаружи слушает только **loopback** и **не занимает** **80/443** на хосте. Так и задумано для обычного случая: на дроплете уже крутится **nginx** (или что-то ещё) на публичных портах, а этот стек живёт рядом как отдельный сервис за обратным прокси.

**Не путать с «Caddy на весь интернет»:** проброс `CADDY_PUBLISH=0.0.0.0:80` и TLS внутри Caddy имеют смысл **только** если машина **целиком** отдана под этот один сайт и на **80/443** никто больше не слушает. Если на том же IP другие сайты или сервисы — так делать нельзя; см. раздел ниже про nginx.

## Дроплет с несколькими сайтами (nginx + этот стек)

**Основная прод-схема из репозитория:** контейнеры публикуют приложение на **127.0.0.1:9080** (дефолт в `docker-compose.yml`). Системный **nginx** (или аналог) по-прежнему держит **80/443** для всего остального; для `electoral-calc.org` добавляется один `server` с `proxy_pass` на `http://127.0.0.1:9080`. Существующие виртуальные хосты не трогаются, кроме явно нового файла для домена калькулятора.

1. Поднимите контейнеры из каталога проекта (без правки системного nginx):

```bash
docker compose up -d --build
```

2. Скопируйте пример и вручную подключите его в nginx (после проверки `nginx -t` и `systemctl reload nginx`):

- `deploy/nginx-electoral-calc.conf.example`

3. Выпустите сертификат (когда DNS **A** уже указывает на IP дроплета), например: `certbot --nginx -d electoral-calc.org -d www.electoral-calc.org`.

## Локальная разработка без Docker

**API:**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Фронтенд** (проксирует `/api` на порт 8000):

```bash
cd frontend
npm install
npm run dev
```

## Продакшен: `electoral-calc.org` на DigitalOcean (чеклист)

Ниже описан **типичный** вариант: один дроплет, на нём уже **nginx** на **80/443** (другие проекты, лендинги, API за тем же IP). Калькулятор не претендует на эти порты: внутри Docker Caddy отдаёт сайт на **127.0.0.1:9080**, наружу домен ведёт **nginx** с TLS (certbot и т.п.).

### 1. DNS

У регистратора домена `electoral-calc.org`:

- Запись **A** для `@` (корень) → публичный **IPv4** дроплета.
- По желанию **A** для `www` → тот же IP (или **CNAME** `www` → `electoral-calc.org`).

Подождите распространения DNS (от минут до часов). Проверка: `dig +short electoral-calc.org A`.

### 2. Дроплет

- Ubuntu LTS, **Docker Engine** и плагин **Compose** ([официальная инструкция](https://docs.docker.com/engine/install/ubuntu/)).
- **Firewall** (`ufw`): открыты **22**, **80**, **443** (и что ещё нужно для других сервисов).

### 3. Код на сервере

```bash
sudo mkdir -p /opt/mandate-allocation-calculator
sudo chown "$USER":"$USER" /opt/mandate-allocation-calculator
cd /opt/mandate-allocation-calculator
git clone https://github.com/YOUR_LOGIN/mandate-allocation-calculator.git .
# или git remote + pull, если репозиторий приватный — настройте deploy key / SSH
```

Создайте `.env` в корне проекта (рядом с `docker-compose.yml`):

```env
# Caddy внутри контейнера — HTTP на :80; наружу только loopback (не конфликтует с nginx).
DOMAIN=:80

# Явно (можно не задавать — такой же дефолт в compose):
# CADDY_PUBLISH=127.0.0.1:9080

# Опционально: если хотите задать CORS вручную (иначе в backend уже зашиты https://electoral-calc.org и https://www.electoral-calc.org)
# CORS_ORIGINS=https://electoral-calc.org,https://www.electoral-calc.org
```

Запуск:

```bash
docker compose up -d --build
curl -sS http://127.0.0.1:9080/api/health
```

Должно вернуть `{"status":"ok"}`.

### 4. Nginx + HTTPS

1. Скопируйте пример в конфиг nginx (путь может отличаться, например Debian/Ubuntu):

   ```bash
   sudo cp deploy/nginx-electoral-calc.conf.example /etc/nginx/sites-available/electoral-calc.org
   sudo ln -sf /etc/nginx/sites-available/electoral-calc.org /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

2. Когда **A-запись** уже смотрит на IP дроплета, выпустите сертификат (пример с certbot для nginx):

   ```bash
   sudo certbot --nginx -d electoral-calc.org -d www.electoral-calc.org
   ```

3. Откройте в браузере: `https://electoral-calc.org` — лендинг, `/app` — калькулятор, `/api/health` — проверка API.

Если после включения HTTPS браузер ругается на API: убедитесь, что запросы идут на **тот же хост** (без смешения `www` и apex без редиректа) и что в ответах API не блокирует CORS — при пустом `CORS_ORIGINS` в backend уже разрешены `https://electoral-calc.org` и `https://www.electoral-calc.org`.

### Аналитика: Google Analytics 4 (бесплатно)

В [Google Analytics](https://analytics.google.com/) создайте ресурс **GA4** и поток для веб-сайта — получите идентификатор вида **`G-XXXXXXXXXX`**.

На сервере в `.env` рядом с `docker-compose.yml` добавьте:

```env
VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX
```

Затем пересоберите образ фронта (переменная подставляется на этапе **`docker compose build`**, не в рантайме):

```bash
docker compose build --no-cache caddy && docker compose up -d
```

Пока переменная не задана, счётчик **не подключается**. В отчётах GA4 будут страницы (включая SPA-маршруты `/`, `/app`, …), источники трафика, география и т.д. Локально при `npm run dev` можно положить то же имя в `frontend/.env` как `VITE_GA_MEASUREMENT_ID=...`.

### 5. GitHub Actions (автодеплой по push)

В репозитории на GitHub → **Settings → Secrets and variables → Actions** добавьте:

| Секрет | Смысл |
|--------|--------|
| `DO_HOST` | IP или хост SSH (часто IP дроплета) |
| `DO_USER` | пользователь SSH (`root` или `deploy`) |
| `DO_SSH_KEY` | приватный ключ PEM целиком |
| `DO_DEPLOY_PATH` | абсолютный путь к клону, например `/opt/mandate-allocation-calculator` |

На сервере у пользователя из `DO_USER` должны быть права на `docker compose` в этом каталоге и доступ к `git pull`.

Workflow (`.github/workflows/deploy.yml`) при push в **`master`** или **`main`** выполняет: `cd $DO_DEPLOY_PATH` → `git pull --ff-only` → `docker compose build` → `docker compose up -d`.

**Важно:** изменения должны быть **запушены** в GitHub; иначе на дроплете останется старый `git pull`.

### Отдельная машина целиком под этот сайт (редко)

Имеет смысл **только** если у вас **отдельный** дроплет или VM, где **кроме** этого проекта на **80/443** ничего не должно слушать (ни общий nginx, ни другой сайт на том же IP). Тогда можно опубликовать Caddy на `0.0.0.0:80` (в `.env`: `CADDY_PUBLISH=0.0.0.0:80`), при необходимости пробросить **443** в `docker-compose.yml` и выдать сертификат **внутри Caddy** (`DOMAIN=electoral-calc.org`).  

**Если на том же дроплете уже что-то работает на 80/443** — этот вариант не подходит: останьтесь на чеклисте выше (**127.0.0.1:9080** + nginx `proxy_pass`), иначе получите конфликт портов или сломаете соседние сервисы.

---

## Деплой на DigitalOcean + GitHub Actions (кратко)

См. раздел **«Продакшен: electoral-calc.org»** выше: клон, `.env`, `docker compose`, nginx, certbot, секреты Actions.

## API

- `GET /api/health` — проверка живости  
- `POST /api/calculate` — JSON с партиями и настройками  
- `POST /api/export.xlsx?lang=ru|en` — выгрузка таблицы в Excel  

Схемы см. в `backend/app/main.py`.

## Legacy Streamlit

```bash
pip install -r legacy/requirements-streamlit.txt
streamlit run legacy/streamlit_app.py
```

Запускайте из корня репозитория, чтобы находился `parties.json` (если используется).
