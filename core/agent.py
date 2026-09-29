"""Prompts and plan execution for project mode: plan -> read/run/write -> answer."""
import json

from core.tools import READ_ONLY_COMMANDS, GIT_READ_ONLY, read_file, execute_command, write_file, append_file, replace_in_file, trash_file

MAX_FILES = 3
MAX_COMMANDS = 2
MAX_WRITES = 3
MAX_DELETES = 5

# Passed to Ollama as `format` so the model must return valid JSON with these keys.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": {"type": "string"}},
        "commands": {"type": "array", "items": {"type": "string"}},
        "write": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
        "append": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
        "replace": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
                "required": ["path", "old", "new"],
            },
        },
        "delete": {"type": "array", "items": {"type": "string"}},
        "plan": {"type": "string"},
    },
    "required": ["files", "commands", "write", "append", "replace", "delete", "plan"],
}


def decision_prompt(context, user_input):
    return f"""{context}

User: {user_input}

RESPOND WITH ONLY JSON (no other text). Keys:
- "files": files to read (paths relative to the project folder)
- "commands": read-only commands to run. Allowed: {', '.join(sorted(READ_ONLY_COMMANDS))} (git only: {', '.join(sorted(GIT_READ_ONLY))}). No pipes, redirects or &&. To read a file (including .docx), put it in "files", not in a command.
- "write": NEW files to create (or fully overwrite), as {{"path": "...", "content": "..."}}
- "append": add text to the END of an existing file, as {{"path": "...", "content": "..."}}. Use this when the user asks to add something to a file; the existing content is kept.
- "replace": change text inside an existing file, as {{"path": "...", "old": "exact text", "new": "new text"}}
For .docx, write content as Markdown (# headings, - bullets, **bold**); it becomes real Word formatting.
- "delete": files or folders to delete (they are moved to the Trash, so the user can restore them). Only when the user asks to delete.
- "plan": what you will do
Example:
{{"files": ["file1.py"], "commands": ["git log -5"], "write": [{{"path": "notes.txt", "content": "text"}}], "append": [], "replace": [], "delete": ["old.txt"], "plan": "what you will do"}}
Use empty lists for anything not needed."""


def analysis_prompt(context, user_input, results):
    return f"""{context}

User: {user_input}

Files: {json.dumps(results['files'], ensure_ascii=False)[:1000]}

Commands: {json.dumps(results['commands'], ensure_ascii=False)[:1000]}

Written files: {json.dumps(results['writes'], ensure_ascii=False)[:1000]}

Appended: {json.dumps(results['appends'], ensure_ascii=False)[:1000]}

Replaced: {json.dumps(results['replaces'], ensure_ascii=False)[:1000]}

Deleted (moved to Trash): {json.dumps(results['deletes'], ensure_ascii=False)[:1000]}

Provide answer."""


def run_plan(decision, folder, log, check_stop):
    """Carry out the model's plan. log(title, body, lang) reports each step."""
    results = {'files': {}, 'commands': {}, 'writes': {}, 'appends': {}, 'replaces': {}, 'deletes': {}}

    for idx, path in enumerate(decision.get("files", [])[:MAX_FILES]):
        check_stop()
        content = read_file(folder, str(path))
        results['files'][path] = content
        log(f"3.{idx + 1} Read file: {path}", content[:800], "text")

    for idx, cmd in enumerate(decision.get("commands", [])[:MAX_COMMANDS]):
        check_stop()
        output = execute_command(str(cmd), folder)
        results['commands'][cmd] = output
        log(f"4.{idx + 1} Ran command: $ {cmd}", output, "bash")

    writes = [w for w in decision.get("write", []) if isinstance(w, dict) and w.get("path")][:MAX_WRITES]
    for idx, w in enumerate(writes):
        check_stop()
        content = str(w.get("content", ""))
        outcome = write_file(folder, str(w["path"]), content)
        results['writes'][w["path"]] = outcome
        log(f"4w.{idx + 1} Wrote file: {w['path']}", f"{outcome}\n\n{content[:800]}", "text")

    appends = [w for w in decision.get("append", []) if isinstance(w, dict) and w.get("path")][:MAX_WRITES]
    for idx, w in enumerate(appends):
        check_stop()
        content = str(w.get("content", ""))
        outcome = append_file(folder, str(w["path"]), content)
        results['appends'][w["path"]] = outcome
        log(f"4a.{idx + 1} Appended to: {w['path']}", f"{outcome}\n\n{content[:800]}", "text")

    replaces = [w for w in decision.get("replace", []) if isinstance(w, dict) and w.get("path")][:MAX_WRITES]
    for idx, w in enumerate(replaces):
        check_stop()
        outcome = replace_in_file(folder, str(w["path"]), str(w.get("old", "")), str(w.get("new", "")))
        results['replaces'][w["path"]] = outcome
        log(f"4r.{idx + 1} Replaced in: {w['path']}", f"{outcome}\n\n- {w.get('old', '')}\n+ {w.get('new', '')}", "diff")

    for idx, path in enumerate(decision.get("delete", [])[:MAX_DELETES]):
        check_stop()
        outcome = trash_file(folder, str(path))
        results['deletes'][path] = outcome
        log(f"4d.{idx + 1} Deleted (to Trash): {path}", outcome, "text")

    return results
