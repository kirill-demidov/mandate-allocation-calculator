CREATED: 2026-04-20 | claude-sonnet-4-6
APPROVED: 2026-04-20 | claude-sonnet-4-6
DONE & IMPLEMENTED | 2026-04-20 | claude-sonnet-4-6

# Plan: electoral-laws-collector

Цель: одиночный скрипт `electoral_laws.py` в корне репозитория.
При запуске собирает ссылки на тексты избирательных законов из трёх источников
(GLOBALCIT → ACE → IFES), пишет в SQLite + CSV + отчёт покрытия.
ACE и IFES дополняют страны из GLOBALCIT новыми ссылками, не пропускаются.

---

## 1. Инициализация БД и вспомогательные утилиты

**What:** Схема SQLite (`countries`, `electoral_laws`), функции upsert, HTTP-обёртка с кешем.

**How:**
- `init_db(conn)` — CREATE TABLE IF NOT EXISTS по схеме из ТЗ.
- `upsert_country(conn, name, iso2, region) -> int` — INSERT OR IGNORE + SELECT id.
- `upsert_law(conn, country_id, name, url, lang, source)` — INSERT OR REPLACE по UNIQUE(country_id, law_url).
- `fetch(url, cache=True) -> str` — сохраняет HTML в `./cache/{md5(url)}.html`; при повторном вызове читает из кеша; sleep 1s между сетевыми запросами; ошибки → `scrape_errors.log`, возвращает `""`.

---

## 2. Скрапер GLOBALCIT

**What:** Разобрать таблицу на `https://globalcit.eu/national-electoral-laws/`, извлечь страну, название закона, URL документа, язык.

**How:**
- `fetch()` страницы → BeautifulSoup.
- Найти основную таблицу (`<table>` или `<tbody>`), итерировать строки.
- Из каждой строки: колонка страны → `upsert_country`; колонка названия закона + ссылки → `upsert_law(..., source="GLOBALCIT")`.
- Печатать прогресс: `GLOBALCIT: {country} — {n} laws`.

---

## 3. Скрапер ACE

**What:** Обойти `https://aceproject.org/epic-en`, для каждой страны найти раздел "Legal Framework" и извлечь ссылки на законы.

**How:**
- `fetch()` индексной страницы → найти ссылки на страницы стран.
- Для каждой страны: `fetch()` страницы страны → найти секцию "Legal Framework" → извлечь ссылки (href + текст ссылки).
- `upsert_country` + `upsert_law(..., source="ACE")` — INSERT OR REPLACE, дублирование по URL не создаст второй записи.
- Прогресс: `ACE: {country} — {n} laws`.

---

## 4. Скрапер IFES

**What:** Обойти `https://www.electionguide.org/countries/`, для каждой страны найти "Legal Framework" / "Electoral Law" ссылки.

**How:**
- `fetch()` индекса стран → список ссылок на страницы стран.
- Для каждой: `fetch()` страницы → найти секцию "Legal Framework" или "Electoral Law" → ссылки.
- `upsert_country` + `upsert_law(..., source="IFES")`.
- Прогресс: `IFES: {country} — {n} laws`.

---

## 5. Экспорт CSV и отчёт покрытия

**What:** `electoral_laws.csv` + `laws_coverage_report.txt`.

**How:**
- `export_csv(conn)` — SELECT JOIN countries + electoral_laws → запись в CSV с заголовками.
- `write_coverage_report(conn)` — считает:
  - всего стран в БД
  - стран с хотя бы одним законом (список)
  - стран без законов (список)
  - разбивка по source: GLOBALCIT N, ACE N, IFES N
  - печатает в stdout и пишет в `laws_coverage_report.txt`.

---

## 6. `__main__` и зависимости

**What:** Точка входа, автоустановка зависимостей.

**How:**
- Попытка `import requests, bs4`; при ImportError — `subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4"])` + повторный import.
- `os.makedirs(CACHE_DIR, exist_ok=True)`.
- `logging.basicConfig(filename="scrape_errors.log", level=logging.ERROR)`.
- Последовательно: `init_db` → `scrape_globalcit` → `scrape_ace` → `scrape_ifes` → `export_csv` → `write_coverage_report` → `conn.close()`.

---

## AFTER IMPLEMENTATION (2026-04-20)

`electoral_laws.py` создан в корне репозитория (~330 строк). Реализовано:
- автоустановка `requests` + `beautifulsoup4` при первом запуске
- HTTP-кеш в `./cache/` (md5 URL), rate-limit 1s между запросами, ошибки в `scrape_errors.log`
- `init_db` / `upsert_country` / `upsert_law` (UNIQUE(country_id, law_url) — дедупликация)
- `scrape_globalcit` — таблица GLOBALCIT + fallback по заголовкам если JS-рендер
- `scrape_ace` — индекс стран ACE → каждая страница → секция "Legal Framework"
- `scrape_ifes` — индекс стран IFES ElectionGuide → секция "Electoral Law"
- `export_csv` → `electoral_laws.csv`, `write_coverage_report` → `laws_coverage_report.txt`
- Проверки: синтаксис OK, DB-слой (dedup, уникальность), отчёт покрытия — все прошли.

---

## Зависимости и риски

- Структура HTML GLOBALCIT/ACE/IFES может отличаться от ожидаемой → скраперы должны логировать предупреждения, не падать.
- IFES может требовать JavaScript — проверить при реализации; при необходимости перейти на статический URL-паттерн страниц.
- Кеш делает повторные запуски дешёвыми; при изменении структуры сайта — очистить `./cache/`.
