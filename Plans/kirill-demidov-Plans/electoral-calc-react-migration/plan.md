CREATED: 2026-04-19 | claude-sonnet-4-6
APPROVED: 2026-04-19 | claude-sonnet-4-6

# План: mandate-allocation-calculator — React + Python API, Docker, DO, electoral-calc.org

Цель: убрать Streamlit, дать чистый академический UI (политология), лендинг на RU/EN, расчёты на Python, экспорт Excel, деплой в Docker на DigitalOcean дроплете с доменом `electoral-calc.org`, CI через GitHub Actions (push → SSH). Сохранение состояния на сервере не требуется.

---

## 1. Каркас репозитория и границы ответственности

**What:** Разделить текущий монолит `app.py` на бэкенд (API) и фронтенд (React), зафиксировать структуру каталогов и контракт API.

**How:** В корне репозитория завести, например, `backend/` (FastAPI, расчёты, Excel) и `frontend/` (Vite + React + TypeScript). Логику распределения мандатов вынести из `app.py` в импортируемые модули в `backend/` (реюз кода из `modeler.py` / перенос дублирующих функций из `app.py` с минимальным изменением алгоритмов). Streamlit-зависимости убрать из прод-пути бэкенда. Документировать JSON-схемы запрос/ответ для основного эндпоинта расчёта и для экспорта.

---

## 2. Бэкенд: FastAPI и эндпоинты

**What:** HTTP API для расчёта по выбранному методу и для выгрузки Excel; CORS только для своего домена (и localhost в dev).

**How:** Реализовать эндпоинт(ы): например `POST /api/calculate` (вход: партии, голоса/настройки, метод, порог и т.д. — по фактической модели из текущего UI) и `POST /api/export.xlsx` или `GET` с query/body по принятому дизайну, генерация через `openpyxl` или pandas+Excel writer. Валидация через Pydantic. Ошибки — структурированные JSON. Healthcheck `GET /api/health` для Docker/прокси.

---

## 3. Фронтенд: Vite + React, i18n, лендинг и приложение

**What:** Двуязычный лендинг с объяснением сервиса (RU/EN) и отдельный экран калькулятора в академическом визуальном стиле (нейтральная типографика, сдержанная палитра, читаемые таблицы и пояснения к методам).

**How:** React Router: маршрут `/` — лендинг, `/app` (или `/calculator`) — калькулятор. i18n: `react-i18next` или компактный слой JSON-локалей. Состояние ввода только в памяти браузера (без сохранения на сервере). Вызовы API через `fetch`/axios. Отображение результатов и текстов методов — по смыслу текущего Streamlit-приложения, но с новой компоновкой.

---

## 4. Контейнеризация и reverse proxy с TLS

**What:** Один сценарий запуска на дроплете: фронт как статика, бэкенд как процесс(ы), наружу — HTTPS на `electoral-calc.org`.

**How:** `docker-compose.yml`: сервис `backend` (образ из `backend/Dockerfile`), сервис `reverse-proxy` (например **Caddy** с автоматическим Let's Encrypt по домену или **nginx** + certbot по инструкции в README). Статику собрать на этапе CI или multi-stage: либо отдельный образ `frontend` с nginx только со статикой, либо копирование `dist/` в том же Caddy. Прокси: `/api/*` → backend, `/` → статика SPA с fallback на `index.html`.

---

## 5. Подготовка DigitalOcean «с нуля»

**What:** Дроплет с Docker, firewall, DNS, SSH для деплоя.

**How:** Документировать в README: создание дроплета (Ubuntu LTS), установка Docker Engine + Compose plugin, `ufw` (22 с ограничением по IP при желании, 80/443 открыты). В панели регистратора для `electoral-calc.org` — **A-запись** на публичный IP дроплета (и при необходимости `www`). Дождаться распространения DNS перед выпуском сертификата.

---

## 6. GitHub Actions: деплой по push

**What:** Автоматический деплой при push в основную ветку (например `master`/`main`).

**How:** Workflow: checkout → сборка фронта (Node) → сборка/публикация артефактов или сборка образов на runner; затем SSH на дроплет (секреты: `SSH_PRIVATE_KEY`, `HOST`, `USER`, при необходимости `KNOWN_HOSTS`). На сервере: `git pull` в каталоге приложения или `rsync`/`scp` docker-compose и контекстов; `docker compose build && docker compose up -d`. Альтернатива без registry: собирать образы на сервере по свежему коду — проще для одного дроплета. Секреты только в GitHub Secrets, не в репозитории.

---

## 7. Наблюдаемость, безопасность, чистка legacy

**What:** Минимально пригодный прод: логи, непривилегированный пользователь в контейнерах, удаление/архивация Streamlit из основного потока.

**How:** В Dockerfile `USER` non-root где возможно. Удалить или пометить deprecated `streamlit` из основного `requirements` бэкенда; опционально оставить ветку/тег со Streamlit или папку `legacy/` по желанию. Обновить корневой `README.md`: локальный запуск (`docker compose up`), переменные окружения (домен, `CORS_ORIGINS`), схема архитектуры.

---

## 8. Проверки перед закрытием (после реализации, STEP 5)

**What:** Убедиться, что функциональность соответствует заявленной.

**How:** Локально: `docker compose up`, ручная проверка лендинга RU/EN, сценарии расчёта для всех методов из README, скачивание Excel. На дроплете: HTTPS, редирект HTTP→HTTPS, проверка с мобильного/второй сети. Прогнать workflow на тестовом push (при необходимости — отдельная ветка с ограниченным trigger).

---

## Зависимости и риски

- Первичная настройка DNS и выпуск сертификата может занять время; Caddy упростает повторные попытки.
- Размер и дублирование логики в `app.py`/`modeler.py` потребуют аккуратного рефакторинга без изменения численных результатов (желательно зафиксировать эталонные входы/выходы в тестах).

---

## AFTER IMPLEMENTATION (2026-04-19)

**Сделано:** вынесена логика расчёта в `backend/app/calc.py` (эквивалент прежнего `app.py`), добавлен FastAPI (`/api/health`, `/api/calculate`, `/api/export.xlsx`), фронтенд Vite+React+TS с маршрутами `/` (лендинг RU/EN) и `/app` (калькулятор), стили под «академический» вид, `docker-compose` с сервисами `backend` и `caddy`, образ прокси собирает статику фронта, `deploy/Caddyfile` проксирует `/api` на бэкенд, добавлены `.dockerignore`, `.env.example`, обновлён корневой `README.md`, workflow `.github/workflows/deploy.yml` (SSH + `git pull` + `docker compose build/up`). Streamlit перенесён в `legacy/streamlit_app.py`.

**Проверки:** `npm run build` (frontend), импорт и вызов `calculate_mandates` из `backend`, `docker compose config`, `docker compose build` — успешно.

**На стороне пользователя:** создать A‑запись для `electoral-calc.org`, подготовить дроплет (Docker, клон репозитория, `.env` с `DOMAIN=electoral-calc.org`), добавить секреты GitHub Actions (`DO_HOST`, `DO_USER`, `DO_SSH_KEY`, `DO_DEPLOY_PATH`).

**Справочник выборов (ParlGov + CLEA):** реализовано; подробно — **раздел 9** ниже.

---

## 9. Справочник выборов (ParlGov + CLEA) — реализовано (апрель 2026)

**Цель:** экран «Справочник» с выборками ParlGov (национальные парламентские выборы из `view_election.csv`) и опционально CLEA (окружной CSV → агрегат в локальном DuckDB); показать порог из данных CLEA (с оговоркой), разделение мест на пропорциональный уровень и окружной/одномандатный по **MAG**, где это возможно; при переходе в калькулятор из CLEA использовать **только пропорциональный пул** мандатов, если он известен и больше нуля.

### 9.1. ParlGov (`backend/app/parlgov_duckdb.py`)

- Скачивание `view_election.csv` и `election.csv`, фильтр `election_type = parliament`, вью `parliament_elections`, `election_meta` для даты и `votes_valid`.
- `list_elections`, `election_detail`, `calculator_prefill` — доли и места по партиям.
- В экспорте ParlGov **нет** раздельных полей «пропорция / округа» — в `election_detail` явно отдаются `seats_pr_tier: null`, `seats_constituency_tier: null`.

### 9.2. CLEA (`backend/app/clea_duckdb.py`)

- Вход: CSV (`CLEA_CSV_PATH` или каталог `CLEA_DATA_DIR`), выход: файл DuckDB с агрегатами.
- Алиасы колонок: **MAG**, порог (`thr` и варианты), явное имя порога — **`CLEA_THRESHOLD_COL`**.
- **`CLEA_PR_ONLY`** (по умолчанию включён): при наличии MAG национальные голоса/свод по партиям для расчёта долей — **только строки с `mag > 1`**; без MAG — все строки, в метаданных предупреждение о смешанных системах.
- **`clea_elections`:** `seats_total`; **`seats_pr_tier`** / **`seats_constituency_tier`** — суммы `seat` по `mag > 1` и по `mag IS NULL OR mag <= 1`; без колонки MAG оба NULL; также `threshold_percent`, `threshold_column`, `pr_tier_mode`, `aggregation_note`, `threshold_note`.
- **`_clea_aggregate_schema_ok`:** проверка новых колонок → при обновлении кода **обязательная пересборка** DuckDB даже без смены mtime CSV.
- **Багфикс:** в SQL попадали буквальные `{thr_col_lit}` и т.п. — фрагмент после `+ ctr_n_sql +` для литералов переведён на **`f"""`**, чтобы f-интерполяция не обрывалась на первом `"""`.
- **`calculator_prefill`:** `totalMandates` = `seats_pr_tier`, если **> 0**; иначе `seats_total` или запасной дефолт. В **`meta`:** `seats_total_all_tiers`, разбивка мест, `calculator_mandates_tier` (`pr_mag_gt_1` / `all_seats`).

### 9.3. API (`backend/app/reference_api.py`)

- `/api/reference/*` (статус, страны, классические выборы ParlGov, деталь, префилл), **`GET /api/reference/unified-elections`** — единый список из `ref_party_election`, **`GET /api/reference/duckdb`** — скачивание `parlgov.duckdb` (в ответе имя `reference.duckdb`).
- `/api/reference/clea/*` — деталь, префилл, список по CLEA-файлу (совместимость); **`GET /api/reference/clea/duckdb`** — тот же файл CLEA или `reference.duckdb`, если путь совпал с объединённой выдачей (см. ниже).
- После **`POST /api/reference/refresh`** сбрасываются кэш-соединения обоих store, чтобы не держать устаревший lock.

### 9.3.1. Единая таблица `ref_party_election` (`backend/app/reference_unified.py`)

- В **`parlgov.duckdb`** (соединение ParlGov) пересобирается таблица **`ref_party_election`**: строка = выборы × партия; колонки: дата, подпись (страна), партия, голоса, доля %, места, **`source`** (`parlgov` / `clea`), **`threshold_pct`** (у CLEA при наличии).
- **CLEA не пишет в тот же файл**, что ParlGov (иначе два writer → SIGSEGV в `duckdb.so`). CLEA по-прежнему в **`clea_aggregated.duckdb`**; при сборке `ref_party_election` CLEA подключается через **`ATTACH ... (READ_ONLY)`** и затем **`DETACH`**.

### 9.4. Фронтенд

- `frontend/src/pages/Reference.tsx`, `frontend/src/api/types.ts`, локали `ru.json` / `en.json`.
- **Одна** таблица выборов по **`unified-elections`**: ключ/ID, дата, страна, действительные голоса (если есть в CLEA-сводке), места, **проп. / окр.** (заполнены только для строк CLEA с MAG), порог, **источник**, кнопка «Показать».
- Сноска `parlgovSeatsTierFoot`; при отсутствии CSV CLEA — короткая подсказка `cleaOptionalHint` (без отдельной панели «CLEA отключён»).
- В детализации — по-прежнему `seatsTierCleaSplit` / `seatsTierCleaNoMag` / `seatsTierParlgov`.

### 9.5. Оговорки

- Порог в constituency-файле CLEA **не всегда** тождествен юридическому национальному PR-порогу — сверка с **codebook** экспорта.
- Разбивка по **MAG** — эвристика CLEA; сложные смешанные системы могут потребовать другой выгрузки или ручной настройки.

### 9.6. Проверки по блоку справочника

- `python3 -m py_compile app/clea_duckdb.py app/parlgov_duckdb.py`; `npm run build` в `frontend/`.
- После деплоя/обновления кода: **обновить CLEA** (кнопка в UI или POST refresh), убедиться, что в таблице и в деталке отображаются числа разбивки, а не плейсхолдеры SQL.

---

## 10. Текущее состояние

**Git / прод:** справочник ParlGov+CLEA, MAG, порог, разбивка мест, фикс суммы %, демо `data/clea/clea.csv`, в **`docker-compose`** тома **`./data/parlgov`** и **`./data/clea`** (uid приложения **1000**). На дроплете: **`chown -R 1000:1000 data/`** при `Permission denied` на `.duckdb`.

**Два файла DuckDB + ATTACH:** `parlgov.duckdb` (ParlGov + таблица **`ref_party_election`**) и **`clea_aggregated.duckdb`** (агрегат из CSV). Объединение в `ref_party_election` только через **READ_ONLY ATTACH**, без второго writer на `parlgov.duckdb` (избегание **exit 139 / segfault**).

**Сделано при продолжении:** `backend/tests/test_calc_regression.py`; **`backend/tests/test_reference_unified.py`** — пересборка `ref_party_election` (ParlGov-only, CLEA-only, UNION + DETACH); workflow `.github/workflows/tests.yml` на push/PR.

**Отложено:** эталон Бельгии в UI — нужны полные входные данные CLEA/ParlGov для сценария.

---

## 11. Исправление локального окружения (2026-04-19)

**Проблема:** бэкенд локально «не отвечал» — фронтенд получал 404.

**Причина:** порт `8000` занят сторонним процессом (`/Users/kirilldemidov/playground/gdelt/server.py`). Vite dev-proxy смотрел на `127.0.0.1:8000`, поэтому запросы `/api/*` уходили в чужой сервер и получали `{"detail":"Not Found"}`.

**Исправлено:**
- `frontend/vite.config.ts` — proxy target изменён с `8000` → `8001`
- `README.md` — инструкция локального запуска обновлена: `--port 8001`

**Старт локально (актуальный):**
```bash
# Бэкенд
cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8001

# Фронтенд (в другом терминале)
cd frontend && npm run dev
```
Затем перезапустить Vite-сервер (если уже запущен) — изменение proxy вступает в силу только после рестарта.

**Прод (DigitalOcean):** найден и исправлен сегфолт — см. ниже.

### 11.1. Сегфолт на проде (exit 139) — DuckDB WAL

**Симптом:** `backend` поднимался, обрабатывал 2–3 запроса (`/api/health`, `/api/reference/status`) и падал с `Exited (139)`.

**Причина:** при предыдущем краше DuckDB не сделал checkpoint; файл `parlgov.duckdb.wal` (1.9 MB при основном DB 12 KB) остался в `data/parlgov/`. При следующем запуске DuckDB пытается реплеировать WAL → SIGSEGV в `duckdb 1.1.3`.

**Исправлено:**
- `backend/app/parlgov_duckdb.py`: при старте проверяет наличие `*.wal` файла — если есть, удаляет WAL и основной `.duckdb` до вызова `duckdb.connect()`, затем пересобирает из CSV.
- `docker-compose.yml`: добавлен `restart: unless-stopped` для `backend`.
- На сервере: вручную удалены `parlgov.duckdb` + `.wal`, бэкенд перезапущен.

**Деплой:** изменения закоммичены (`79aeda7`), задеплоены через `git pull` + `docker compose build/up -d`. Оба контейнера работают стабильно.
