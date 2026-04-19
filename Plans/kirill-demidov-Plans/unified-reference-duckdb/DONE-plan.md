CREATED: 2026-04-19 | claude-sonnet-4-6
APPROVED: 2026-04-19 | claude-sonnet-4-6
DONE & IMPLEMENTED: 2026-04-19 | claude-sonnet-4-6

# План: unified-reference-duckdb

Цель: объединить ParlGov и CLEA в единый файл `reference.duckdb` через один последовательный ETL.
Убрать `parlgov.duckdb` + `clea_aggregated.duckdb`, ATTACH/DETACH, эндпоинт скачивания CLEA-файла.

---

## Корневая причина двух файлов

`ParlGovStore._con` и `CleaStore._con` — это два **одновременно открытых** write-соединения.
DuckDB допускает только одно write-соединение к файлу → SIGSEGV при попытке оба в один файл.

**Решение:** один `ReferenceStore` с одним `self._con`.
ETL последовательный: ParlGov → CLEA → `ref_party_election` — всё в одном соединении, нет конкурентных writer'ов.

---

## Шаг 1 — Создать `backend/app/reference_store.py`

**What:** Новый единый класс `ReferenceStore`, заменяет `ParlGovStore` + `CleaStore` + `reference_unified.py`.

**How:**

`_db_path()` → `{PARLGOV_DATA_DIR}/reference.duckdb` (дефолт: `/tmp/parlgov/reference.duckdb`).

`_ensure_loaded()` — ленивая инициализация:
1. WAL cleanup: если `reference.duckdb.wal` существует → удалить WAL + DB, пересобрать из CSV
2. `duckdb.connect(str(db_path))` — единственное write-соединение
3. Если `parliament_elections` view отсутствует → `_ingest_parlgov(con)`
4. Если CLEA CSV доступен и `clea_elections` таблица отсутствует/устарела → `_ingest_clea(con)`
5. Если `ref_party_election` отсутствует или schema неполная → `_rebuild_ref(con)`
6. Закэшировать `self._con = con`

`_ingest_parlgov(con, ve_path, el_path)`:
- Логика из `ParlGovStore._materialize_parliament` без вызова `rebuild_ref_party_election`

`_ingest_clea(con, csv_path)`:
- Логика из `CleaStore._rebuild` без вызова `rebuild_ref_party_election`
- Работает в том же `con`, таблицы `clea_elections`, `clea_party_national`, `clea_build_meta` создаются в `reference.duckdb`

`_rebuild_ref(con)`:
- UNION ALL прямо внутри одного соединения — нет `ATTACH`/`DETACH`
- ParlGov: `FROM parliament_elections LEFT JOIN election_meta`
- CLEA (если `clea_elections` есть): `FROM clea_party_national INNER JOIN clea_elections`

`refresh(force=False)`:
- Закрыть `self._con`
- HEAD к parlgov.org; если CSV новее или `force` → скачать
- Если CLEA CSV новее `clea_build_meta.source_mtime` или `force` → пересобрать CLEA
- Пересобрать `ref_party_election`
- Открыть `self._con` заново

Методы запросов (мигрируют из старых классов без изменения логики):
- `status()`, `list_countries()`, `list_elections()`, `list_unified_elections()`
- `election_detail(election_id)` — ParlGov
- `calculator_prefill(election_id)` — ParlGov
- `clea_election_detail(election_key)` — CLEA
- `clea_calculator_prefill(election_key)` — CLEA

Синглтон в конце файла: `_store = ReferenceStore()` / `get_reference_store()`.

---

## Шаг 2 — Обновить `backend/app/reference_api.py`

**What:** Заменить два store на один, удалить эндпоинт скачивания CLEA-duckdb.

**How:**
- Импорт: `from app.reference_store import get_reference_store` вместо двух старых
- Все обращения к `get_store()` → `get_reference_store()`
- Все обращения к `get_clea_store()` → `get_reference_store()`
- Удалить эндпоинт `GET /api/reference/clea/duckdb`
- `GET /api/reference/duckdb` → отдаёт `reference.duckdb` (имя в заголовке `reference.duckdb`)
- `POST /api/reference/refresh` → вызывает `store.refresh(force=force)` (один вызов)
- `GET /api/reference/status` → `store.status()` возвращает единый JSON

---

## Шаг 3 — Удалить старые файлы

**What:** Убрать три устаревших модуля.

**How:** Удалить:
- `backend/app/parlgov_duckdb.py`
- `backend/app/clea_duckdb.py`
- `backend/app/reference_unified.py`

---

## Шаг 4 — Обновить `docker-compose.yml`

**What:** Убрать `CLEA_DUCKDB_PATH`, тома без изменений (CLEA CSV всё ещё нужен как входной файл).

**How:**
- Удалить env var `CLEA_DUCKDB_PATH` (больше нет отдельного CLEA duckdb)
- Тома `./data/parlgov` и `./data/clea` остаются:
  - `data/parlgov/` — ParlGov CSV кэш + **`reference.duckdb`**
  - `data/clea/` — входной CSV CLEA (источник)
- `restart: unless-stopped` у `backend` уже есть → без изменений

---

## Шаг 5 — Обновить тесты

**What:** Переписать `test_reference_unified.py` под новую архитектуру.

**How:**
- Убрать тесты ATTACH/DETACH (больше не нужны)
- Добавить тест: `ReferenceStore` с только ParlGov-данными → `ref_party_election` содержит только `source='parlgov'`
- Добавить тест: `ReferenceStore` с ParlGov + CLEA CSV → оба source в `ref_party_election`
- Добавить тест: нет отдельного файла `clea_aggregated.duckdb` — всё в `reference.duckdb`
- `test_calc_regression.py` — без изменений

---

## Шаг 6 — Обновить `Plans/docs/project-context.md`

**What:** Актуализировать описание архитектуры DuckDB.

**How:**
- Раздел «Ключевой технический момент» → заменить на описание единого `reference.duckdb`
- Убрать упоминание `clea_aggregated.duckdb` и ATTACH/DETACH
- Обновить таблицу файлов репозитория (шаг 6)

---

---

## AFTER IMPLEMENTATION (2026-04-19)

**Создано:** `backend/app/reference_store.py` — единый `ReferenceStore` с одним `self._con` к `reference.duckdb`. ETL: ParlGov CSV → CLEA CSV → `ref_party_election` в одном соединении, нет ATTACH/DETACH.

**Удалено:** `parlgov_duckdb.py`, `clea_duckdb.py`, `reference_unified.py`.

**Обновлено:** `reference_api.py` (один импорт `get_reference_store`, убран эндпоинт `/clea/duckdb`), `test_reference_unified.py` (4 теста под новую архитектуру), `Plans/docs/project-context.md`.

**Проверки:** `python3 -m py_compile` — OK; `python3 -m pytest tests/ -v` — 8/8 passed.

**На проде при деплое:** старые `parlgov.duckdb` и `clea_aggregated.duckdb` в `data/` можно оставить — новый код их игнорирует. При первом старте/refresh создаётся `data/parlgov/reference.duckdb`.

---

## Зависимости и риски

- **Обратная совместимость:** эндпоинт `/api/reference/clea/duckdb` исчезает.
  Если фронт его вызывает — нужно проверить `Reference.tsx` (по контексту — не вызывает).
- **Данные на проде:** при деплое старые `parlgov.duckdb` и `clea_aggregated.duckdb`
  можно оставить в `data/` — новый код их игнорирует; `reference.duckdb` будет пересобран.
- **Размер WAL:** WAL-cleanup логика обязательна, копируется из `parlgov_duckdb.py`.
