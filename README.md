# Юридический мониторинг

Система ежедневного мониторинга законодательства: скачивает все акты за **последние 14 дней**, пропускает дубликаты, классифицирует по **настраиваемым зонам интереса** и выгружает в **Excel и Word**.

## Быстрый старт в PyCharm

### 1. Открыть проект

File → Open → выберите папку `legal-monitor`.

### 2. Создать виртуальное окружение

В PyCharm: File → Settings → Project → Python Interpreter → Add Interpreter → Virtualenv → OK.

Или в терминале:

```bash
cd legal-monitor
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install "greenlet>=3.1.0" --only-binary=:all:
pip install -r requirements.txt
pip install -e .
copy .env.example .env
```

> **Windows + Python 3.9:** если `pip install` падает на `greenlet`, выполните команду с `--only-binary=:all:` как выше.

### 3. Настроить окружение

```bash
copy .env.example .env
```

Опционально добавьте в `.env`:
- `OPENAI_API_KEY` — для умных пояснительных записок
- `DUMA_API_KEY` — для api.duma.gov.ru (без него работает RSS)

### 4. Настроить зоны интереса

**Способ А — файл** (удобно для правки в PyCharm):

Откройте `config/profiles.yaml`, включите/выключите профили (`enabled: true/false`), добавьте ключевые слова.

**Способ Б — интерактивное меню:**

Создайте Run Configuration в PyCharm:
- Script path: `scripts/menu.py`
- Working directory: корень проекта `legal-monitor`
- Python interpreter: `.venv`

Запустите → пункт **7. Настроить зоны интереса**.

### 5. Запустить

**Рекомендуется для первого теста:** `scripts/menu.py` → пункт **1. Полный цикл**.

Или через CLI:

```bash
python -m legal_monitor full
```

Результат: Excel в папке `output/`.

---

## Run Configurations для PyCharm

| Название | Script | Описание |
|----------|--------|----------|
| Menu | `scripts/menu.py` | Главное меню |
| Full cycle | Module: `legal_monitor`, Parameters: `full` | Полный цикл |
| Ingest only | Module: `legal_monitor`, Parameters: `ingest` | Только скачивание |
| Profiles | Module: `legal_monitor`, Parameters: `profiles` | Список профилей |

Для модуля: Run → Edit Configurations → + Python → Module name: `legal_monitor`, Parameters: `full`.

**Важно:** добавьте `src` в PYTHONPATH или установите пакет: `pip install -e .`

---

## Источники данных

| Источник | Включён по умолчанию | Метод |
|----------|---------------------|-------|
| publication.pravo.gov.ru | да | REST API |
| RSS Госдумы | да | RSS (без ключа) |
| regulation.gov.ru | да | REST API |
| sozd.duma.gov.ru | да | Playwright (браузер) |
| api.duma.gov.ru | нет | REST API (нужен ключ) |

Включение/выключение: `config/settings.yaml` → секция `sources`.

---

## Логика работы

1. **Каждый день** сканируются последние **14 дней** (`FETCH_WINDOW_DAYS`).
2. Скачиваются **все** документы со всех источников.
3. **Дубликаты** (тот же `source + external_id`) не сохраняются повторно.
4. Если текст изменился — запись **обновляется**.
5. Классификация по ключевым словам из профилей.
6. **Cleanup** (пункт 6 меню): удаляет документы старше 60 дней пакетом 14 дней.

---

## Структура проекта

```
legal-monitor/
├── config/
│   ├── settings.yaml      # Окно, источники, пороги
│   └── profiles.yaml      # Зоны интереса ← редактируйте здесь
├── scripts/
│   └── menu.py            # Главное меню для PyCharm
├── src/legal_monitor/
│   ├── connectors/        # pravo, duma, regulation, sozd
│   ├── pipeline/          # ingest, classify, export
│   └── cli.py             # CLI команды
├── data/                  # SQLite база + скачанные файлы
├── output/                # Excel отчёты
└── .env                   # Секреты (не коммитить)
```

---

## Команды CLI

```bash
python -m legal_monitor ingest     # Скачать
python -m legal_monitor classify   # Классифицировать
python -m legal_monitor export     # Excel/Word
python -m legal_monitor cleanup    # Очистка старых
python -m legal_monitor full       # Всё сразу
python -m legal_monitor profiles   # Список профилей
```

---

## Ежедневный запуск (Windows Task Scheduler)

Program: `C:\path\to\legal-monitor\.venv\Scripts\python.exe`  
Arguments: `-m legal_monitor full`  
Start in: `C:\path\to\legal-monitor`  
Trigger: ежедневно в 06:00.

---

## Troubleshooting

**СОЗД не отвечает:** установите Playwright: `playwright install chromium`. Или отключите в `config/settings.yaml`: `sozd: false`.

**Мало документов:** проверьте интернет и попробуйте только `pravo` + `duma_rss` (быстрее всего).

**Пустой Excel:** сначала запустите ingest, потом classify.

**Кириллица в консоли PyCharm:** Run → Edit Configurations → Environment → `PYTHONIOENCODING=utf-8`.
