#!/usr/bin/env python3
"""
Локальный транскрибатор для YouTube-проекта.
Использует Deepgram nova-2 (тот же API что в transcriber-bot).

Использование:
    python3 transcribe.py /path/to/video.mp4
    python3 transcribe.py /path/to/video.mp4 -o scripts/my-video/transcript.txt
    python3 transcribe.py /path/to/video.mp4 --timestamps

Как работает:
    1. Если передан видео-файл (mp4, mov, mkv...) — ffmpeg автоматически
       извлекает аудиодорожку в MP3 64kbps/16kHz (~15-25 МБ вместо 200-500 МБ видео).
    2. Аудио стримится в Deepgram по частям (не грузится целиком в память).
    3. Временный MP3-файл удаляется сразу после отправки.

    Это решает проблему таймаута при загрузке больших видео-файлов.

Требования:
    pip install requests
    brew install ffmpeg          # для извлечения аудио из видео
    export DEEPGRAM_API_KEY=...  # или положить в .env

Форматы: mp4, mov, m4a, mp3, wav, ogg, webm, mkv, avi, m4v
"""

import argparse
import os
import sys
import json
from pathlib import Path
from typing import Optional


def load_env():
    """Load .env from project dir if exists."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


def extract_audio(video_path: Path) -> Path:
    """Extract audio from video file using ffmpeg. Returns path to mp3 file."""
    import subprocess
    import tempfile

    audio_path = Path(tempfile.mktemp(suffix=".mp3"))
    print("🎵 Извлекаю аудио из видео (ffmpeg)...")
    result = subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-vn", "-acodec", "mp3", "-ab", "64k", "-ar", "16000", "-y", str(audio_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"⚠️  ffmpeg недоступен или ошибка: {result.stderr[:200]}")
        return video_path  # fallback — отправляем оригинал
    size_mb = audio_path.stat().st_size / 1024 / 1024
    print(f"✅ Аудио извлечено: {size_mb:.1f} МБ")
    return audio_path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def transcribe(file_path: str, timestamps: bool = False, language: Optional[str] = None) -> str:
    """Send audio/video file to Deepgram, return transcript text."""
    import requests

    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        print("❌ DEEPGRAM_API_KEY не задан. Добавь в .env или export DEEPGRAM_API_KEY=...")
        sys.exit(1)

    params = {
        "model": "nova-2",
        "smart_format": "true",
        "punctuate": "true",
        "paragraphs": "true",
    }
    # У Deepgram detect_language ПЕРЕОПРЕДЕЛЯЕТ language, поэтому вместе их не шлём:
    # без флага --language — русский по умолчанию + автоопределение,
    # с явным --language (включая ru) — язык фиксируется жёстко, без «угадывания».
    if language is None:
        params["language"] = "ru"
        params["detect_language"] = "true"
    else:
        params["language"] = language
    if timestamps:
        params["utterances"] = "true"

    file_path = Path(file_path)
    if not file_path.exists():
        print(f"❌ Файл не найден: {file_path}")
        sys.exit(1)

    size_mb = file_path.stat().st_size / 1024 / 1024
    print(f"📁 Файл: {file_path.name} ({size_mb:.1f} МБ)")

    # Для видео-файлов — сначала извлечь аудио, чтобы не грузить 200+ МБ
    temp_audio = None
    if file_path.suffix.lower() in VIDEO_EXTENSIONS:
        extracted = extract_audio(file_path)
        if extracted != file_path:
            temp_audio = extracted
            file_path = extracted

    print("⏳ Отправляю в Deepgram...")

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/octet-stream",
    }

    try:
        # Стримим файл — не загружаем весь в память
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers=headers,
                data=f,
                timeout=900,
            )
    finally:
        # Удаляем временный аудио-файл
        if temp_audio and temp_audio.exists():
            temp_audio.unlink()

    if resp.status_code != 200:
        print(f"❌ Deepgram error {resp.status_code}: {resp.text[:300]}")
        sys.exit(1)

    result = resp.json()

    if timestamps:
        return _extract_with_timestamps(result)
    else:
        return _extract(result)


def _extract(response: dict) -> str:
    results = response.get("results", {})

    paragraphs = (
        results.get("channels", [{}])[0]
        .get("alternatives", [{}])[0]
        .get("paragraphs", {})
        .get("paragraphs", [])
    )

    if paragraphs:
        parts = []
        for para in paragraphs:
            text = " ".join(s.get("text", "") for s in para.get("sentences", []))
            if text.strip():
                parts.append(text.strip())
        if parts:
            return "\n\n".join(parts)

    # fallback
    return (
        results.get("channels", [{}])[0]
        .get("alternatives", [{}])[0]
        .get("transcript", "")
    )


def _extract_with_timestamps(response: dict) -> str:
    results = response.get("results", {})
    words = (
        results.get("channels", [{}])[0]
        .get("alternatives", [{}])[0]
        .get("words", [])
    )

    if not words:
        return _extract(response)

    parts = []
    last_ts = -30
    chunk = []

    for w in words:
        start = w.get("start", 0)
        text = w.get("punctuated_word", w.get("word", ""))

        if start - last_ts >= 30:
            if chunk:
                parts.append(" ".join(chunk))
                chunk = []
            m, s = int(start // 60), int(start % 60)
            chunk.append(f"[{m:02d}:{s:02d}]")
            last_ts = start

        chunk.append(text)

    if chunk:
        parts.append(" ".join(chunk))

    return "\n\n".join(parts)


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Транскрибатор видео/аудио через Deepgram")
    parser.add_argument("file", help="Путь к видео или аудио файлу")
    parser.add_argument("-o", "--output", help="Куда сохранить транскрибацию (по умолчанию рядом с файлом)")
    parser.add_argument("--timestamps", action="store_true", help="Добавить таймкоды [MM:SS] каждые 30 сек")
    parser.add_argument("--language", default=None, help="Язык аудио для Deepgram (ru, zh, en, de…). Без флага — ru с авто-определением; с флагом (включая --language ru) язык фиксируется жёстко")
    args = parser.parse_args()

    text = transcribe(args.file, timestamps=args.timestamps, language=args.language)

    word_count = len(text.split())
    print(f"✅ Транскрибировано: {word_count} слов")

    # Определяем куда сохранить
    if args.output:
        out_path = Path(args.output)
    else:
        src = Path(args.file)
        out_path = src.with_suffix(".txt")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"💾 Сохранено: {out_path}")

    return str(out_path)


if __name__ == "__main__":
    main()
