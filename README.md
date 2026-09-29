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
pip install -r requirements.txt
ollama pull qwen3:8b
streamlit run app.py
```
