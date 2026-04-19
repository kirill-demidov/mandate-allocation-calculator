CREATED: 2026-04-19 | claude-sonnet-4-6
APPROVED: 2026-04-19 | claude-sonnet-4-6
DONE & IMPLEMENTED: 2026-04-19 | claude-sonnet-4-6

# План: calculator-improvements-landing-expansion

Три связанных улучшения:
1. Автоподстановка порога из справочника → калькулятор
2. Колонка «Реальный результат» в таблице калькулятора
3. Расширение лендинга: секции «Источники» и «Методы»

---

## Шаг 1 — Автоподстановка порога (Reference.tsx)

**What:** При открытии ParlGov-выборов из unified-списка — подставлять `row.threshold_percent` в стейт `threshold`, а не сбрасывать в 0.

**How:**
- `onPickUnified` уже имеет `row: UnifiedElectionRow` с полем `threshold_percent`
- Передать его в `onPickElection(id, key, threshold)` как третий параметр
- Внутри `onPickElection`: `setThreshold(threshold ?? 0)` вместо `setThreshold(0)`
- Обновить i18n: `ref.thresholdHint` → убрать «задайте вручную», написать что порог подставляется автоматически для известных стран

---

## Шаг 2 — Реальный результат: бэкенд (reference_store.py)

**What:** Добавить `seatsRecorded` к каждой партии в ответах `calculator_prefill` и `clea_calculator_prefill`.

**How:**
- `calculator_prefill`: в цикле по `detail["parties"]` брать `seats_recorded` → включить в `parties_out` как `"seatsRecorded": int | None`
- `clea_calculator_prefill`: аналогично — `seats_recorded` уже есть в `detail["parties"]`
- Тип ответа остаётся совместимым (новое поле опционально)

---

## Шаг 3 — Реальный результат: фронт

**What:** Показать колонку «Факт» / «Actual» в таблице результатов калькулятора, когда данные о реальных местах доступны.

**How:**

**`frontend/src/api/types.ts`:**
- `ReferencePrefillResponse.parties` → добавить `seatsRecorded?: number | null`

**`frontend/src/types/calculatorPrefill.ts`:**
- `CalculatorPrefillState.parties` → добавить `seatsRecorded?: number | null`

**`frontend/src/pages/Reference.tsx`:**
- При построении `CalculatorPrefillState` включить `seatsRecorded` из prefill-ответа

**`frontend/src/pages/Calculator.tsx`:**
- Локальный тип party-стейта → добавить `seatsRecorded?: number | null`
- При загрузке `location.state` (prefill) — сохранить `seatsRecorded` в party-стейт
- В таблице результатов: если хоть у одной партии `seatsRecorded != null` → показать колонку «Факт» между «Голоса %» и «Хэйр»
- Значение в ячейке: `seatsRecorded ?? "—"` (совмещается с партией по имени)
- `colgroup`: добавить `<col>` для новой колонки (только когда видима)

**`frontend/src/locales/ru.json` + `en.json`:**
- `table.actual`: `"Факт"` / `"Actual"`
- `table.actualTitle`: `"Реальный результат (из источника)"` / `"Actual seats (from source)"`

---

## Шаг 4 — Расширение лендинга

**What:** Две новые подробные секции на лендинге: «Источники данных» и «Методы в деталях».

**How:**

**Секция «Источники данных»** (после текущей `refTitle`/`refP1`/`refP2`):
- Подзаголовок `landing.sourcesTitle`
- ParlGov: что это, сколько выборов, ссылка на parlgov.org
- CLEA: что это, окружной уровень → агрегация, ссылка на electiondataarchive.org
- Оговорка про качество данных (academic use)

**Секция «Методы в деталях»** (вместо одного абзаца `methodsList` — расширить до карточек/списка):
- Сохранить краткий вводный абзац `methodsList` как есть
- Добавить `landing.methodsDetail` — список из 5 пунктов: название метода + 1–2 предложения (более детально чем сейчас, менее детально чем на странице калькулятора)
- Ключи: `landing.methodsDetailHare`, `landing.methodsDetailDroop`, `landing.methodsDetailSL`, `landing.methodsDetailDHondt`, `landing.methodsDetailImp`

**`Landing.tsx`:**
- Добавить `<ul>` / `<dl>` для методов со ссылкой на `/app` (калькулятор)
- Добавить блок источников с внешними ссылками (target="_blank")

**`ru.json` + `en.json`:**
- Новые ключи под `landing.*` для обеих секций
- Ссылки вшиты в JSX (не в локали)

---

## Шаг 5 — Проверки

**What:** Убедиться что всё работает end-to-end.

**How:**
- `npm run build` в `frontend/` — нет TS-ошибок
- Локально: открыть справочник → выбрать ParlGov-выборы → убедиться что порог подставился
- Открыть калькулятор из справочника → убедиться что колонка «Факт» появилась с числами
- Открыть калькулятор напрямую (без prefill) → колонка «Факт» отсутствует
- Лендинг: обе секции отображаются на RU и EN, ссылки работают

---

## Зависимости

Шаг 1 независим. Шаг 2 нужен до Шага 3. Шаг 4 независим.
Порядок реализации: 1 → 2 → 3 → 4 → 5.
