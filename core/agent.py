"""Agent loop: the model calls tools, sees each result, and decides the next step."""
import os

from core import tools

MAX_STEPS = 12
READ_LIMIT = 8000
OPTIONS = {'num_ctx': 8192}


def _tool(name, description, **params):
    required = [k for k, v in params.items() if not v.pop('optional', False)]
    return {'type': 'function', 'function': {
        'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': params, 'required': required},
    }}


TOOLS = [
    _tool('list_files', 'List files in the project folder or a subfolder.',
          path={'type': 'string', 'description': 'Subfolder, relative. Default "."', 'optional': True}),
    _tool('read_file', 'Read a file (text, code, or .docx). A .docx is shown as Markdown with $LaTeX$ equations. Always read a file before editing it.',
          path={'type': 'string', 'description': 'Path relative to the project folder'}),
    _tool('run_command', f"Run a read-only command. Allowed: {', '.join(sorted(tools.READ_ONLY_COMMANDS))} "
                         f"(git only: {', '.join(sorted(tools.GIT_READ_ONLY))}). No pipes, redirects or &&.",
          command={'type': 'string'}),
    _tool('write_file', 'Create a new file, or REPLACE ALL of an existing one (everything not in content is lost). '
                        'To extend or improve a document, read it first and include ALL existing content. For .docx write Markdown '
                        '(# headings, - bullets, **bold**, $$LaTeX$$ equations); it becomes real Word formatting.',
          path={'type': 'string'}, content={'type': 'string'}),
    _tool('append_file', 'Add content to the end of an existing file, keeping what is there. Same Markdown rules for .docx.',
          path={'type': 'string'}, content={'type': 'string'}),
    _tool('replace_in_file', 'Replace exact text inside a file. Read the file first so "old" matches exactly.',
          path={'type': 'string'}, old={'type': 'string'}, new={'type': 'string'}),
    _tool('delete_file', 'Move a file or folder to the Trash (the user can restore it). Only when the user asks.',
          path={'type': 'string'}),
]

SYSTEM_PROMPT = """You are K1, an assistant working inside the user's project folder: {folder}
Use the tools to look at and change files. Paths are relative to the project folder, e.g. "notes.docx", not "{folder}/notes.docx".
Work step by step: look first (list_files, read_file), then act, then check the result if needed.
When the task is done, stop calling tools and give a short answer saying what you did."""


def normalize_path(folder, path):
    """Make a model-given path relative to the project folder.

    Small models often repeat the folder name ("thermo/file.docx") or give the full path.
    """
    path = str(path).strip() or '.'
    base = os.path.realpath(folder)
    if os.path.isabs(path):
        return os.path.relpath(path, base) if os.path.commonpath([base, os.path.realpath(path)]) == base else path
    for prefix in (folder.rstrip('/') + '/', os.path.basename(base) + '/'):
        if path.startswith(prefix) and not os.path.exists(os.path.join(base, path)):
            return path[len(prefix):] or '.'
    return path


def run_tool(name, args, folder):
    args = args or {}
    path = normalize_path(folder, args.get('path', '.'))
    if name == 'list_files':
        base = tools.resolve_in_folder(folder, path)
        if not base:
            return f"[Not allowed: {path} is outside the project folder]"
        return "\n".join(tools.scan_folder(base, max_files=100)) or "[Empty folder]"
    if name == 'read_file':
        return tools.read_file(folder, path, limit=READ_LIMIT)
    if name == 'run_command':
        return tools.execute_command(str(args.get('command', '')), folder)
    if name == 'write_file':
        return tools.write_file(folder, path, str(args.get('content', '')))
    if name == 'append_file':
        return tools.append_file(folder, path, str(args.get('content', '')))
    if name == 'replace_in_file':
        return tools.replace_in_file(folder, path, str(args.get('old', '')), str(args.get('new', '')))
    if name == 'delete_file':
        return tools.trash_file(folder, path)
    return f"[Unknown tool: {name}]"


def _describe(name, args):
    args = args or {}
    if name == 'run_command':
        return f"$ {args.get('command', '')}"
    detail = str(args.get('path', '.'))
    if name == 'replace_in_file':
        detail += f" ({str(args.get('old', ''))[:40]!r} → {str(args.get('new', ''))[:40]!r})"
    return f"{name}: {detail}"


def _step_body(name, args, result):
    args = args or {}
    if name in ('write_file', 'append_file'):
        return f"{result}\n\n{str(args.get('content', ''))[:800]}", "text"
    if name == 'run_command':
        return result, "bash"
    return str(result)[:800], "text"


def run(client, model, messages, folder, think, log, check_stop, on_text):
    """Run the loop and return the final answer.

    messages: chat history (role/content). folder: project folder, or "" for plain chat (no tools).
    log(title, body, lang) reports a step; on_text(text) shows the reply as it streams.
    """
    convo = list(messages)
    if folder:
        convo.insert(0, {'role': 'system', 'content': SYSTEM_PROMPT.format(folder=folder)})
    tool_list = TOOLS if folder else None

    for step in range(1, MAX_STEPS + 1):
        check_stop()
        content, calls = "", []
        for chunk in client.chat(model=model, messages=convo, tools=tool_list, stream=True, think=think, options=OPTIONS):
            check_stop()
            if chunk.message.content:
                content += chunk.message.content
                on_text(content)
            if chunk.message.tool_calls:
                calls.extend(chunk.message.tool_calls)

        convo.append({'role': 'assistant', 'content': content, 'tool_calls': calls})
        if not calls:
            return content
        if content.strip():
            log(f"{step}. Model: {content.strip()[:80]}", content, "text")
            on_text("")

        for call in calls:
            check_stop()
            name, args = call.function.name, call.function.arguments
            result = run_tool(name, args, folder)
            body, lang = _step_body(name, args, result)
            log(f"{step}. {_describe(name, args)}", body, lang)
            convo.append({'role': 'tool', 'content': str(result), 'tool_name': name})

    log(f"Reached the limit of {MAX_STEPS} steps", None, None)
    convo.append({'role': 'user', 'content': 'Stop using tools now and summarize what you did and what is left.'})
    content = ""
    for chunk in client.chat(model=model, messages=convo, stream=True, think=think, options=OPTIONS):
        check_stop()
        content += chunk.message.content or ""
        on_text(content)
    return content
