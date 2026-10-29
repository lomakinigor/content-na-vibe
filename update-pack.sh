#!/usr/bin/env bash
# Обновляет только опубликованные файлы пакета. Данные сервера сохраняются.

set -euo pipefail

repository="${CONTENT_NA_VIBE_REPOSITORY:-https://github.com/lomakinigor/content-na-vibe.git}"
temporary=".content-na-vibe-update.tmp"
required_skills=(producer-orchestrator trend-hunter video-transcriber scenario-writer presentation-maker lead-magnet-maker)

test -f pack.manifest.json || { echo "Ошибка: запустите скрипт из корня content-na-vibe." >&2; exit 1; }
test ! -e "$temporary" || { echo "Ошибка: уже есть $temporary. Ничего не обновлено." >&2; exit 1; }

git clone --quiet --depth 1 "$repository" "$temporary"
trap 'rm -rf -- "$temporary"' EXIT

test -f "$temporary/pack.manifest.json" || { echo "Ошибка: в источнике нет manifest. Ничего не обновлено." >&2; exit 1; }
for skill in "${required_skills[@]}"; do
  test -f "$temporary/skills/$skill/SKILL.md" || { echo "Ошибка: в источнике нет $skill. Ничего не обновлено." >&2; exit 1; }
done

for directory in _playbooks keys-guide skills tools; do
  test -d "$temporary/$directory" || { echo "Ошибка: в источнике нет $directory. Ничего не обновлено." >&2; exit 1; }
done

for directory in _playbooks keys-guide skills tools; do
  mkdir -p "$directory"
  cp -R "$temporary/$directory/." "$directory/"
done

for file in .pack-version env.example pack.manifest.json README.md requirements.txt SECURITY.md SETUP.md UPSTREAM.md update-pack.sh; do
  test -f "$temporary/$file" && cp "$temporary/$file" "$file"
done

if [ -x .venv/bin/pip ]; then
  .venv/bin/pip install --disable-pip-version-check -r requirements.txt
fi

echo "Готово: пакет обновлён до $(head -n 1 .pack-version). voice/, .venv и server credentials сохранены."
