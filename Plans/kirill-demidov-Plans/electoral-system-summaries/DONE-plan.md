CREATED: 2026-04-20 | claude-sonnet-4-6
APPROVED: 2026-04-20 | claude-sonnet-4-6
DONE & IMPLEMENTED: 2026-04-19 | claude-sonnet-4-6

# Plan: electoral-system-summaries

Цель: для каждой страны из справочника показывать в отдельной вкладке
краткую выжимку из избирательного закона (EN + RU) и ссылку на источник.
Генерация — через Claude API по кнопке в UI; результат кешируется в
`data/parlgov/country_summaries.json`.

---

## 1. Хранилище выжимок

**What:** JSON-файл `country_summaries.json` в data volume; один объект на
страну, ключ = `country_name_short` (ISO alpha-3, как в ParlGov).

**How:** Схема одной записи:
```json
{
  "DEU": {
    "summary_en": "Germany uses the D'Hondt method...",
    "summary_ru": "Германия использует метод д'Ондта...",
    "law_name": "Bundeswahlgesetz",
    "law_url": "https://...",
    "generated_at": "2026-04-20T10:00:00"
  }
}
```
Путь: `PARLGOV_DATA_DIR/country_summaries.json` (тот же volume что и
`reference.duckdb`). Создаётся при первой генерации; повторный запрос
перезаписывает запись для страны, остальные не трогает.

---

## 2. Сопоставление страна ↔ закон

**What:** Взять первый закон типа `electoral_system` для страны из
`electoral.db` (скрапер). Матчинг по имени страны через нормализацию.

**How:**
- `electoral.db` хранится локально (корень репо или volume) — не в Docker.
  В продакшене файла нет → для поиска закона читаем `electoral.db`, путь
  задаётся через env `ELECTORAL_DB_PATH` (опционально).
- Если `ELECTORAL_DB_PATH` не задан или файл не найден → `law_url = null`,
  генерируем выжимку только по названию страны и коду.
- Матчинг: `country_name` из `electoral.db` нормализуем (lower, strip) →
  сравниваем с `country_name` из ParlGov (`parliament_elections`).

---

## 3. Извлечение текста закона

**What:** Скачать страницу закона, извлечь читаемый текст (до ~6000 символов)
для передачи в Claude.

**How:**
- HTML: `fetch()` → BeautifulSoup → `get_text()` → первые 6000 символов.
- PDF (URL оканчивается на `.pdf`): попытка через `pdfminer.six`
  (`pip install pdfminer.six`); при ошибке → отправляем только URL и название.
- Таймаут 20 с; при любой ошибке → context = только название закона + страна.
- Отдельная утилита `extract_law_text(url) -> str` в `backend/app/`.

---

## 4. Генерация выжимки через Claude API

**What:** POST-запрос к Claude API с текстом закона → JSON `{en, ru}`.

**How:**
- Пакет `anthropic` добавить в `backend/requirements.txt`.
- Модель: `claude-haiku-4-5-20251001` (дёшево, достаточно для выжимки).
- Промпт (system):
  ```
  You are an expert in comparative electoral systems. Given a text excerpt
  from an electoral law, write a concise 2–3 sentence summary explaining:
  1. The electoral system type (PR, majoritarian, mixed).
  2. The seat allocation method (D'Hondt, Sainte-Laguë, Hare, etc.) if specified.
  3. The electoral threshold (%) if mentioned.
  Respond ONLY with valid JSON: {"en": "...", "ru": "..."}
  ```
- User message: `Country: {country_name}\nLaw: {law_name}\n\nText:\n{text}`
- Парсим JSON из ответа; при ошибке парсинга — берём raw text как `en`, `ru = ""`.

---

## 5. FastAPI эндпоинты

**What:** Два новых маршрута в `reference_api.py`.

**How:**

`GET /api/reference/summaries`
→ читает `country_summaries.json`, возвращает весь объект.
→ если файл не найден → `{}`.

`POST /api/reference/generate-summary`
Body: `{ "country_code": "DEU", "anthropic_key": "sk-ant-..." }`
→ ищет закон через `electoral.db` (если есть)
→ извлекает текст
→ вызывает Claude API с переданным ключом
→ дописывает запись в `country_summaries.json`
→ возвращает `{ "country_code": "DEU", "summary_en": "...", "summary_ru": "..." }`
→ ключ нигде не логируется и не сохраняется.

---

## 6. Фронтенд: вкладка «Electoral System»

**What:** В детализации выборов (`InlineDetail`) добавить переключатель вкладок;
вторая вкладка — выжимка из закона + ссылка.

**How:**
- Стейт `activeTab: "parties" | "system"` внутри `InlineDetail`.
- Табы: «Parties» / «Electoral System» (EN) | «Партии» / «Избирательная система» (RU).
- При открытии детализации: `GET /api/reference/summaries` → ищем запись по
  `country_code` выборов.
- Вкладка «Electoral System»:
  - Если запись есть: показываем текст на текущем языке + ссылку на закон.
  - Если нет: кнопка «Generate summary» → модалка с полем API key +
    «Generate» button → POST → при успехе показываем текст.
- Добавить ключи i18n:
  `ref.tabParties`, `ref.tabSystem`, `ref.generateSummary`,
  `ref.summaryApiKeyLabel`, `ref.summaryApiKeyPlaceholder`,
  `ref.summaryGenerating`, `ref.summaryLawSource`.

---

## 7. `backend/requirements.txt`

**What:** Добавить зависимости.

**How:**
```
anthropic>=0.25.0
pdfminer.six>=20221105
```

---

## Зависимости и риски

- `electoral.db` в продакшене недоступен без ручного копирования — деградация
  до генерации без текста закона (только по имени страны). Указать в README.
- Claude Haiku может не точно определить метод если в тексте нет явного
  упоминания — выжимка остаётся информативной на уровне типа системы.
- PDF-парсинг ненадёжен для scanned PDFs — деградация до title-only context.
- API ключ передаётся в теле HTTPS-запроса — не логируется, не сохраняется;
  пользователь несёт ответственность за стоимость запросов.
