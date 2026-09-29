# K1 AI Desktop

A local AI desktop assistant built with Streamlit and [Ollama](https://ollama.com). Everything runs on your machine.

## Features
- Chat with local models (the list comes from `ollama list`)
- Projects: link a folder so the AI can read files, run safe commands and write files (including real `.docx`)
- Chat history saved per project in `data/`
- Collapsible step-by-step log of what the AI read, ran and wrote
- Optional "Thinking" mode for models that support it
- Live CPU and memory monitor

## Run
```bash
./run.sh
```
The first run creates `.venv/` and installs `requirements.txt`. Then pull a model:
```bash
ollama pull qwen3:8b
```
To keep Ollama's models inside this folder, run `./setup_models.sh` once (needs sudo).

## Structure
```
app.py            Streamlit UI
core/storage.py   projects and chat history (data/)
core/tools.py     read files, read-only commands, write/append/replace (.docx is read as Markdown and LaTeX becomes Word equations), delete to Trash
core/agent.py     agent loop: the model calls tools step by step (Ollama tool calling)
run.sh            start the app with .venv
setup_models.sh   move Ollama models into models/
data/             chats and projects.json   (not in git)
models/           Ollama models             (not in git)
projects/         default project folders   (not in git)
```

## Safety
In project mode the AI works in a loop: it calls a tool, sees the result, and picks the next step (up to 12 steps). It can only run read-only commands (`ls`, `cat`, `grep`, `find`, `git log/diff/status`, ...), without a shell, so pipes and `&&` do not work. Reading, writing and deleting are limited to the project folder. Deleted files go to the system Trash, and every file is backed up to `data/backups/` before it is changed.
