# Контекст проекта mandate-allocation-calculator

CREATED: 2026-04-19 | claude-sonnet-4-6

---

## 1. Что за проект

**Назначение:** веб-сервис для сравнения распределения мандатов по правилам **Хэйра, Друпа, Сент-Лагю, Д'Ондта, Империали**; экспорт в Excel; публичный домен **electoral-calc.org**.

**Стек:**
- **Backend:** Python **FastAPI** (`backend/app/`) — расчёт, Excel, API справочника.
- **Frontend:** **Vite + React + TypeScript**, i18n **RU/EN** (`frontend/`).
- **Docker:** `docker-compose.yml` — сервисы **`backend`** и **`caddy`** (статика + прокси `/api` на бэкенд).
- **Прод-схема на дроплете:** Caddy слушает **127.0.0.1:9080** → снаружи **nginx** с `proxy_pass` на этот порт (чтобы не занимать 80/443 у других сайтов на том же IP).

**Legacy:** Streamlit вынесен в `legacy/`, не основной поток.

---

## 2. Справочник выборов (ParlGov + CLEA)

**ParlGov:** скачиваются `view_election.csv` и `election.csv`, в DuckDB — вью **`parliament_elections`**, таблица **`election_meta`** (даты, `votes_valid` и т.д.). Национальные парламентские выборы.

**CLEA:** опционально один **окружной UTF-8 CSV** (`CLEA_CSV_PATH` или файлы в `CLEA_DATA_DIR`). Агрегация до национального уровня, учёт **MAG**, порога, разбивки мест на пропорциональный пул (MAG>1) и окружной/одномандатный (MAG≤1), флаг **`CLEA_PR_ONLY`**. Результат пишется в **тот же** `reference.duckdb`.

**Единая таблица для аналитики и UI-списка:** **`ref_party_election`** в **`reference.duckdb`** — строка «выборы × партия»:

| Колонка | Смысл |
|--------|--------|
| `election_key` | уникальный ключ выборов |
| `election_date` | дата выборов |
| `election_label` | подпись (страна/название) |
| `party_name` | название партии |
| `votes_absolute` | голоса (оценка) |
| `vote_share_pct` | доля в % |
| `seats` | места |
| `source` | `parlgov` / `clea` |
| `threshold_pct` | порог (у CLEA при наличии; у ParlGov — NULL) |

### Ключевой технический момент: единый `reference.duckdb`

DuckDB не допускает два одновременных write-соединения к одному файлу. Исторически это приводило к SIGSEGV (exit 139) когда ParlGov и CLEA пытались писать в один файл.

**Текущая архитектура:** один класс `ReferenceStore` (`reference_store.py`) с одним `self._con`. ETL последовательный в одном соединении: ParlGov CSV → `parliament_elections` view → CLEA CSV → `clea_elections` / `clea_party_national` → `ref_party_election` (inline UNION ALL, без ATTACH). Файл — **`reference.duckdb`** в `PARLGOV_DATA_DIR`. Нет `parlgov.duckdb`, нет `clea_aggregated.duckdb`, нет ATTACH/DETACH.

### API (ключевые эндпоинты)

- `GET /api/health` — живость
- `GET /api/reference/status` — JSON `{ parlgov: {...}, clea: {...} }`
- `POST /api/reference/refresh?force=false` — ParlGov HEAD + CLEA mtime; сбрасывает кэш-соединения обоих store
- `GET /api/reference/countries` — список стран ParlGov
- `GET /api/reference/elections?...` — выборы только ParlGov
- **`GET /api/reference/unified-elections?...&source=parlgov|clea`** — единый список из `ref_party_election`
- `GET /api/reference/election/{id}` — партии и метаданные (ParlGov)
- `GET /api/reference/election/{id}/prefill` — предзаполнение калькулятора
- **`GET /api/reference/duckdb`** — скачивание `parlgov.duckdb` (в заголовке имя `reference.duckdb`)
- `GET /api/reference/clea/status|elections|detail|prefill` — совместимость с CLEA-блоком
- ~~`GET /api/reference/clea/duckdb`~~ — удалён (данные в едином `reference.duckdb`)

### Фронт (`Reference.tsx`)

- Одна таблица по `unified-elections`, фильтр источника (ParlGov / CLEA / все).
- Кнопка **«Скачать справочник (.duckdb)»** → `GET /api/reference/duckdb`.
- При отсутствии CSV CLEA — короткая подсказка `cleaOptionalHint` вместо большого блока «CLEA отключён».

### Docker-тома и права

В `docker-compose.yml` смонтированы:
```
./data/parlgov:/app/data/parlgov
./data/clea:/app/data/clea
```
Данные переживают перезапуск. uid приложения в образе — **1000**; при `Permission denied` на `.duckdb`:
```bash
chown -R 1000:1000 /opt/mandate-allocation-calculator/data/
```

---

## 3. Тесты и CI

| Файл | Что проверяет |
|------|--------------|
| `backend/tests/test_calc_regression.py` | Регрессия расчёта мандатов (Хэйр 60/40, порог, суммы) |
| `backend/tests/test_reference_unified.py` | `ref_party_election`: только ParlGov, только CLEA, оба + проверка `DETACH` |

- **`.github/workflows/tests.yml`** — unittest на push/PR.
- **`.github/workflows/deploy.yml`** — SSH на дроплет, `git pull`, `docker compose build && up -d` (по push в `master`/`main`).

---

## 4. Прод (DigitalOcean)

- Каталог проекта: **`/opt/mandate-allocation-calculator`**
- Контейнер `backend` — uid 1000 в образе; данные в `./data/parlgov` и `./data/clea`.

**Диагностика 502:**
```bash
ssh -i ~/.ssh/do_key root@<IP>
cd /opt/mandate-allocation-calculator
docker compose ps
docker logs mandate-allocation-calculator-backend-1 --tail=100
dmesg -T | tail -30 | grep -iE "oom|segfault|mandate"
```
Если exit 139 — segfault в duckdb.so (был баг с двумя writer → исправлен через ATTACH). Если OOM — смотреть память дроплета.

**Быстрый перезапуск бэкенда:**
```bash
cd /opt/mandate-allocation-calculator
docker compose up -d backend
```

---

## 5. Данные на проде

| Источник | Выборов | Строк (партий) | Примечание |
|----------|---------|----------------|------------|
| **ParlGov** | ~841 | ~6 807 | Скачивается автоматически с parlgov.org |
| **CLEA** | 1 | 2 | Синтетический тест-CSV (`data/clea/clea.csv`) — реального CLEA нет |

ParlGov на порядки богаче; CLEA можно подключить, положив реальный CSV в `data/clea/` и задав `CLEA_CSV_PATH`.

---

## 6. Важные файлы репозитория

```
backend/
  app/
    calc.py              — расчёт мандатов (Хэйр, Друп, Сент-Лагю, Д'Ондт, Империали)
    reference_store.py   — единый ReferenceStore: ParlGov + CLEA → reference.duckdb (один writer)
    reference_api.py     — FastAPI router /api/reference/*
    main.py              — FastAPI app, CORS, включение router
  tests/
    test_calc_regression.py
    test_reference_unified.py

frontend/
  src/
    pages/Reference.tsx  — справочник (unified-elections, детализация, переход в калькулятор)
    pages/Calculator.tsx — основной калькулятор
    api/client.ts        — fetch-обёртки (fetchUnifiedElections, referenceDuckdbDownloadHref, …)
    api/types.ts         — TypeScript-типы (UnifiedElectionRow, ReferenceElectionDetail, …)
    locales/ru.json, en.json — i18n-строки

docker-compose.yml
deploy/
  Dockerfile             — Caddy + статика React
  Caddyfile
  nginx-electoral-calc.conf.example
.github/workflows/
  tests.yml
  deploy.yml
Plans/
  kirill-demidov-Plans/electoral-calc-react-migration/plan.md
  docs/project-context.md  ← этот файл
data/
  clea/clea.csv           — синтетический тест-CSV
  parlgov/reference.duckdb — единый файл (создаётся при первом запуске, только на сервере)
```

---

## 7. Текущий статус и отложенное

**Сделано:** React+FastAPI, пять методов, Excel, ParlGov+CLEA unified, ATTACH-фикс, тесты, CI, деплой через Actions, nginx+certbot на дроплете.

**Отложено:**
- Эталон Бельгии в UI (нужны входные данные CLEA/ParlGov для конкретного сценария).
- Dependabot moderate по npm-зависимостям фронта (1 предупреждение из GitHub).
- Реальный CSV CLEA на проде (сейчас только синтетика).
