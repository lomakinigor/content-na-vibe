#!/usr/bin/env python3
"""
Двухэтапный pipeline для создания сценариев из транскрибаций.

Stage 1 (Haiku):  Транскрибация (100k) → структурный конспект (10-15k)
Stage 2 (Sonnet): Конспект + промпт scenario.txt → готовый сценарий

Экономия: ~80-90% лимита по сравнению с прямым вызовом Opus.

Использование:
    python3 pipeline.py transcript.txt
    python3 pipeline.py transcript.txt --output scenario.md
    python3 pipeline.py transcript.txt --mode topic --duration 15
    cat transcript.txt | python3 pipeline.py -

Требования:
    установленный Claude Code CLI (команда `claude`) с активной подпиской —
    API-ключи не нужны, вызовы идут в headless-режиме `claude -p`
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# ─── Конфиг ──────────────────────────────────────────────────────────────────

# Модели для каждого этапа (передаются в `claude -p --model ...`)
STAGE1_MODEL = "claude-haiku-4-5"  # дешёвый, быстрый — для сжатия
STAGE2_MODEL = "claude-sonnet-5"   # умный — для сценария

# Порог: если текст короче этого — пропускаем Stage 1
COMPRESSION_THRESHOLD_WORDS = 15_000  # ~15k слов ≈ 30-40 мин речи

# Таймаут одного вызова CLI, сек (Sonnet 5 на длинном конспекте думает долго)
CLAUDE_TIMEOUT_S = 1800

# Папка с промптами (относительно этого файла)
PIPELINE_DIR = Path(__file__).parent
PROMPTS_DIR = PIPELINE_DIR / "prompts"
SCENARIO_KIT_DIR = PIPELINE_DIR.parent
SCENARIO_PROMPTS_DIR = SCENARIO_KIT_DIR / "prompts"


# ─── Утилиты ─────────────────────────────────────────────────────────────────

def count_words(text: str) -> int:
    return len(text.split())


def estimate_tokens(text: str) -> int:
    """Грубая оценка: ~1.5 токена на слово для русского текста."""
    return int(count_words(text) * 1.5)


def load_prompt(path: Path) -> str:
    if not path.exists():
        print(f"❌ Файл промпта не найден: {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def check_claude_cli() -> None:
    if not shutil.which("claude"):
        print("❌ Не найдена команда `claude` (Claude Code CLI)")
        print("   Установи Claude Code и войди в аккаунт с подпиской")
        sys.exit(1)


def call_claude(
    model: str,
    system: str,
    user_message: str,
) -> tuple[str, dict]:
    """Вызов Claude через headless `claude -p` (авторизация — подписка Claude Code).

    Возвращает (текст ответа, usage). System-промпт склеивается с сообщением:
    так вызов не зависит от версии CLI и лимитов argv на длину аргументов.
    """

    full_prompt = system + "\n\n─── Материал ───\n\n" + user_message

    try:
        # --tools "" отключает ВСЕ инструменты: транскрипция — недоверенный текст
        # (чужое видео), prompt-injection в нём не должна получить доступ к файлам/шеллу
        result = subprocess.run(
            ["claude", "-p", "--model", model, "--output-format", "json", "--tools", ""],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        print(f"❌ Claude CLI не ответил за {CLAUDE_TIMEOUT_S} сек")
        sys.exit(1)

    if result.returncode != 0:
        print(f"❌ Claude CLI ошибка (код {result.returncode}):")
        print(f"   {(result.stderr or result.stdout)[:500].strip()}")
        sys.exit(1)

    # --output-format json → {"result": "...", "usage": {...}, ...}
    # На случай смены схемы в новых версиях CLI — fallback на сырой текст.
    try:
        data = json.loads(result.stdout)
        text = data.get("result", "")
        usage = data.get("usage", {}) or {}
    except (json.JSONDecodeError, AttributeError):
        text = result.stdout
        usage = {}

    if not text.strip():
        print("❌ Claude CLI вернул пустой ответ")
        sys.exit(1)

    return text, usage


# ─── Stage 1: Сжатие через Haiku ─────────────────────────────────────────────

def stage1_compress(transcript: str) -> tuple[str, dict]:
    """Сжать транскрибацию в структурный конспект."""

    system_prompt = load_prompt(PROMPTS_DIR / "compress.txt")

    print(f"📋 Stage 1: Сжатие через Haiku...")
    print(f"   Модель: {STAGE1_MODEL}")
    print(f"   Вход: ~{count_words(transcript)} слов (~{estimate_tokens(transcript)} токенов)")

    start = time.time()
    summary, usage = call_claude(
        model=STAGE1_MODEL,
        system=system_prompt,
        user_message=transcript,
    )
    elapsed = time.time() - start

    print(f"   ✅ Готово за {elapsed:.1f} сек")
    print(f"   Выход: ~{count_words(summary)} слов (~{estimate_tokens(summary)} токенов)")
    print(f"   Сжатие: {count_words(transcript)} → {count_words(summary)} слов "
          f"({count_words(summary) / max(count_words(transcript), 1) * 100:.0f}%)")
    if usage:
        print(f"   Токены: вход={usage.get('input_tokens', '?')}, выход={usage.get('output_tokens', '?')}")

    return summary, usage


# ─── Stage 2: Сценарий через Sonnet ──────────────────────────────────────────

def stage2_scenario(content: str, mode: str, duration: Optional[int] = None) -> tuple[str, dict]:
    """Сгенерировать сценарий из конспекта или транскрибации."""

    if mode == "video":
        prompt_file = SCENARIO_PROMPTS_DIR / "scenario.txt"
        label = "по видео"
    else:
        prompt_file = SCENARIO_PROMPTS_DIR / "scenario_topic.txt"
        label = "по теме"

    system_prompt = load_prompt(prompt_file)

    if duration:
        content = f"Хронометраж: {duration} минут.\n\n{content}"

    print(f"\n🎬 Stage 2: Сценарий ({label}) через Sonnet...")
    print(f"   Модель: {STAGE2_MODEL}")
    print(f"   Вход: ~{count_words(content)} слов (~{estimate_tokens(content)} токенов)")

    start = time.time()
    scenario, usage = call_claude(
        model=STAGE2_MODEL,
        system=system_prompt,
        user_message=content,
    )
    elapsed = time.time() - start

    print(f"   ✅ Готово за {elapsed:.1f} сек")
    print(f"   Выход: ~{count_words(scenario)} слов")
    if usage:
        print(f"   Токены: вход={usage.get('input_tokens', '?')}, выход={usage.get('output_tokens', '?')}")

    return scenario, usage


# ─── Основной pipeline ───────────────────────────────────────────────────────

def run_pipeline(
    transcript: str,
    mode: str = "video",
    output_path: Optional[Path] = None,
    duration: Optional[int] = None,
    force_compress: bool = False,
    save_summary: bool = True,
) -> str:
    """
    Запустить двухэтапный pipeline.

    Args:
        transcript: текст транскрибации
        mode: "video" (по видео) или "topic" (по теме)
        output_path: куда сохранить сценарий
        duration: хронометраж (для mode=topic)
        force_compress: принудительно сжать, даже если текст короткий
        save_summary: сохранить промежуточный конспект
    """

    check_claude_cli()
    word_count = count_words(transcript)

    print("═" * 60)
    print("🎯 Pipeline: Транскрибация → Конспект → Сценарий")
    print("═" * 60)
    print(f"   Вход: ~{word_count} слов (~{estimate_tokens(transcript)} токенов)")
    print(f"   Режим: {'по видео' if mode == 'video' else 'по теме'}")
    print(f"   Порог сжатия: {COMPRESSION_THRESHOLD_WORDS} слов")
    print()

    total_usage = {"input_tokens": 0, "output_tokens": 0}

    # Решаем: нужно ли сжатие?
    need_compress = force_compress or word_count > COMPRESSION_THRESHOLD_WORDS

    if need_compress:
        # Stage 1: Сжатие
        summary, usage1 = stage1_compress(transcript)
        total_usage["input_tokens"] += usage1.get("input_tokens", 0)
        total_usage["output_tokens"] += usage1.get("output_tokens", 0)

        # Сохраняем конспект
        if save_summary and output_path:
            summary_path = output_path.parent / f"{output_path.stem}_summary.md"
            summary_path.write_text(summary, encoding="utf-8")
            print(f"   💾 Конспект: {summary_path}")

        content_for_scenario = summary
    else:
        print(f"⏩ Текст короткий ({word_count} слов) — сжатие не нужно, сразу в Sonnet")
        content_for_scenario = transcript

    # Stage 2: Сценарий
    scenario, usage2 = stage2_scenario(content_for_scenario, mode, duration)
    total_usage["input_tokens"] += usage2.get("input_tokens", 0)
    total_usage["output_tokens"] += usage2.get("output_tokens", 0)

    # Сохраняем сценарий
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(scenario, encoding="utf-8")
        print(f"\n💾 Сценарий: {output_path}")
    else:
        # Автоматическое имя
        auto_path = PIPELINE_DIR / "output" / f"scenario_{int(time.time())}.md"
        auto_path.parent.mkdir(parents=True, exist_ok=True)
        auto_path.write_text(scenario, encoding="utf-8")
        print(f"\n💾 Сценарий: {auto_path}")

    # Итоги
    print()
    print("═" * 60)
    print("📊 Итоги")
    print("═" * 60)
    print(f"   Входных токенов:  {total_usage['input_tokens']:,}")
    print(f"   Выходных токенов: {total_usage['output_tokens']:,}")

    if need_compress:
        # Сравнение: сколько бы стоил прямой вызов Opus
        direct_input = estimate_tokens(transcript)
        print(f"\n   💡 Без pipeline (Opus напрямую): ~{direct_input:,} входных токенов")
        print(f"   💡 С pipeline: {total_usage['input_tokens']:,} входных токенов")
        saved = max(0, direct_input - total_usage["input_tokens"])
        if direct_input > 0:
            print(f"   💡 Экономия: ~{saved:,} токенов ({saved / direct_input * 100:.0f}%)")

    print()
    return scenario


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Двухэтапный pipeline: транскрибация → конспект → сценарий",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python3 pipeline.py transcript.txt
  python3 pipeline.py transcript.txt --output scripts/my-video/script.md
  python3 pipeline.py transcript.txt --mode topic --duration 15
  python3 pipeline.py transcript.txt --force-compress
  cat long_transcript.txt | python3 pipeline.py -
        """,
    )

    parser.add_argument(
        "input",
        help="Файл с транскрибацией (или '-' для stdin)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Путь для сохранения сценария (по умолчанию: pipeline/output/)",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["video", "topic"],
        default="video",
        help="Режим: video (по видео, default) или topic (по теме)",
    )
    parser.add_argument(
        "--duration", "-d",
        type=int,
        help="Желаемый хронометраж в минутах (для mode=topic)",
    )
    parser.add_argument(
        "--force-compress", "-f",
        action="store_true",
        help="Принудительно сжать, даже если текст короткий",
    )
    parser.add_argument(
        "--no-save-summary",
        action="store_true",
        help="Не сохранять промежуточный конспект",
    )

    args = parser.parse_args()

    # Читаем транскрибацию
    if args.input == "-":
        transcript = sys.stdin.read()
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"❌ Файл не найден: {input_path}")
            sys.exit(1)
        transcript = input_path.read_text(encoding="utf-8")

    if not transcript.strip():
        print("❌ Пустая транскрибация")
        sys.exit(1)

    # Выходной путь
    output_path = Path(args.output) if args.output else None

    # Запуск
    run_pipeline(
        transcript=transcript,
        mode=args.mode,
        output_path=output_path,
        duration=args.duration,
        force_compress=args.force_compress,
        save_summary=not args.no_save_summary,
    )


if __name__ == "__main__":
    main()
