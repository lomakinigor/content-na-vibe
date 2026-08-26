#!/usr/bin/env python3
"""Парсит reels/production/2026-05-13.md и собирает HTML страницу для съёмки."""
import re
import html
from pathlib import Path

MD = Path("reels/production/input.md")
OUT = Path("reels/production/input-shooting.html")

raw = MD.read_text(encoding="utf-8")

# Разбиваем по заголовкам ## Reel N
parts = re.split(r"^## Reel (\S+)\s*—\s*(.+?)$", raw, flags=re.MULTILINE)
# parts[0] = до первого Reel; затем повторяется: num, title, body

reels = []
for i in range(1, len(parts), 3):
    num = parts[i].strip()
    title_raw = parts[i + 1].strip()
    body = parts[i + 2]

    # Статус — из заголовка (✅ ЗАПИСАНО)
    status = "ok" if "✅ ЗАПИСАНО" in title_raw else "wait"
    title = title_raw.replace("✅ ЗАПИСАНО", "").strip()

    # Референс
    ref_match = re.search(r"### Референс\s*\n(.+?)(?=\n\n|\n###|\Z)", body, re.DOTALL)
    ref_block = ref_match.group(1).strip() if ref_match else ""
    # Достаём первый URL
    url_match = re.search(r"https?://\S+", ref_block)
    ref_url = url_match.group(0) if url_match else ""

    # Оригинал (может отсутствовать — например Reel 9)
    orig_match = re.search(r"### Оригинал.*?\n(.+?)(?=\n### |\n> |\Z)", body, re.DOTALL)
    orig = orig_match.group(1).strip() if orig_match else ""

    # Текст для записи: блок "### Мой текст для записи"
    mt_match = re.search(r"### Мой текст для записи\s*\n(.+?)(?=\n### |\n> |\Z)", body, re.DOTALL)
    my_text_full = mt_match.group(1).strip() if mt_match else ""

    # Разделим на хук и тело. Хук — первый абзац, обычно начинается с **[ХУК — ...]**
    hook = ""
    body_text = ""
    if my_text_full:
        # Хук = всё до первого \n\n
        first_para, _, rest = my_text_full.partition("\n\n")
        # Убираем разметку **[ХУК — ...]** из видимого хука, но запомним пометку
        hook_marker = ""
        hm = re.match(r"\*\*\[ХУК\s*—\s*([^\]]+)\]\*\*\s*(.*)", first_para, re.DOTALL)
        if hm:
            hook_marker = hm.group(1).strip()
            hook = hm.group(2).strip()
        else:
            hook = first_para.strip()
        body_text = rest.strip()
    else:
        # Reel 9 — особый случай (тело такое же как Reel 8)
        hook_marker = ""

    # Заметки к записи
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

    reels.append({
        "num": num,
        "title": title,
        "status": status,
        "ref_url": ref_url,
        "ref_block": ref_block,
        "orig": orig,
        "hook": hook,
        "hook_marker": hook_marker,
        "body_text": body_text,
        "notes": notes_raw,
        "cta": cta,
    })

print(f"Парснул {len(reels)} Reel'ов")

# Считаем статистику
n_ok = sum(1 for r in reels if r["status"] == "ok")
n_wait = sum(1 for r in reels if r["status"] == "wait")

# Конвертация markdown-подобной разметки в HTML (минимум — bullets, inline code, bold)
def md_to_html(text: str) -> str:
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
            item = ln_stripped[2:]
            # inline code `xxx`
            item = re.sub(r"`([^`]+)`", lambda m: f"<code>{html.escape(m.group(1))}</code>", item)
            # bold **xxx**
            item = re.sub(r"\*\*([^*]+)\*\*", lambda m: f"<b>{html.escape(m.group(1))}</b>", item)
            # escape остального — но мы уже частично преобразовали, нужен другой подход
            # переделаем: сначала escape, потом разметка
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


# Особый случай: Reel 9 — это второй ролик из дубля Reel 8. Тело пустое, нужно подставить из Reel 8.
reel_map = {r["num"]: r for r in reels}
if "9" in reel_map and not reel_map["9"]["body_text"] and "8" in reel_map:
    reel_map["9"]["hook"] = reel_map["8"]["hook"]
    reel_map["9"]["hook_marker"] = "ТОТ ЖЕ ЧТО Reel 8 — дубль"
    reel_map["9"]["body_text"] = reel_map["8"]["body_text"]

# Собираем HTML
def render_reel(r):
    badge_class = "ok" if r["status"] == "ok" else "wait"
    badge_text = "✓ Записано" if r["status"] == "ok" else "⏳ На запись"
    hook_pill = f'<span class="pill">{html.escape(r["hook_marker"] or "")}</span>' if r["hook_marker"] else ""

    cta_html = ""
    for platform, text in r["cta"].items():
        if text:
            text_esc = html.escape(text)
            text_esc = re.sub(r"`([^`]+)`", r'<span class="codeword">\1</span>', text_esc)
            text_esc = re.sub(r"«([^»]+)»", r'«<span class="codeword">\1</span>»', text_esc)
            cta_html += f'<div class="cta-row"><span class="platform">{html.escape(platform)}</span>{text_esc}</div>'

    notes_html = md_to_html(r["notes"])

    orig_html = html.escape(r["orig"]) if r["orig"] else ""

    search_title = (r["title"] + " " + r["body_text"][:200]).lower()
    search_title = re.sub(r"[^\w\s]", " ", search_title)

    return f'''<details data-status="{r["status"]}" data-reel="{r["num"]}" data-title="{html.escape(search_title)}">
  <summary>
    <span class="num">{html.escape(r["num"])}</span>
    <span class="ttl">{html.escape(r["title"])}</span>
    <span class="badge {badge_class}">{badge_text}</span>
    <span class="arrow">▶</span>
  </summary>
  <div class="body">

    <div class="actions">
      <button class="copy-btn" data-copy-target="reel-{r["num"]}-text">📋 Копировать в суфлёр</button>
      <button class="teleprompter-btn" data-tp="reel-{r["num"]}">🎤 Развернуть для съёмки</button>
      <button class="status-btn" data-toggle-status>{'↩ Отменить отметку' if r["status"] == "ok" else '✓ Отметить записанным'}</button>
    </div>

    <div class="sec">
      <h3>Хук {hook_pill}</h3>
      <div class="hook">{html.escape(r["hook"])}</div>
    </div>

    <div class="sec">
      <h3>Текст для записи</h3>
      <div class="body-text" id="reel-{r["num"]}-text">{html.escape(r["body_text"])}</div>
    </div>

    {f'<div class="sec"><h3>Заметки к записи</h3><div class="note">{notes_html}</div></div>' if notes_html else ''}

    <div class="sec">
      <h3>CTA по площадкам</h3>
      <div class="cta-grid">{cta_html}</div>
    </div>

    <div class="sec">
      <h3>Референс</h3>
      <a class="ref-link" href="{html.escape(r["ref_url"])}" target="_blank" rel="noopener">📱 Открыть оригинал →</a>
    </div>

    {f'<div class="sec"><h3>Что было в оригинале (для контекста)</h3><button class="original-toggle" data-toggle="orig-{r["num"]}">📜 Показать транскрипт оригинала</button><div class="original-text" id="orig-{r["num"]}">{orig_html}</div></div>' if orig_html else ''}

  </div>
</details>'''


reel_cards = "\n\n".join(render_reel(r) for r in reels)

html_out = f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1a1612">
<title>Reels на съёмку — 2026-05-13</title>
<style>
*{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
html,body{{margin:0;padding:0;background:#1a1612;color:#f1ebe1;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:880px;margin:0 auto;padding:20px 16px 80px}}
header{{padding:8px 4px 22px;border-bottom:1px solid #3a3128;margin-bottom:18px}}
h1{{font-size:24px;margin:0 0 6px;font-weight:700;letter-spacing:-0.01em}}
.sub{{color:#a89c8c;font-size:14px}}
.stats{{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}}
.chip{{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;
  background:#221d18;border:1px solid #3a3128;font-size:13px;color:#a89c8c}}
.chip b{{color:#f1ebe1;font-weight:600}}
.dot{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.dot.ok{{background:#7fb069}}
.dot.wait{{background:#c8a165}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;align-items:center}}
.filter{{padding:8px 14px;border-radius:8px;background:#221d18;border:1px solid #3a3128;
  color:#a89c8c;font-size:13px;cursor:pointer;font-family:inherit}}
.filter.active{{background:#e8a04a;color:#1a1612;border-color:#e8a04a;font-weight:600}}
.search{{flex:1;min-width:160px;padding:9px 14px;border-radius:8px;background:#221d18;
  border:1px solid #3a3128;color:#f1ebe1;font-size:13px;font-family:inherit;outline:none}}
.search:focus{{border-color:#e8a04a}}
.edit-btn{{padding:9px 14px;border-radius:8px;background:#221d18;border:1px solid #3a3128;
  color:#f1ebe1;font-size:13px;cursor:pointer;font-family:inherit;text-decoration:none;
  display:inline-flex;align-items:center;gap:6px;font-weight:500}}
.edit-btn:hover{{border-color:#e8a04a;color:#e8a04a}}
.hint{{font-size:12px;color:#6e6359;margin-top:8px}}
.reset-btn{{font-size:11px;color:#6e6359;background:transparent;border:none;cursor:pointer;text-decoration:underline;font-family:inherit;padding:4px 0;margin-top:6px}}
.reset-btn:hover{{color:#c8a165}}

details{{background:#221d18;border:1px solid #3a3128;border-radius:14px;margin:12px 0;overflow:hidden}}
details[open]{{background:#2b251f}}
details[data-status="ok"]{{opacity:0.65}}
details[data-status="ok"][open]{{opacity:1}}
summary{{padding:14px 16px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:12px;
  user-select:none;outline:none}}
summary::-webkit-details-marker{{display:none}}
.num{{flex-shrink:0;width:38px;height:38px;border-radius:10px;background:#1a1612;
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;color:#e8a04a}}
.ttl{{flex:1;min-width:0;font-weight:600;font-size:15px;line-height:1.35}}
.badge{{flex-shrink:0;font-size:11px;padding:4px 8px;border-radius:6px;font-weight:600;letter-spacing:0.02em;text-transform:uppercase}}
.badge.ok{{background:rgba(127,176,105,0.15);color:#7fb069;border:1px solid rgba(127,176,105,0.3)}}
.badge.wait{{background:rgba(200,161,101,0.15);color:#c8a165;border:1px solid rgba(200,161,101,0.3)}}
.arrow{{flex-shrink:0;color:#a89c8c;transition:transform 0.2s;font-size:12px}}
details[open] .arrow{{transform:rotate(90deg)}}

.body{{padding:4px 18px 22px;border-top:1px solid #3a3128}}

.actions{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 6px}}
.copy-btn{{flex:1;min-width:200px;padding:14px 18px;border-radius:12px;
  background:linear-gradient(135deg,#e8a04a,#d97757);color:#1a1612;font-weight:700;
  font-size:16px;border:none;cursor:pointer;font-family:inherit;
  display:inline-flex;align-items:center;justify-content:center;gap:8px;letter-spacing:-0.01em}}
.copy-btn:hover{{filter:brightness(1.08)}}
.copy-btn.copied{{background:#7fb069;color:#0f1308}}
.teleprompter-btn{{padding:14px 18px;border-radius:12px;background:transparent;
  color:#f1ebe1;border:1px solid #3a3128;font-weight:600;font-size:14px;cursor:pointer;
  font-family:inherit;display:inline-flex;align-items:center;gap:8px}}
.teleprompter-btn:hover{{border-color:#e8a04a;color:#e8a04a}}
.status-btn{{padding:14px 18px;border-radius:12px;background:transparent;
  color:#a89c8c;border:1px solid #3a3128;font-weight:600;font-size:14px;cursor:pointer;
  font-family:inherit;display:inline-flex;align-items:center;gap:8px}}
.status-btn:hover{{border-color:#7fb069;color:#7fb069}}
details[data-status="ok"] .status-btn{{color:#7fb069;border-color:rgba(127,176,105,0.3)}}

.sec{{margin-top:18px}}
.sec h3{{font-size:12px;text-transform:uppercase;letter-spacing:0.08em;color:#e8a04a;
  margin:0 0 8px;font-weight:600;display:flex;align-items:center;gap:8px}}
.sec h3 .pill{{font-size:10px;background:rgba(232,160,74,0.15);color:#e8a04a;padding:2px 8px;
  border-radius:999px;text-transform:none;letter-spacing:0;font-weight:600;border:1px solid rgba(232,160,74,0.3)}}

a{{color:#f0b66c;text-decoration:none;border-bottom:1px solid rgba(240,182,108,0.3);word-break:break-word}}
a:hover{{border-bottom-color:#f0b66c}}
.muted{{color:#a89c8c}}

.hook{{background:linear-gradient(135deg,rgba(232,160,74,0.08),rgba(217,119,87,0.05));
  border:1px solid rgba(232,160,74,0.3);padding:16px 18px;border-radius:12px;
  font-size:17px;line-height:1.6;color:#f7e9d4;font-weight:500;white-space:pre-wrap}}
.body-text{{white-space:pre-wrap;font-size:18px;line-height:1.7;color:#f1ebe1;
  background:#1a1612;padding:18px 20px;border-radius:12px;border:1px solid #3a3128;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Georgia,serif}}
.note{{font-size:14px;color:#c4b8a5;padding:12px 14px;
  background:rgba(232,160,74,0.05);border-left:3px solid #e8a04a;border-radius:6px;line-height:1.55}}
.note ul{{margin:6px 0 0;padding-left:18px}}
.note li{{margin-bottom:4px}}
.note p{{margin:6px 0}}
.note code{{background:#1a1612;padding:1px 6px;border-radius:4px;font-size:13px;color:#f0b66c}}

.cta-grid{{display:grid;gap:8px;margin-top:6px}}
.cta-row{{padding:10px 12px;background:#1a1612;border-radius:8px;border:1px solid #3a3128;font-size:14px;line-height:1.5}}
.cta-row .platform{{color:#e8a04a;display:block;margin-bottom:3px;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;font-weight:700}}
.cta-row .codeword{{font-weight:700;color:#f7e9d4;background:rgba(232,160,74,0.12);padding:1px 6px;border-radius:4px}}

.ref-link{{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border-radius:8px;
  background:#1a1612;border:1px solid #3a3128;font-size:13px;color:#f0b66c;text-decoration:none}}
.ref-link:hover{{border-color:#e8a04a}}

.original-toggle{{cursor:pointer;font-size:13px;color:#a89c8c;
  padding:8px 12px;background:transparent;border:1px dashed #3a3128;border-radius:8px;
  display:inline-flex;align-items:center;gap:6px;font-family:inherit}}
.original-toggle:hover{{color:#e8a04a;border-color:#e8a04a}}
.original-text{{display:none;margin-top:10px;padding:14px 16px;background:#181410;
  border:1px solid #3a3128;border-radius:10px;font-size:13px;line-height:1.6;color:#a89c8c;white-space:pre-wrap}}
.original-text.shown{{display:block}}

.hidden{{display:none !important}}
footer{{margin-top:30px;padding:20px 4px;border-top:1px solid #3a3128;color:#a89c8c;
  font-size:13px;text-align:center}}

/* Суфлёр-режим: full-screen overlay */
.teleprompter{{position:fixed;inset:0;background:#0a0806;z-index:1000;
  padding:40px 8vw;overflow-y:auto;display:none}}
.teleprompter.active{{display:block}}
.teleprompter .tp-close{{position:fixed;top:16px;right:16px;background:#221d18;
  color:#f1ebe1;border:1px solid #3a3128;padding:10px 16px;border-radius:8px;
  cursor:pointer;font-family:inherit;font-size:14px;font-weight:600;z-index:1001}}
.teleprompter .tp-hook{{font-size:26px;line-height:1.5;color:#f7e9d4;font-weight:500;
  margin-bottom:24px;padding-bottom:24px;border-bottom:1px solid #3a3128;white-space:pre-wrap}}
.teleprompter .tp-body{{font-size:30px;line-height:1.6;color:#f1ebe1;white-space:pre-wrap}}
.teleprompter .tp-num{{color:#e8a04a;font-weight:700;font-size:14px;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:8px}}
.teleprompter .tp-ttl{{color:#a89c8c;font-size:16px;margin-bottom:30px}}
</style>
</head>
<body>

<div class="wrap">
  <header>
    <h1>🎬 Reels на съёмку — 13 мая</h1>
    <div class="sub">25 сценариев · автор · Claude Code · вертикалки</div>

    <div class="stats">
      <span class="chip"><span class="dot ok"></span>Записано: <b id="stat-ok">{n_ok}</b></span>
      <span class="chip"><span class="dot wait"></span>На запись: <b id="stat-wait">{n_wait}</b></span>
      <span class="chip">Всего: <b>{len(reels)}</b></span>
    </div>

    <div class="toolbar">
      <button class="filter active" data-f="all">Все</button>
      <button class="filter" data-f="wait">⏳ На запись</button>
      <button class="filter" data-f="ok">✓ Записанные</button>
      <input type="search" class="search" placeholder="🔎 Поиск по теме…" id="search">
      <a class="edit-btn" href="vscode://file/reels/production/input.md">📝 Открыть .md</a>
    </div>
    <button class="reset-btn" id="reset-btn">↻ Сбросить локальные отметки (вернуть как в .md)</button>
  </header>

  <div id="list">
{reel_cards}
  </div>

  <footer>
    Прогресс сохраняется в этом браузере (localStorage) · стиль «Крафтовый терминал»
  </footer>
</div>

<!-- Суфлёр-режим overlay -->
<div class="teleprompter" id="tp">
  <button class="tp-close" id="tp-close">✕ Закрыть</button>
  <div class="tp-num" id="tp-num"></div>
  <div class="tp-ttl" id="tp-ttl"></div>
  <div class="tp-hook" id="tp-hook"></div>
  <div class="tp-body" id="tp-body"></div>
</div>

<script>
const STORAGE_KEY = 'reels-2026-05-13-status';

function loadStatus() {{
  try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }} catch(e) {{ return {{}}; }}
}}
function saveStatus(s) {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}}

// Применить статус из localStorage поверх дефолтного
function applyStoredStatus() {{
  const stored = loadStatus();
  document.querySelectorAll('#list > details').forEach(d => {{
    const reelId = d.dataset.reel;
    if (stored[reelId]) {{
      d.dataset.status = stored[reelId];
      const badge = d.querySelector('.badge');
      const statusBtn = d.querySelector('.status-btn');
      if (stored[reelId] === 'ok') {{
        badge.className = 'badge ok';
        badge.textContent = '✓ Записано';
        if (statusBtn) statusBtn.textContent = '↩ Отменить отметку';
      }} else {{
        badge.className = 'badge wait';
        badge.textContent = '⏳ На запись';
        if (statusBtn) statusBtn.textContent = '✓ Отметить записанным';
      }}
    }}
  }});
  updateCounters();
}}

function updateCounters() {{
  let ok = 0, wait = 0;
  document.querySelectorAll('#list > details').forEach(d => {{
    if (d.dataset.status === 'ok') ok++;
    else wait++;
  }});
  document.getElementById('stat-ok').textContent = ok;
  document.getElementById('stat-wait').textContent = wait;
}}

// Переключение статуса записанности
document.querySelectorAll('[data-toggle-status]').forEach(btn => {{
  btn.addEventListener('click', (e) => {{
    e.preventDefault();
    const block = btn.closest('details');
    const reelId = block.dataset.reel;
    const newStatus = block.dataset.status === 'ok' ? 'wait' : 'ok';
    block.dataset.status = newStatus;
    const stored = loadStatus();
    stored[reelId] = newStatus;
    saveStatus(stored);
    const badge = block.querySelector('.badge');
    if (newStatus === 'ok') {{
      badge.className = 'badge ok';
      badge.textContent = '✓ Записано';
      btn.textContent = '↩ Отменить отметку';
    }} else {{
      badge.className = 'badge wait';
      badge.textContent = '⏳ На запись';
      btn.textContent = '✓ Отметить записанным';
    }}
    updateCounters();
    // Переприменить текущий фильтр (вдруг карточка скроется)
    const activeFilter = document.querySelector('.filter.active').dataset.f;
    applyFilter(activeFilter);
  }});
}});

// Сброс
document.getElementById('reset-btn').addEventListener('click', () => {{
  if (confirm('Сбросить все локальные отметки? Вернётся то что прописано в .md файле.')) {{
    localStorage.removeItem(STORAGE_KEY);
    location.reload();
  }}
}});

// Копирование в буфер
document.querySelectorAll('.copy-btn').forEach(btn => {{
  const originalLabel = btn.textContent;
  btn.addEventListener('click', async () => {{
    const targetId = btn.dataset.copyTarget;
    const block = btn.closest('details');
    const hook = block.querySelector('.hook').textContent.trim();
    const body = document.getElementById(targetId).textContent.trim();
    const full = hook + '\\n\\n' + body;
    try {{
      await navigator.clipboard.writeText(full);
      btn.classList.add('copied');
      btn.textContent = '✓ Скопировано — вставь в суфлёр';
      setTimeout(() => {{
        btn.classList.remove('copied');
        btn.textContent = originalLabel;
      }}, 2000);
    }} catch (e) {{
      alert('Не удалось скопировать: ' + e.message);
    }}
  }});
}});

// Развернуть транскрипт оригинала
document.querySelectorAll('.original-toggle').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const target = document.getElementById(btn.dataset.toggle);
    target.classList.toggle('shown');
    btn.textContent = target.classList.contains('shown')
      ? '📜 Скрыть транскрипт оригинала'
      : '📜 Показать транскрипт оригинала';
  }});
}});

// Фильтры
function applyFilter(f) {{
  document.querySelectorAll('#list > details').forEach(d => {{
    d.classList.toggle('hidden', f !== 'all' && d.dataset.status !== f);
  }});
}}
document.querySelectorAll('.filter').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilter(btn.dataset.f);
  }});
}});

// Поиск
document.getElementById('search').addEventListener('input', (e) => {{
  const q = e.target.value.toLowerCase().trim();
  document.querySelectorAll('#list > details').forEach(d => {{
    const title = (d.dataset.title || '') + ' ' + d.querySelector('.ttl').textContent.toLowerCase();
    d.classList.toggle('hidden', q && !title.includes(q));
  }});
}});

// Суфлёр-режим
document.querySelectorAll('.teleprompter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const block = btn.closest('details');
    const num = block.querySelector('.num').textContent;
    const ttl = block.querySelector('.ttl').textContent;
    const hook = block.querySelector('.hook').textContent;
    const body = block.querySelector('.body-text').textContent;
    document.getElementById('tp-num').textContent = 'Reel ' + num;
    document.getElementById('tp-ttl').textContent = ttl;
    document.getElementById('tp-hook').textContent = hook;
    document.getElementById('tp-body').textContent = body;
    document.getElementById('tp').classList.add('active');
    document.body.style.overflow = 'hidden';
  }});
}});
function closeTP() {{
  document.getElementById('tp').classList.remove('active');
  document.body.style.overflow = '';
}}
document.getElementById('tp-close').addEventListener('click', closeTP);
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') closeTP();
}});

// Старт
applyStoredStatus();
</script>

</body>
</html>
'''

OUT.write_text(html_out, encoding="utf-8")
print(f"Записано: {OUT}")
print(f"Reel'ов: {len(reels)} (ok={n_ok}, wait={n_wait})")
