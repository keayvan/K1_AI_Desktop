"""What the AI can do inside a project folder: read, run read-only commands, write."""
import base64
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import psutil

# Only read-only tools. No shell, so pipes, redirects and `&&` are not possible.
READ_ONLY_COMMANDS = {'ls', 'find', 'grep', 'cat', 'head', 'tail', 'wc', 'tree', 'stat', 'file', 'git'}
GIT_READ_ONLY = {'log', 'status', 'diff', 'show', 'branch', 'ls-files', 'blame', 'rev-parse'}
FIND_BLOCKED = {'-exec', '-execdir', '-ok', '-okdir', '-delete', '-fprint', '-fprint0', '-fprintf', '-fls'}


def resolve_in_folder(base, rel_path):
    """Return the absolute path, or None if it points outside base."""
    base = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base, rel_path))
    return target if os.path.commonpath([base, target]) == base else None


def read_file(base, rel_path, limit=2000):
    target = resolve_in_folder(base, rel_path)
    if not target:
        return f"[Not allowed: {rel_path} is outside the project folder]"
    if not os.path.isfile(target):
        return "[Not found]"
    if target.lower().endswith('.docx'):
        try:
            from docx import Document
            return "\n".join(p.text for p in Document(target).paragraphs)[:limit]
        except Exception as e:
            return f"[Cannot read docx: {e}]"
    try:
        with open(target, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(limit)
    except Exception:
        return "[Cannot read]"


def check_command(args):
    """Return an error string if the command is not allowed, else None."""
    name = args[0]
    if name not in READ_ONLY_COMMANDS:
        return f"[Not allowed: {name}. Allowed: {', '.join(sorted(READ_ONLY_COMMANDS))}]"
    if name == 'git':
        if len(args) < 2 or args[1] not in GIT_READ_ONLY:
            return f"[Not allowed: only git {', '.join(sorted(GIT_READ_ONLY))}]"
        if any(a.startswith('--output') or a.startswith('--ext-diff') for a in args):
            return "[Not allowed: git option that writes files or runs programs]"
    if name == 'find' and FIND_BLOCKED & set(args):
        return "[Not allowed: find option that runs commands or writes/deletes files]"
    return None


def execute_command(cmd, cwd):
    try:
        args = shlex.split(cmd)
    except ValueError as e:
        return f"[Invalid command: {e}]"
    if not args:
        return "[Empty command]"
    error = check_command(args)
    if error:
        return error
    if args[0] == 'git' and args[1] in {'log', 'diff', 'show'}:
        args[2:2] = ['--no-ext-diff', '--no-textconv']
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=15)
        raw = result.stdout + result.stderr
        if b'\x00' in raw[:8000] or raw.startswith(b'PK\x03\x04') or raw.startswith(b'%PDF'):
            return '[Binary output (e.g. .docx, .pdf, image). Use "files" to read documents instead of commands.]'
        output = raw.decode('utf-8', errors='replace')[:3000]
        return output or "[Empty]"
    except subprocess.TimeoutExpired:
        return "[Timeout]"
    except Exception as e:
        return f"[Error: {e}]"


def _add_markdown_runs(paragraph, text):
    for i, part in enumerate(re.split(r'\*\*', text)):
        if part:
            paragraph.add_run(part).bold = (i % 2 == 1)


MATH_RE = re.compile(r'\$\$.+?\$\$|\\\(.+?\\\)|\\\[.+?\\\]|(?<![\\$])\$[^$\s][^$]*?\$')


def _join_math_blocks(content):
    """Put multi-line $$...$$ or \\[...\\] blocks on one line so each becomes one paragraph."""
    content = re.sub(r'\$\$(.+?)\$\$', lambda m: '$$' + ' '.join(m.group(1).split()) + '$$', content, flags=re.S)
    return re.sub(r'\\\[(.+?)\\\]', lambda m: '$$' + ' '.join(m.group(1).split()) + '$$', content, flags=re.S)


def _pandoc_paragraph(text):
    """Convert one Markdown line with LaTeX math to a docx paragraph element (real Word equations)."""
    import copy
    import tempfile
    import pypandoc
    from docx import Document
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'p.docx')
        pypandoc.convert_text(text, 'docx', format='markdown+tex_math_dollars+tex_math_single_backslash', outputfile=out)
        paragraphs = Document(out).paragraphs
        return copy.deepcopy(paragraphs[0]._p) if paragraphs else None


def _add_math_paragraph(doc, text, style=None):
    paragraph = doc.add_paragraph(style=style)
    try:
        source = _pandoc_paragraph(text)
    except Exception:
        source = None
    if source is None:
        _add_markdown_runs(paragraph, text)
        return
    for child in list(source):
        if not child.tag.endswith('}pPr'):
            paragraph._p.append(child)


def _add_markdown(doc, content):
    """Add simple Markdown (headings, bullets, numbered lists, bold, LaTeX math) to a docx Document."""
    for line in _join_math_blocks(content).splitlines():
        stripped = line.strip()
        if stripped.startswith('```'):
            continue
        heading = re.match(r'^(#{1,6})\s+(.*)', stripped)
        bullet = re.match(r'^[-*]\s+(.*)', stripped)
        numbered = re.match(r'^\d+\.\s+(.*)', stripped)
        if heading:
            doc.add_heading(heading.group(2).replace('**', '').replace('$', ''), level=min(len(heading.group(1)), 4))
            continue
        if bullet:
            text, style = bullet.group(1), 'List Bullet'
        elif numbered:
            text, style = numbered.group(1), 'List Number'
        elif stripped and set(stripped) != {'-'}:
            text, style = stripped, None
        else:
            continue
        if MATH_RE.search(text):
            _add_math_paragraph(doc, text, style)
        else:
            _add_markdown_runs(doc.add_paragraph(style=style), text)


def fix_docx_math(target):
    """Turn paragraphs that contain LaTeX ($$...$$, $...$) into real Word equations. Returns how many."""
    from docx import Document
    doc = Document(target)
    count = 0
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not MATH_RE.search(text):
            continue
        try:
            source = _pandoc_paragraph(text)
        except Exception:
            continue
        if source is None:
            continue
        for child in list(paragraph._p):
            if not child.tag.endswith('}pPr'):
                paragraph._p.remove(child)
        for child in list(source):
            if not child.tag.endswith('}pPr'):
                paragraph._p.append(child)
        count += 1
    if count:
        doc.save(target)
    return count


def write_docx(target, content):
    from docx import Document
    doc = Document()
    _add_markdown(doc, content)
    doc.save(target)


def write_file(base, rel_path, content):
    target = resolve_in_folder(base, rel_path)
    if not target:
        return f"[Not allowed: {rel_path} is outside the project folder]"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if target.lower().endswith('.docx'):
            write_docx(target, content)
        else:
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)
        return f"[Wrote {len(content)} chars to {target}]"
    except Exception as e:
        return f"[Error: {e}]"


def trash_file(base, rel_path):
    """Move a file or folder inside the project to the system Trash (recoverable)."""
    target = resolve_in_folder(base, rel_path)
    if not target:
        return f"[Not allowed: {rel_path} is outside the project folder]"
    if target == os.path.realpath(base):
        return "[Not allowed: cannot delete the project folder itself]"
    if not os.path.lexists(target):
        return "[Not found]"
    try:
        result = subprocess.run(['/usr/bin/gio', 'trash', target], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return f"[Error: {result.stderr.strip()}]"
        return f"[Moved to Trash: {target}]"
    except Exception as e:
        return f"[Error: {e}]"


def append_file(base, rel_path, content):
    """Add content to the end of a file. Existing .docx formatting is kept."""
    target = resolve_in_folder(base, rel_path)
    if not target:
        return f"[Not allowed: {rel_path} is outside the project folder]"
    if not os.path.isfile(target):
        return f"[Not found: {rel_path}. Use list_files to check the name, or write_file to create a new file]"
    try:
        if target.lower().endswith('.docx'):
            from docx import Document
            doc = Document(target)
            _add_markdown(doc, content)
            doc.save(target)
        else:
            with open(target, 'a', encoding='utf-8') as f:
                f.write(("\n" if not content.startswith("\n") else "") + content)
        return f"[Appended {len(content)} chars to {target}]"
    except Exception as e:
        return f"[Error: {e}]"


def replace_in_file(base, rel_path, old, new):
    """Replace text in a file. In .docx, runs keep their formatting when possible."""
    target = resolve_in_folder(base, rel_path)
    if not target:
        return f"[Not allowed: {rel_path} is outside the project folder]"
    if not os.path.isfile(target):
        return "[Not found]"
    if not old:
        return "[Nothing to replace: 'old' is empty]"
    try:
        if target.lower().endswith('.docx'):
            from docx import Document
            doc = Document(target)
            count = 0
            paragraphs = list(doc.paragraphs) + [p for t in doc.tables for row in t.rows for cell in row.cells for p in cell.paragraphs]
            for p in paragraphs:
                if old not in p.text:
                    continue
                hits = sum(r.text.count(old) for r in p.runs)
                if hits:
                    for r in p.runs:
                        r.text = r.text.replace(old, new)
                    count += hits
                else:
                    count += p.text.count(old)
                    text = p.text.replace(old, new)
                    for r in p.runs[1:]:
                        r.text = ""
                    p.runs[0].text = text
            if count:
                doc.save(target)
                fix_docx_math(target)
        else:
            with open(target, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
            count = text.count(old)
            if count:
                with open(target, 'w', encoding='utf-8') as f:
                    f.write(text.replace(old, new))
        return f"[Replaced {count} occurrence(s) in {target}]" if count else f"[Text not found in {target}]"
    except Exception as e:
        return f"[Error: {e}]"


def scan_folder(folder_path, max_files=30):
    items = []
    try:
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in sorted(files)[:max_files]:
                if not file.startswith('.'):
                    items.append(os.path.relpath(os.path.join(root, file), folder_path))
    except Exception:
        pass
    return items


def get_folder_context(folder_path):
    context = "Project Files:\n"
    for f in scan_folder(folder_path)[:20]:
        context += f"  - {f}\n"
    try:
        branch = subprocess.check_output(['git', '-C', folder_path, 'rev-parse', '--abbrev-ref', 'HEAD'],
                                         text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        context += f"\nBranch: {branch}\n"
    except Exception:
        pass
    return context


def extract_json(text):
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception:
        pass
    return {"files": [], "commands": [], "write": [], "plan": "Parse error"}


def process_uploaded_file(uploaded_file):
    file_name = uploaded_file.name
    file_ext = Path(file_name).suffix.lower()
    try:
        if file_ext in ['.txt', '.md', '.log', '.json', '.csv',
                        '.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.rb']:
            content = uploaded_file.read().decode('utf-8', errors='ignore')
            kind = {'.json': 'json', '.csv': 'csv'}.get(file_ext, 'text' if file_ext in ['.txt', '.md', '.log'] else 'code')
            return {'name': file_name, 'type': kind, 'content': content[:5000]}
        if file_ext == '.pdf':
            import PyPDF2
            text = "".join(page.extract_text() or "" for page in PyPDF2.PdfReader(uploaded_file).pages[:5])
            return {'name': file_name, 'type': 'pdf', 'content': text[:5000]}
        if file_ext == '.docx':
            from docx import Document
            text = "\n".join(p.text for p in Document(uploaded_file).paragraphs)
            return {'name': file_name, 'type': 'docx', 'content': text[:5000]}
        if file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
            image_data = base64.b64encode(uploaded_file.read()).decode()
            return {'name': file_name, 'type': 'image', 'content': f'[Image: {file_name}]', 'base64': image_data}
        return {'name': file_name, 'type': 'unknown', 'content': f'[Unsupported: {file_ext}]'}
    except Exception as e:
        return {'name': file_name, 'type': 'error', 'content': f'[Error: {e}]'}


def get_system_stats():
    try:
        memory = psutil.virtual_memory()
        return {
            'cpu': psutil.cpu_percent(interval=0.01),
            'memory_percent': memory.percent,
            'memory_used': memory.used / (1024**3),
            'memory_total': memory.total / (1024**3),
        }
    except Exception:
        return {'cpu': 0, 'memory_percent': 0, 'memory_used': 0, 'memory_total': 0}
