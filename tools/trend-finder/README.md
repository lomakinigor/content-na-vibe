# YouTube Trend Finder

CLI для поиска трендовых видео по критерию `views / subscribers ≥ N` через YouTube Data API v3.

## Зачем

Найти в нише (AI, Claude Code, вайбкодинг и т.п.) ролики, которые алгоритм YouTube раздал сильно за пределы ядра канала — потенциал вирального контента. Точные метрики, а не догадки.

## Установка

```bash
cd tools/trend-finder
pip install -r requirements.txt
cp .env.example .env
# вписать YOUTUBE_API_KEY в .env
```

## Как получить YouTube Data API ключ (3 минуты)

1. Открой [console.cloud.google.com](https://console.cloud.google.com)
2. Верхняя панель → **Select a project** → **NEW PROJECT** → назови `youtube-trends` → **Create**
3. В поиске: «YouTube Data API v3» → **ENABLE**
4. Слева: **APIs & Services** → **Credentials** → **CREATE CREDENTIALS** → **API key**
5. Скопируй ключ (вид `AIzaSy...`)
6. Нажми **Restrict Key** → API restrictions → выбери только «YouTube Data API v3» → Save

Положи ключ в `.env`:
```
YOUTUBE_API_KEY=AIzaSy...
```

**Квота:** 10,000 units/день бесплатно. 25 URL = ~50 units. Хватит с запасом.

## Использование

### Режим 1: проверить список URL
```bash
python3 trend_finder.py --urls input/candidates.txt --min-ratio 5 --days 60 --exclude-shorts
```

Формат `candidates.txt` — по одному URL на строку:
```
https://www.youtube.com/watch?v=sx6ZSbc51gY
https://www.youtube.com/watch?v=MieTeHQmXMs
https://youtu.be/pJylXFAC87A
```

### Режим 2: поиск по запросу
```bash
# Только длинные (по умолчанию для нашего канала)
python3 trend_finder.py --search "Claude Code tutorial" --min-ratio 5 --days 30 --region RU --exclude-shorts

# Только Shorts — если нужны идеи для вертикальных
python3 trend_finder.py --search "Claude Code tutorial" --min-ratio 10 --days 30 --region RU --only-shorts
```

### Режим 3: трекать канал конкурента
```bash
python3 trend_finder.py --channel @NickVels_AI --last 20 --exclude-shorts
```

## Флаги

| Флаг | Описание | По умолчанию |
|------|----------|--------------|
| `--urls FILE` | Режим: прогнать список URL | — |
| `--search "query"` | Режим: поиск по запросу | — |
| `--channel @handle` | Режим: последние видео канала | — |
| `--last N` | Сколько видео с канала брать (только для --channel) | 20 |
| `--min-ratio N` | Фильтр: views/subs ≥ N | 0 |
| `--min-views N` | Фильтр по просмотрам | 0 |
| `--days N` | Только за последние N дней | 60 |
| `--region CODE` | Регион: `RU`, `US`, `worldwide` | `worldwide` |
| `--exclude-shorts` | Исключить Shorts (длительность ≤ 180 сек) | off |
| `--only-shorts` | Только Shorts (длительность ≤ 180 сек) | off |
| `--output PATH` | Путь к итоговому .md | `output/trends-YYYY-MM-DD.md` |

`--exclude-shorts` и `--only-shorts` взаимоисключающие (argparse падает если указать оба).

## Вывод

Markdown-таблица, отсортированная по ratio. Колонка `Type` показывает формат:

```markdown
| # | Type | Title | Channel | Views | Subs | Ratio | Views/h | Date | URL |
|---|------|-------|---------|-------|------|-------|---------|------|-----|
| 1 | 🎬 Long | ... | ... | 1.2M | 15K | ×80 | 500 | 2026-04-10 | ... |
| 2 | ⚡ Short | ... | ... | 600K | 8K | ×75 | 1200 | 2026-04-15 | ... |
```

## Ограничения

- **Скрытые подписчики:** часть каналов скрывает subs. Такие видео попадают в отдельную секцию отчёта (без ratio).
- **YouTube search max 50 за запрос:** для большего покрытия использует пагинацию (до 3 страниц = 150 видео).
- **Как определяется Short:** эвристика `duration ≤ 180 секунд`. Точность ~99% для обычного контента. Редкие 2-3-минутные горизонтальные ролики могут ошибочно попасть в Shorts — для 100% точности нужна доп. проверка через HTTP HEAD (сейчас не реализовано).
- **Views/hour информативен первые 7 дней** после публикации.
