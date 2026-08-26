# Режим «Поиск трендов»

**Инструмент:** `tools/trend-finder/` — CLI на Python через YouTube Data API v3.
Полная документация — `tools/trend-finder/README.md` и `tools/trend-finder/SKILL.md`.

## Три под-режима

```bash
# 1. По ключевым словам (дефолт — только длинные видео)
.venv/bin/python trend_finder.py --search "Claude Code" --region RU --days 30 --min-ratio 5 --exclude-shorts

# 2. Канал конкурента (дефолт — только длинные)
.venv/bin/python trend_finder.py --channel @NickVels_AI --last 30 --exclude-shorts

# 3. Проверить свой список URL (образец формата — input/candidates-example.txt)
.venv/bin/python trend_finder.py --urls input/candidates-example.txt --min-ratio 5 --exclude-shorts

# Только Shorts (если явно просят)
.venv/bin/python trend_finder.py --search "Claude Code" --region RU --days 30 --only-shorts --min-ratio 10

# Оба формата (вперемешку, с пометкой Type в отчёте)
.venv/bin/python trend_finder.py --search "Claude Code" --region RU --days 30 --min-ratio 5
```

## Формат видео — ключевое правило

- Канал автора горизонтальный → по умолчанию **всегда `--exclude-shorts`**
- `--only-shorts` — только если пользователь явно выбрал «⚡ Shorts»
- Оба флага вместе — ошибка (argparse валидирует)
- Short определяется эвристикой: `duration ≤ 180 сек` (точность ~99%)

## Калибровка ratio для ниши Claude Code / AI / вайбкодинг

Верифицировано 2026-04-19 через YouTube Data API на 25 URL + 3 поисковых запроса + полный разбор канала @NickVels_AI:

| Ratio (views / subs) | Оценка |
|----------------------|--------|
| **×10+** | Явный вирус для этой ниши |
| **×5–10** | Сильный ролик |
| **<×3** | Органика (дошёл только до своей аудитории) |

**НЕ применяй порог ×50** — в этой нише он нереалистичен. У эталонного канала @NickVels_AI топ-ролик имеет ratio ×9.1, не ×50. Дефолтные флаги: `--min-ratio 5 --days 30 --exclude-shorts`.

**Для Shorts-прогонов — порог другой:** `--min-ratio 10` минимум.

## Куда сохранять

- **Сырые отчёты** по каждому запуску → `tools/trend-finder/output/trends-YYYY-MM-DD.md`
- **Сводный месячный отчёт** (если собираешь тренды за период) → `research/trends-YYYY-MM.md`

## Обязательный мост после отчёта

После того как выдал отчёт — **всегда** спроси через `AskUserQuestion`:

> «Хочешь сразу сделать сценарий по ТОП-1 теме? Варианты:
> 1. Да, запускаем режим 💡 Сценарий по идее по ТОП-1
> 2. Да, но возьмём ТОП-2 или ТОП-3
> 3. Нет, только отчёт — подумаю и выберу позже»
