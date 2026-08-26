#!/usr/bin/env python3
"""Парсит reels/production/2026-05-13.md и собирает HTML для МОНТАЖЁРА.

Отличия от build_shooting_page.py:
- Карточки заточены под монтажёра: кнопки «Скачать» и «Открыть в Drive» (не «копировать в суфлёр»)
- Бейджи «✓ Готово / ⏳ В записи» по наличию Google Drive ссылки
- Нет суфлёр-режима, нет кнопки «открыть .md», нет отметок записанности
- Чистый стиль 2026-05-01.html
"""
import re
import html
from pathlib import Path

MD = Path("reels/production/input.md")
OUT = Path("reels/production/input.html")

raw = MD.read_text(encoding="utf-8")

parts = re.split(r"^## Reel (\S+)\s*—\s*(.+?)$", raw, flags=re.MULTILINE)

reels = []
for i in range(1, len(parts), 3):
    num = parts[i].strip()
    title_raw = parts[i + 1].strip()
    body = parts[i + 2]
    title = title_raw.replace("✅ ЗАПИСАНО", "").strip()

    # Референс
    ref_match = re.search(r"### Референс\s*\n(.+?)(?=\n\n|\n###|\Z)", body, re.DOTALL)
    ref_block = ref_match.group(1).strip() if ref_match else ""
    url_match = re.search(r"https?://\S+", ref_block)
    ref_url = url_match.group(0) if url_match else ""

    # Текст для записи
    mt_match = re.search(r"### Мой текст для записи\s*\n(.+?)(?=\n### |\n> |\Z)", body, re.DOTALL)
    my_text_full = mt_match.group(1).strip() if mt_match else ""
    if my_text_full:
        # Убираем разметку [ХУК — ...] из тела — для монтажёра она не нужна
        my_text_clean = re.sub(r"\*\*\[ХУК[^\]]*\]\*\*\s*", "", my_text_full)
    else:
        my_text_clean = ""

    # Заметки
    notes_match = re.search(r"### Заметки к записи\s*\n(.+?)(?=\n### |\n> |\Z)", body, re.DOTALL)
    notes_raw = notes_match.group(1).strip() if notes_match else ""

    # CTA
    cta = {"Instagram": "", "YouTube": "", "ВК": ""}
    cta_match = re.search(r"### CTA\s*\n(.+?)(?=\n### |\n> |\n---|\Z)", body, re.DOTALL)
    if cta_match:
        cta_block = cta_match.group(1)
        for platform in cta:
            pm = re.search(rf"\*\*{platform}:\*\*\s*(.+?)(?=\n\*\*|\Z)", cta_block, re.DOTALL)
            if pm:
                cta[platform] = pm.group(1).strip()

    # Готовое видео — Google Drive ссылка
    drive_match = re.search(r"### Готовое видео.*?\n(.+?)(?=\n---|\Z)", body, re.DOTALL)
    drive_block = drive_match.group(1).strip() if drive_match else ""
    drive_url_match = re.search(r"https://drive\.google\.com/file/d/([^/]+)/", drive_block)
    drive_id = drive_url_match.group(1) if drive_url_match else ""
    drive_url = f"https://drive.google.com/file/d/{drive_id}/view" if drive_id else ""

    reels.append({
        "num": num,
        "title": title,
        "ref_url": ref_url,
        "ref_block": ref_block,
        "body_text": my_text_clean,
        "notes": notes_raw,
        "cta": cta,
        "drive_id": drive_id,
        "drive_url": drive_url,
    })

# Особый случай: Reel 8 не имеет своего видео — это сдвоенный дубль с Reel 9
reel_map = {r["num"]: r for r in reels}
if "8" in reel_map and not reel_map["8"]["drive_id"] and "9" in reel_map and reel_map["9"]["drive_id"]:
    reel_map["8"]["drive_id"] = reel_map["9"]["drive_id"]
    reel_map["8"]["drive_url"] = reel_map["9"]["drive_url"]
    reel_map["8"]["dub_note"] = "Тот же исходник что Reel 9 — на монтаже из одного видео режется два ролика с разными CTA."
# Reel 9 — текст такой же как у 8 (если у 9 пустое тело)
if "9" in reel_map and not reel_map["9"]["body_text"] and "8" in reel_map:
    reel_map["9"]["body_text"] = reel_map["8"]["body_text"]
    reel_map["9"]["dub_note"] = "Тот же исходник что Reel 8 — вторая нарезка с другим CTA в финале."

ok_count = sum(1 for r in reels if r["drive_id"])
wait_count = len(reels) - ok_count
print(f"Парснул {len(reels)} Reel'ов: готово {ok_count}, в записи {wait_count}")


def md_to_html(text: str) -> str:
    """Минимальный markdown → HTML для заметок (списки, инлайн-код, жирный)."""
    if not text:
        return ""
    lines = text.split("\n")
    out = []
    in_ul = False
    for ln in lines:
        ln_stripped = ln.strip()
        if ln_stripped.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            raw = ln_stripped[2:]
            esc = html.escape(raw)
            esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
            esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc)
            out.append(f"<li>{esc}</li>")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if ln_stripped:
                esc = html.escape(ln_stripped)
                esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
                esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc)
                out.append(f"<p>{esc}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def render_reel(r):
    is_ready = bool(r["drive_id"])
    badge_class = "ok" if is_ready else "wait"
    badge_text = "✓ Готово" if is_ready else "⏳ В записи"

    cta_html = ""
    for platform, text in r["cta"].items():
        if text:
            text_esc = html.escape(text)
            text_esc = re.sub(r"`([^`]+)`", r"<b>\1</b>", text_esc)
            text_esc = re.sub(r"«([^»]+)»", r"«<b>\1</b>»", text_esc)
            cta_html += f'<div class="cta-row"><b>{html.escape(platform)}</b>{text_esc}</div>'

    notes_html = md_to_html(r["notes"])
    body_text_esc = html.escape(r["body_text"]) if r["body_text"] else ""

    if is_ready:
        download_url = f"https://drive.google.com/uc?export=download&amp;id={r['drive_id']}"
        view_url = f"https://drive.google.com/file/d/{r['drive_id']}/view"
        video_block = (
            f'<a class="btn" href="{download_url}">⬇ Скачать</a>'
            f'<a class="btn secondary" href="{view_url}" target="_blank" rel="noopener">👁 Открыть в Drive</a>'
        )
    else:
        video_block = '<div class="note">⏳ Видео ещё не записано — ждём съёмку.</div>'

    dub_note_html = (
        f'<div class="note" style="margin-bottom:10px">📎 {html.escape(r.get("dub_note", ""))}</div>'
        if r.get("dub_note") else ""
    )

    search_title = (r["title"] + " " + r["body_text"][:200]).lower()
    search_title = re.sub(r"[^\w\s]", " ", search_title)

    ref_link_html = (
        f'<a href="{html.escape(r["ref_url"])}" target="_blank" rel="noopener">Открыть оригинал в Instagram</a>'
        if r["ref_url"] else '<span class="muted">нет ссылки</span>'
    )

    return f'''<details data-status="{badge_class}" data-title="{html.escape(search_title)}">
  <summary>
    <span class="num">{html.escape(r["num"])}</span>
    <span class="ttl">{html.escape(r["title"])}</span>
    <span class="badge {badge_class}">{badge_text}</span>
    <span class="arrow">▶</span>
  </summary>
  <div class="body">
    {dub_note_html}
    <div class="sec"><h3>Референс</h3>{ref_link_html}</div>
    {f'<div class="sec"><h3>Текст для записи</h3><div class="text-block">{body_text_esc}</div></div>' if body_text_esc else ''}
    {f'<div class="sec"><h3>Заметки</h3><div class="note">{notes_html}</div></div>' if notes_html else ''}
    <div class="sec"><h3>CTA по площадкам</h3><div class="cta-grid">{cta_html}</div></div>
    <div class="sec"><h3>Готовое видео (для монтажа)</h3>{video_block}</div>
  </div>
</details>'''


reel_cards = "\n".join(render_reel(r) for r in reels)

html_out = f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1a1612">
<title>Reels на монтаж — 2026-05-13</title>
<style>*{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
html,body{{margin:0;padding:0;background:#1a1612;color:#f1ebe1;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:780px;margin:0 auto;padding:20px 16px 80px}}
header{{padding:8px 4px 20px;border-bottom:1px solid #3a3128;margin-bottom:18px}}
h1{{font-size:22px;margin:0 0 6px;font-weight:700;letter-spacing:-0.01em}}
.sub{{color:#a89c8c;font-size:14px}}
.stats{{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}}
.chip{{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;
  background:#221d18;border:1px solid #3a3128;font-size:13px;color:#a89c8c}}
.chip b{{color:#f1ebe1;font-weight:600}}
.dot{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.dot.ok{{background:#7fb069}}
.dot.wait{{background:#c8a165}}
details{{background:#221d18;border:1px solid #3a3128;border-radius:14px;margin:10px 0;overflow:hidden}}
details[open]{{background:#2b251f}}
summary{{padding:14px 16px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:12px;
  user-select:none;outline:none}}
summary::-webkit-details-marker{{display:none}}
.num{{flex-shrink:0;width:34px;height:34px;border-radius:10px;background:#1a1612;
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;color:#e8a04a}}
.ttl{{flex:1;min-width:0;font-weight:600;font-size:15px;line-height:1.35}}
.badge{{flex-shrink:0;font-size:11px;padding:4px 8px;border-radius:6px;font-weight:600;letter-spacing:0.02em;text-transform:uppercase}}
.badge.ok{{background:rgba(127,176,105,0.15);color:#7fb069;border:1px solid rgba(127,176,105,0.3)}}
.badge.wait{{background:rgba(200,161,101,0.15);color:#c8a165;border:1px solid rgba(200,161,101,0.3)}}
.arrow{{flex-shrink:0;color:#a89c8c;transition:transform 0.2s;font-size:12px}}
details[open] .arrow{{transform:rotate(90deg)}}
.body{{padding:4px 16px 18px;border-top:1px solid #3a3128}}
.sec{{margin-top:16px}}
.sec h3{{font-size:12px;text-transform:uppercase;letter-spacing:0.08em;color:#e8a04a;
  margin:0 0 8px;font-weight:600}}
a{{color:#f0b66c;text-decoration:none;border-bottom:1px solid rgba(240,182,108,0.3);word-break:break-word}}
a:hover{{border-bottom-color:#f0b66c}}
.muted{{color:#a89c8c}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:12px 18px;border-radius:10px;
  background:linear-gradient(135deg,#e8a04a,#d97757);color:#1a1612;font-weight:700;
  font-size:15px;border:none;text-decoration:none;margin-top:6px;margin-right:8px}}
.btn.secondary{{background:transparent;color:#f1ebe1;border:1px solid #3a3128}}
.btn:hover{{filter:brightness(1.08)}}
.cta-grid{{display:grid;gap:8px;margin-top:6px}}
.cta-row{{padding:10px 12px;background:#1a1612;border-radius:8px;border:1px solid #3a3128;font-size:14px}}
.cta-row b{{color:#e8a04a;display:block;margin-bottom:3px;font-size:12px;letter-spacing:0.04em;text-transform:uppercase}}
.cta-row b b{{color:#f7e9d4;display:inline;font-size:inherit;letter-spacing:0;text-transform:none;background:rgba(232,160,74,0.12);padding:1px 6px;border-radius:4px}}
.text-block{{white-space:pre-wrap;font-size:15px;line-height:1.6;color:#f1ebe1;
  background:#1a1612;padding:12px 14px;border-radius:10px;border:1px solid #3a3128}}
.note{{font-size:14px;color:#c4b8a5;padding:10px 12px;
  background:rgba(232,160,74,0.05);border-left:3px solid #e8a04a;border-radius:6px;line-height:1.55}}
.note ul{{margin:4px 0 0;padding-left:18px}}
.note li{{margin-bottom:3px}}
.note p{{margin:4px 0}}
.note code{{background:#1a1612;padding:1px 6px;border-radius:4px;font-size:13px;color:#f0b66c}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}}
.filter{{padding:8px 14px;border-radius:8px;background:#221d18;border:1px solid #3a3128;
  color:#a89c8c;font-size:13px;cursor:pointer;font-family:inherit}}
.filter.active{{background:#e8a04a;color:#1a1612;border-color:#e8a04a;font-weight:600}}
.hidden{{display:none !important}}
footer{{margin-top:30px;padding:20px 4px;border-top:1px solid #3a3128;color:#a89c8c;
  font-size:13px;text-align:center}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🎬 Reels на монтаж — 13 мая</h1>
    <div class="sub">автор · Claude Code · вертикалки · Reels 6-25</div>
    <div class="stats">
      <span class="chip"><span class="dot ok"></span>Готово: <b>{ok_count}</b></span>
      <span class="chip"><span class="dot wait"></span>В записи: <b>{wait_count}</b></span>
      <span class="chip">Всего: <b>{len(reels)}</b></span>
    </div>
    <div class="toolbar">
      <button class="filter active" data-f="all">Все</button>
      <button class="filter" data-f="ok">✓ Готовые</button>
      <button class="filter" data-f="wait">⏳ В процессе</button>
    </div>
  </header>
  <div id="list">
{reel_cards}
  </div>
  <footer>Стиль «Крафтовый терминал» · 25 сценариев</footer>
</div>
<script>
document.querySelectorAll('.filter').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const f = btn.dataset.f;
    document.querySelectorAll('#list > details').forEach(d => {{
      d.classList.toggle('hidden', f !== 'all' && d.dataset.status !== f);
    }});
  }});
}});
</script>
</body>
</html>
'''

OUT.write_text(html_out, encoding="utf-8")
print(f"Записано: {OUT}")
