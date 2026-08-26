"""HTML-рендеринг YouTube-сценария — светлый Apple-дизайн с редактированием."""
import html
import re
import functools
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


@functools.cache
def _load_asset(filename: str) -> str:
    return (TEMPLATES_DIR / filename).read_text(encoding="utf-8")


def _esc(text) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def render_scenario_html(title: str, scenario_text: str) -> str:
    """Parse LLM scenario output and render as interactive HTML."""

    sections = _parse_sections(scenario_text)
    body = _render_sections(sections)
    css = _load_asset("base.css")

    scenario_css = """
    .edit-hint {
        text-align: center; padding: 10px 0 6px; font-size: 0.78em;
        color: var(--text-secondary); opacity: 0.7;
    }
    .section[contenteditable="true"]:focus {
        outline: 2px solid var(--accent); border-radius: 16px;
    }
    .copy-bar {
        position: fixed; bottom: 0; left: 0; right: 0; z-index: 100;
        background: var(--surface-solid); border-top: 1px solid var(--border);
        padding: 12px 20px; padding-bottom: calc(12px + env(safe-area-inset-bottom, 0px));
        display: flex; gap: 10px; justify-content: center;
    }
    .copy-bar button {
        padding: 12px 24px; border: none; border-radius: 12px;
        font-size: 0.9em; font-weight: 600; cursor: pointer;
        transition: all 0.2s;
    }
    .btn-edit {
        background: var(--surface); color: var(--text-primary);
        border: 1px solid var(--border) !important;
    }
    .btn-edit.active { background: var(--accent); color: white; border-color: var(--accent) !important; }
    .btn-copy { background: var(--accent); color: white; }
    .btn-copy:active { transform: scale(0.95); }
    .copy-toast {
        position: fixed; top: 60px; left: 50%; transform: translateX(-50%);
        background: #1D1D1F; color: white; padding: 10px 24px;
        border-radius: 12px; font-size: 0.85em; font-weight: 600;
        opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 200;
    }
    .copy-toast.show { opacity: 1; }
    body { padding-bottom: 80px; }
    """

    scenario_js = """
    function toggleEdit() {
        const sections = document.querySelectorAll('.section');
        const btn = document.getElementById('editBtn');
        const isEditing = btn.classList.contains('active');
        sections.forEach(s => {
            s.contentEditable = isEditing ? 'false' : 'true';
        });
        btn.classList.toggle('active');
        btn.textContent = isEditing ? '✏️ Редактировать' : '✏️ Готово';
    }
    function copyAll() {
        const container = document.querySelector('.container');
        const sections = container.querySelectorAll('.section');
        let text = '';
        sections.forEach(s => { text += s.innerText + '\\n\\n'; });
        navigator.clipboard.writeText(text.trim()).then(() => {
            const toast = document.getElementById('copyToast');
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 1500);
        }).catch(() => {
            // fallback
            const ta = document.createElement('textarea');
            ta.value = text.trim();
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            const toast = document.getElementById('copyToast');
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 1500);
        });
    }
    // Progress bar
    window.addEventListener('scroll', () => {
        const h = document.documentElement.scrollHeight - window.innerHeight;
        const pct = h > 0 ? (window.scrollY / h) * 100 : 0;
        const fill = document.getElementById('progressFill');
        if (fill) fill.style.width = pct + '%';
    });
    // Fade-in — progressive enhancement
    if (typeof IntersectionObserver !== 'undefined') {
        const obs = new IntersectionObserver(entries => {
            entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('visible'); });
        }, { threshold: 0.1 });
        document.querySelectorAll('.fade-in').forEach(el => {
            el.classList.add('will-animate');
            obs.observe(el);
        });
    }
    // Smooth TOC scroll
    document.querySelectorAll('.toc a').forEach(a => {
        a.addEventListener('click', e => {
            e.preventDefault();
            const target = document.querySelector(a.getAttribute('href'));
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    });
    """

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" crossorigin="anonymous">
<title>{_esc(title)} — Сценарий</title>
<style>{css}\n{scenario_css}</style>
</head>
<body>
<div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
<div class="container">
  <div class="header">
    <h1>📹 Сценарий</h1>
    <p class="summary">{_esc(title)}</p>
  </div>
  <p class="edit-hint">Нажми «Редактировать» чтобы править текст прямо здесь</p>
  {body}
  <div class="footer">
    <p style="font-weight:700;font-size:0.9em;margin-bottom:4px;">Транскрибатор</p>
    <p><a href="https://t.me/Iitrans_bot">@Iitrans_bot</a></p>
  </div>
</div>
<div id="copyToast" class="copy-toast">Скопировано!</div>
<div class="copy-bar">
  <button class="btn-edit" id="editBtn" onclick="toggleEdit()">✏️ Редактировать</button>
  <button class="btn-copy" onclick="copyAll()">📋 Скопировать</button>
</div>
<script>{scenario_js}</script>
</body>
</html>"""


SECTION_PATTERNS = [
    (r'(?:^|\n)\s*(?:<b>)?\s*(?:#+)?\s*(\d+)\.\s*(.+?)(?:</b>)?\s*(?:\n|$)', None),
    (r'(?:^|\n)\s*(?:<b>)?\s*(?:#+)?\s*(ХУК|HOOK|OPEN LOOP|СТРУКТУРА|CTA|ПРИЗЫВ|МЕТА|СЦЕНАРИЙ|ГОТОВЫЙ СЦЕНАРИЙ)(.*)(?:</b>)?\s*(?:\n|$)', None),
]

SECTION_ICONS = {
    "хук": "🎯",
    "hook": "🎯",
    "open loop": "🪝",
    "open loops": "🪝",
    "структура": "📐",
    "cta": "📢",
    "призыв": "📢",
    "мета": "📊",
    "сценарий": "🎬",
    "готовый": "🎬",
}


def _get_icon(title: str) -> str:
    t = title.lower().strip()
    for key, icon in SECTION_ICONS.items():
        if key in t:
            return icon
    return "📌"


def _parse_sections(text: str) -> list:
    """Parse scenario text into sections by numbered headers or known keywords."""
    # Split by numbered headers: "1. TITLE" or "<b>1. TITLE</b>"
    pattern = r'(?:^|\n)\s*(?:<b>)?\s*(\d+)\.\s*(.+?)(?:</b>)?\s*\n'
    splits = list(re.finditer(pattern, text))

    if len(splits) < 2:
        # Try markdown headers
        pattern2 = r'(?:^|\n)\s*#{1,3}\s*(?:\d+\.)?\s*(.+?)\s*\n'
        splits2 = list(re.finditer(pattern2, text))
        if len(splits2) >= 2:
            sections = []
            for i, m in enumerate(splits2):
                title = m.group(1).strip()
                title = re.sub(r'</?b>', '', title).strip()
                start = m.end()
                end = splits2[i+1].start() if i+1 < len(splits2) else len(text)
                content = text[start:end].strip()
                sections.append({"title": title, "content": content, "icon": _get_icon(title)})
            return sections

    if splits:
        sections = []
        for i, m in enumerate(splits):
            title = m.group(2).strip()
            title = re.sub(r'</?b>', '', title).strip()
            start = m.end()
            end = splits[i+1].start() if i+1 < len(splits) else len(text)
            content = text[start:end].strip()
            sections.append({"title": title, "content": content, "icon": _get_icon(title)})
        return sections

    # Fallback: single section
    return [{"title": "Сценарий", "content": text.strip(), "icon": "📹"}]


def _format_content(content: str) -> str:
    """Convert plain text content to HTML paragraphs, preserving structure."""
    # Already has HTML tags? Keep as-is but ensure paragraphs
    if '<b>' in content or '<i>' in content:
        lines = content.split('\n')
        result = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith('- ') or line.startswith('• '):
                result.append(f'<p style="padding-left:16px">{line}</p>')
            elif line.startswith('<'):
                result.append(line)
            else:
                result.append(f'<p>{line}</p>')
        return '\n'.join(result)

    # Plain text
    lines = content.split('\n')
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('- ') or line.startswith('• '):
            result.append(f'<p style="padding-left:16px">{_esc(line)}</p>')
        elif line.startswith('**') and line.endswith('**'):
            result.append(f'<p><b>{_esc(line[2:-2])}</b></p>')
        else:
            result.append(f'<p>{_esc(line)}</p>')
    return '\n'.join(result)


def _render_sections(sections: list) -> str:
    """Render parsed sections as HTML with TOC."""
    if not sections:
        return ""

    # TOC
    toc_items = ""
    for i, s in enumerate(sections):
        sid = f"s{i}"
        toc_items += f'<a href="#{sid}"><span class="toc-num">{i+1}</span><span class="toc-icon">{s["icon"]}</span>{_esc(s["title"])}</a>\n'
    toc = f'<div class="toc"><div class="toc-title">Содержание</div>\n{toc_items}</div>'

    # Sections
    html_parts = [toc]
    for i, s in enumerate(sections):
        sid = f"s{i}"
        formatted = _format_content(s["content"])
        html_parts.append(f'''<div class="section fade-in" id="{sid}">
<div class="section-header">
<span class="section-icon">{s["icon"]}</span>
<span class="section-title">{_esc(s["title"])}</span>
</div>
<div class="card">{formatted}</div>
</div>''')

    return '\n'.join(html_parts)
