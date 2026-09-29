"""Projects and chat history, saved as JSON under data/."""
import json
import os
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CHATS_DIR = DATA_DIR / "chats"
PROJECTS_FILE = DATA_DIR / "projects.json"
DEFAULT_PROJECTS_DIR = APP_DIR / "projects"

CHATS_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_projects():
    return _read_json(PROJECTS_FILE, {})


def save_projects(projects):
    _write_json(PROJECTS_FILE, projects)


def create_project(name, folder=""):
    """Create a project. An empty folder means projects/<name> inside the app."""
    name = name.strip()
    if not name:
        raise ValueError("Name is required")
    folder = os.path.expanduser(folder.strip()) if folder.strip() else str(DEFAULT_PROJECTS_DIR / name)
    os.makedirs(folder, exist_ok=True)
    projects = load_projects()
    pid = datetime.now().strftime("%Y%m%d_%H%M%S")
    projects[pid] = {'name': name, 'folder': os.path.realpath(folder), 'created': datetime.now().isoformat()}
    save_projects(projects)
    return pid


def update_project_folder(pid, folder):
    folder = os.path.realpath(os.path.expanduser(folder.strip()))
    if not os.path.isdir(folder):
        raise ValueError(f"Folder does not exist: {folder}")
    projects = load_projects()
    projects[pid]['folder'] = folder
    save_projects(projects)


def delete_project(pid):
    """Delete a project and its chats. Files in the project folder are kept."""
    for c in list_chats(pid):
        delete_chat(c['id'])
    projects = load_projects()
    projects.pop(pid, None)
    save_projects(projects)


def list_chats(project_id):
    chats = [c for c in (_read_json(p, None) for p in CHATS_DIR.glob("*.json"))
             if c and c.get('project_id') == project_id]
    return sorted(chats, key=lambda c: c.get('updated', ''), reverse=True)


def load_chat(chat_id):
    return _read_json(CHATS_DIR / f"{chat_id}.json", None)


def save_chat(chat_id, project_id, history):
    """Save a chat and return its id (a new one is made when chat_id is None)."""
    if not history:
        return chat_id
    chat_id = chat_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    first = next((m['content'] for m in history if m['role'] == 'user'), 'New chat')
    old = load_chat(chat_id) or {}
    _write_json(CHATS_DIR / f"{chat_id}.json", {
        'id': chat_id,
        'title': old.get('title') or (first.strip().splitlines() or ['New chat'])[0][:40],
        'project_id': project_id,
        'created': old.get('created') or datetime.now().isoformat(),
        'updated': datetime.now().isoformat(),
        'messages': history,
    })
    return chat_id


def delete_chat(chat_id):
    (CHATS_DIR / f"{chat_id}.json").unlink(missing_ok=True)
