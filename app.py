import json
import time

import streamlit as st
from ollama import Client

from core import storage
from core.agent import PLAN_SCHEMA, decision_prompt, analysis_prompt, run_plan
from core.tools import extract_json, get_folder_context, get_system_stats, process_uploaded_file

APP_VERSION = "1.3.0"

st.set_page_config(page_title=f"K1 AI Desktop v{APP_VERSION}", layout="wide")

client = Client(host='localhost:11434')

for key, default in {
    'chat_history': [],
    'chat_id': None,
    'project_id': None,
    'current_folder': "",
    'stop_processing': False,
    'uploaded_files_content': {},
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def new_chat():
    st.session_state.chat_history = []
    st.session_state.chat_id = None


def save_chat():
    st.session_state.chat_id = storage.save_chat(
        st.session_state.chat_id, st.session_state.project_id, st.session_state.chat_history)


def display_system_monitor(elapsed):
    stats = get_system_stats()
    cols = st.columns(5)
    cols[0].metric("CPU", f"{stats['cpu']:.1f}%")
    cols[1].metric("Memory", f"{stats['memory_percent']:.1f}%")
    cols[2].metric("Used", f"{stats['memory_used']:.2f}GB")
    cols[3].metric("Total", f"{stats['memory_total']:.2f}GB")
    cols[4].metric("Time", f"{elapsed:.1f}s")


def render_steps(steps):
    for s in steps:
        st.markdown(f"**{s['title']}**")
        if s.get('body'):
            st.code(s['body'], language=s.get('lang'))


with st.sidebar:
    st.write("### Project")
    projects = storage.load_projects()
    options = [None] + list(projects.keys())
    if st.session_state.project_id not in options:
        st.warning("The selected project no longer exists. Switched to chat only.")
        st.session_state.project_id = None
    selected = st.selectbox(
        "Project:", options,
        index=options.index(st.session_state.project_id),
        format_func=lambda pid: "No project (chat only)" if pid is None else projects[pid]['name'],
        label_visibility="collapsed",
    )
    if selected != st.session_state.project_id:
        st.session_state.project_id = selected
        new_chat()
        st.rerun()

    if st.session_state.project_id:
        st.session_state.current_folder = projects[st.session_state.project_id]['folder']
        st.caption(f"Folder: {st.session_state.current_folder}")
        with st.expander("Change folder"):
            changed_folder = st.text_input("New folder:", value=st.session_state.current_folder, key="change_folder")
            if st.button("Save folder", width="stretch"):
                try:
                    storage.update_project_folder(st.session_state.project_id, changed_folder)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        if st.button("Delete project", width="stretch"):
            storage.delete_project(st.session_state.project_id)
            st.session_state.project_id = None
            new_chat()
            st.rerun()
    else:
        st.session_state.current_folder = ""
        st.caption("No folder: chat only")

    with st.expander("New project"):
        p_name = st.text_input("Name:", key="new_project_name")
        p_folder = st.text_input("Folder:", key="new_project_folder", placeholder="empty = K1_AI_Desktop/projects/<name>")
        if st.button("Create", width="stretch"):
            try:
                st.session_state.project_id = storage.create_project(p_name, p_folder)
                new_chat()
                st.rerun()
            except Exception as e:
                st.error(f"Cannot create project: {e}")

    st.write("---")
    st.write("### Chats")
    if st.button("+ New chat", width="stretch"):
        new_chat()
        st.rerun()
    for c in storage.list_chats(st.session_state.project_id):
        col1, col2 = st.columns([5, 1])
        with col1:
            label = ("▶ " if c['id'] == st.session_state.chat_id else "") + c['title']
            if st.button(label, key=f"chat_{c['id']}", width="stretch"):
                st.session_state.chat_id = c['id']
                st.session_state.chat_history = c.get('messages', [])
                st.rerun()
        with col2:
            if st.button("🗑", key=f"delchat_{c['id']}"):
                storage.delete_chat(c['id'])
                if c['id'] == st.session_state.chat_id:
                    new_chat()
                st.rerun()

    st.write("---")
    st.write("### Upload File")
    uploaded_file = st.file_uploader("Choose file:", type=["txt", "md", "json", "csv", "pdf", "docx", "py", "js", "java", "cpp", "png", "jpg", "jpeg"], label_visibility="collapsed")
    if uploaded_file:
        file_data = process_uploaded_file(uploaded_file)
        st.session_state.uploaded_files_content[file_data['name']] = file_data
        st.success(f"Loaded: {file_data['name']}")

    if st.session_state.uploaded_files_content:
        st.write("**Files:**")
        for fname in list(st.session_state.uploaded_files_content.keys()):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"- {fname}")
            with col2:
                if st.button("X", key=f"del_{fname}"):
                    del st.session_state.uploaded_files_content[fname]
                    st.rerun()

    st.write("---")
    st.write("### Model")
    try:
        installed_models = [m.model for m in client.list().models]
    except Exception:
        installed_models = []
    if not installed_models:
        st.error("No models found. Is Ollama running?")
        installed_models = ["qwen3:8b"]
    default_model = "qwen3:8b" if "qwen3:8b" in installed_models else installed_models[0]
    model = st.selectbox("Select:", installed_models, index=installed_models.index(default_model), label_visibility="collapsed")
    think = st.toggle("Thinking (smarter, slower)", value=False)

    st.write("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Clear", width="stretch"):
            if st.session_state.chat_id:
                storage.delete_chat(st.session_state.chat_id)
            new_chat()
            st.rerun()
    with col2:
        if st.button("Stop", width="stretch"):
            st.session_state.stop_processing = True
            st.rerun()

st.write(f"## K1 AI Desktop `v{APP_VERSION}`")
st.write("### System Status")
display_system_monitor(0)
st.write("---")

for msg in st.session_state.chat_history:
    if msg['role'] == 'user':
        st.write(f"**You:** {msg['content']}")
    else:
        if msg.get('steps'):
            with st.expander(f"Steps ({len(msg['steps'])})", expanded=False):
                render_steps(msg['steps'])
        st.write(f"**AI:**\n\n{msg['content']}")
    st.write("---")

user_input = st.chat_input("Message: Enter to send | Shift+Enter for newline")

if user_input:
    st.session_state.stop_processing = False
    st.session_state.chat_history.append({'role': 'user', 'content': user_input})
    save_chat()

    st.write(f"**You:** {user_input}")
    monitor_placeholder = st.empty()
    status = st.status("Starting...", expanded=False)
    response_placeholder = st.empty()

    steps = []
    start_time = time.time()
    last_update = [start_time]

    def refresh_monitor(force=False):
        now = time.time()
        if force or now - last_update[0] >= 2:
            with monitor_placeholder.container():
                display_system_monitor(now - start_time)
            last_update[0] = now

    def check_stop():
        if st.session_state.stop_processing:
            raise KeyboardInterrupt("Stopped")

    def log_step(title, body=None, lang=None):
        steps.append({'title': title, 'body': body, 'lang': lang})
        status.update(label=title)
        status.markdown(f"**{title}**")
        if body:
            status.code(body, language=lang)
        refresh_monitor()

    def stream_answer(chunks, get_text):
        answer = ""
        with response_placeholder.container():
            box = st.empty()
            for chunk in chunks:
                check_stop()
                answer += get_text(chunk)
                box.markdown(answer)
                refresh_monitor()
        return answer

    try:
        refresh_monitor(force=True)
        check_stop()

        uploaded_context = ""
        if st.session_state.uploaded_files_content:
            uploaded_context = "\n\nUploaded Files:\n"
            for fname, fdata in st.session_state.uploaded_files_content.items():
                uploaded_context += f"\nFile: {fname} ({fdata['type']})\n```\n{fdata['content']}\n```\n"
            log_step("Attached uploaded files",
                     "\n".join(f"- {n} ({d['type']})" for n, d in st.session_state.uploaded_files_content.items()), "text")

        folder = st.session_state.current_folder
        if folder:
            folder_context = get_folder_context(folder)
            log_step(f"1. Scanned folder: {folder}", folder_context, "text")
            context = folder_context + uploaded_context

            status.update(label=f"2. Planning with {model}...")
            status.markdown(f"**2. Planning with {model}** (raw model output)")
            plan_box = status.empty()
            full_response = ""
            for chunk in client.generate(model=model, prompt=decision_prompt(context, user_input), stream=True, think=False, format=PLAN_SCHEMA):
                check_stop()
                full_response += chunk['response']
                plan_box.code(full_response, language="json")
                refresh_monitor()
            steps.append({'title': f"2. Planning with {model} (raw model output)", 'body': full_response, 'lang': "json"})

            decision = extract_json(full_response)
            log_step(f"Plan: {decision.get('plan', '')}",
                     json.dumps({k: decision.get(k, []) for k in ('files', 'commands', 'write', 'delete')}, indent=2, ensure_ascii=False), "json")

            results = run_plan(decision, folder, log_step, check_stop)
            check_stop()

            log_step("5. Generating answer...")
            answer = stream_answer(
                client.generate(model=model, prompt=analysis_prompt(context, user_input, results), stream=True, think=think),
                lambda c: c['response'])
        else:
            log_step("Chat mode (no project folder)")
            messages = [{'role': 'system', 'content': uploaded_context}] if uploaded_context else []
            messages += [{'role': m['role'], 'content': m['content']} for m in st.session_state.chat_history]
            status.update(label=f"Chatting with {model}...")
            answer = stream_answer(
                client.chat(model=model, messages=messages, stream=True, think=think),
                lambda c: c['message']['content'])

        elapsed = time.time() - start_time
        refresh_monitor(force=True)
        steps.append({'title': f"Done in {elapsed:.1f}s", 'body': None, 'lang': None})
        status.update(label=f"Done in {elapsed:.1f}s ({len(steps)} steps)", state="complete", expanded=False)

        st.session_state.chat_history.append({'role': 'assistant', 'content': answer, 'steps': steps})
        save_chat()

        time.sleep(0.5)
        st.rerun()

    except KeyboardInterrupt as e:
        status.update(label=f"Stopped: {e}", state="error")
        st.session_state.stop_processing = False
    except Exception as e:
        status.markdown(f"**Error:** {e}")
        status.update(label=f"Error: {e}", state="error", expanded=True)
