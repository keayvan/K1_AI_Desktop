"""Prompts and plan execution for project mode: plan -> read/run/write -> answer."""
import json

from core.tools import READ_ONLY_COMMANDS, GIT_READ_ONLY, read_file, execute_command, write_file

MAX_FILES = 3
MAX_COMMANDS = 2
MAX_WRITES = 3


def decision_prompt(context, user_input):
    return f"""{context}

User: {user_input}

RESPOND WITH ONLY JSON (no other text). Keys:
- "files": files to read (paths relative to the project folder)
- "commands": read-only commands to run. Allowed: {', '.join(sorted(READ_ONLY_COMMANDS))} (git only: {', '.join(sorted(GIT_READ_ONLY))}). No pipes, redirects or &&.
- "write": files to create or overwrite, as {{"path": "...", "content": "..."}} (for .docx, write the content as Markdown; it is converted to a real Word file)
- "plan": what you will do
Example:
{{"files": ["file1.py"], "commands": ["git log -5"], "write": [{{"path": "notes.txt", "content": "text"}}], "plan": "what you will do"}}
Use empty lists for anything not needed."""


def analysis_prompt(context, user_input, results):
    return f"""{context}

User: {user_input}

Files: {json.dumps(results['files'], ensure_ascii=False)[:1000]}

Commands: {json.dumps(results['commands'], ensure_ascii=False)[:1000]}

Written files: {json.dumps(results['writes'], ensure_ascii=False)[:1000]}

Provide answer."""


def run_plan(decision, folder, log, check_stop):
    """Carry out the model's plan. log(title, body, lang) reports each step."""
    results = {'files': {}, 'commands': {}, 'writes': {}}

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

    return results
