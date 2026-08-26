#!/usr/bin/env python3
"""
Чистит транскрипт YouTube (SRT автосубтитры) через Claude Sonnet 5 (OpenRouter).

Что делает:
  - Парсит SRT, объединяет в поток «(timestamp) текст ...»
  - Режет на чанки ~4000 слов с перехлёстом 200 слов
  - Каждый чанк прогоняет через модель с жёстким промптом: пунктуация + фикс терминов + снятие слов-паразитов
  - Склеивает, убирая перехлёст по маркеру
  - Каждые ~60 сек вставляет таймкод [HH:MM:SS]
  - Сохраняет результат + diff-лог

Использование:
    python3 tools/clean_transcript.py transkrib/transcript_uTX807i8wvA.ru.srt
"""
import argparse
import os
import re
import sys
import json
import time
from pathlib import Path

import requests

MODEL = "anthropic/claude-sonnet-5"
CHUNK_WORDS = 4000
OVERLAP_WORDS = 200
TIMECODE_EVERY_SEC = 60


def load_env():
    env = Path(__file__).parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def parse_srt(path: Path):
    """Return list of (start_sec, text_line) — unique text lines in order of first appearance.

    YouTube autosubs используют rolling captions: каждый блок = 2 строки, где первая повторяет
    последнюю из предыдущего блока. Собираем все строки последовательно и дедуплицируем глобально.
    """
    raw = path.read_text()
    blocks = re.split(r"\n\s*\n", raw.strip())
    seen = set()
    out = []
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        tm = next((l for l in lines if "-->" in l), None)
        if not tm:
            continue
        start = tm.split("-->")[0].strip().replace(",", ".")
        h, m, s = start.split(":")
        start_sec = int(h) * 3600 + int(m) * 60 + float(s)
        text_lines = [l.strip() for l in lines if "-->" not in l and not re.match(r"^\d+$", l)]
        for tl in text_lines:
            if tl and tl not in seen:
                seen.add(tl)
                out.append((start_sec, tl))
    return out


def fmt_ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"


def build_stream(segs):
    """Insert [HH:MM:SS] markers every ~60s into one flat text."""
    parts = []
    last_mark = -TIMECODE_EVERY_SEC
    for ts, txt in segs:
        if ts - last_mark >= TIMECODE_EVERY_SEC:
            parts.append(fmt_ts(ts))
            last_mark = ts
        parts.append(txt)
    return " ".join(parts)


def chunk_text(text: str, size: int, overlap: int):
    """Split by words, keeping timecode markers glued to following word."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        end = min(i + size, len(words))
        chunks.append((" ".join(words[i:end]), i, end))
        if end == len(words):
            break
        i = end - overlap
    return chunks


SYSTEM_PROMPT = """Ты редактор-корректор русскоязычных транскриптов YouTube.

Вход: сырой текст автосубтитров без пунктуации, с ошибками распознавания терминов, с таймкодами вида [HH:MM:SS].

Задача — уровень «умеренно»:
1. Расставить пунктуацию (точки, запятые, тире, прямая речь, абзацы по смыслу).
2. Исправить ошибки распознавания технических терминов. Канон:
   - Claude Code, Claude, Claude Sonnet, Claude Opus, Claude Haiku
   - Antigravity (не «Antivity», не «антивити»)
   - VS Code, Cursor, MCP, MCP-серверы
   - CLAUDE.md, subagents, hooks, skills, slash-команды
   - /login, /model, /help (slash-команды с косой чертой)
   - GitHub, Google Drive, Google Sheets, Telegram
   - shadcn/ui, Tailwind, React, Node.js
   - OpenRouter, OpenAI, Anthropic
3. Убрать слова-паразиты и очевидные повторы: «эээ», «ну вот», «короче говоря» (если паразит), «это самое», дубли типа «я-я», «ну-ну». Маркеры стиля автора («короче», «ребят», «вот в чём фишка», «прям») — ОСТАВИТЬ.
4. Сохранить ВСЕ таймкоды [HH:MM:SS] на своих местах в тексте.

ЗАПРЕЩЕНО:
- Сокращать, пересказывать, выкидывать содержательные куски.
- Переводить термины на русский.
- Добавлять свои комментарии, заголовки, оглавление, примечания.
- Менять порядок мыслей.
- «Улучшать стиль» автора, литературно редактировать.

Выход: только очищенный текст, ничего больше. Никаких префиксов, пояснений, markdown-заголовков."""


def call_model(chunk: str, api_key: str) -> str:
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chunk},
            ],
            # temperature не передаём: Claude Sonnet 5 отвергает нестандартные
            # sampling-параметры с 400
            "max_tokens": 16000,
        },
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def stitch(cleaned_chunks, raw_chunks):
    """Stitch cleaned chunks, removing overlap. Overlap detected by last ~40 words of prev == first ~40 words of next in RAW."""
    if not cleaned_chunks:
        return ""
    result = [cleaned_chunks[0]]
    for i in range(1, len(cleaned_chunks)):
        cleaned = cleaned_chunks[i]
        # Первые слова перекрываются с концом предыдущего. Отрежем первые ~N слов по пропорции перехлёст/размер чанка.
        words = cleaned.split()
        cut = int(len(words) * (OVERLAP_WORDS / CHUNK_WORDS))
        # Найдём первый таймкод после cut — от него и продолжим, это безопасная точка склейки.
        tail = " ".join(words[cut:])
        m = re.search(r"\[\d{2}:\d{2}:\d{2}\]", tail)
        if m:
            tail = tail[m.start():]
        result.append(tail)
    return "\n\n".join(result)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY не найден в .env")

    src = Path(args.srt)
    out = Path(args.output) if args.output else src.with_name(src.stem.replace(".ru", "") + "_clean.txt")
    diff_path = out.with_name(out.stem + "_diff.md")

    print(f"→ Парсю SRT: {src}")
    segs = parse_srt(src)
    print(f"  сегментов: {len(segs)}, длительность: {fmt_ts(segs[-1][0])}")

    stream = build_stream(segs)
    raw_words = len(stream.split())
    print(f"  слов в потоке: {raw_words}")

    chunks = chunk_text(stream, CHUNK_WORDS, OVERLAP_WORDS)
    print(f"→ Чанков: {len(chunks)} (по ~{CHUNK_WORDS} слов, перехлёст {OVERLAP_WORDS})")

    cleaned = []
    for i, (ch, a, b) in enumerate(chunks, 1):
        print(f"  [{i}/{len(chunks)}] слова {a}-{b}, отправка... ", end="", flush=True)
        t0 = time.time()
        try:
            c = call_model(ch, api_key)
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        dt = time.time() - t0
        print(f"ok ({dt:.1f}с, {len(c.split())} слов)")
        cleaned.append(c)

    print("→ Склейка чанков...")
    final = stitch(cleaned, chunks)
    clean_words = len(final.split())

    out.write_text(final)
    print(f"✓ Сохранено: {out} ({clean_words} слов)")

    # Diff-лог
    def count_mentions(text, term):
        return len(re.findall(re.escape(term), text, re.IGNORECASE))

    terms = ["Claude Code", "MCP", "CLAUDE.md", "Agent Team", "subagent", "skill", "hook",
             "Google Sheets", "Telegram", "GitHub", "Antigravity", "VS Code", "Opus", "Sonnet"]
    diff_lines = [
        f"# Diff-лог чистки транскрипта\n",
        f"- Источник: `{src.name}`",
        f"- Результат: `{out.name}`",
        f"- Модель: `{MODEL}`",
        f"- Слов до: **{raw_words}**",
        f"- Слов после: **{clean_words}** ({clean_words/raw_words*100:.1f}%)",
        f"- Чанков: {len(chunks)}",
        "",
        "## Упоминания ключевых терминов (до → после)",
        "",
        "| Термин | RAW | CLEAN |",
        "|---|---:|---:|",
    ]
    for t in terms:
        diff_lines.append(f"| {t} | {count_mentions(stream, t)} | {count_mentions(final, t)} |")

    diff_path.write_text("\n".join(diff_lines))
    print(f"✓ Diff-лог: {diff_path}")

    # Простая самопроверка
    ratio = clean_words / raw_words
    print(f"\n— Самопроверка —")
    print(f"  ratio clean/raw: {ratio:.2f}  (норма: 0.85–1.05)")
    if ratio < 0.85:
        print("  ⚠️  слишком много потеряно — проверь вручную!")
    elif ratio > 1.10:
        print("  ⚠️  слишком много добавлено — проверь вручную!")
    else:
        print("  ✓ в норме")


if __name__ == "__main__":
    main()
