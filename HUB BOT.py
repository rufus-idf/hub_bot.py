import streamlit as st
import pandas as pd
import google.generativeai as genai
import gspread
import json
import uuid
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
# 1. Your existing Master Schedule URL (The Map)
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1azbcaaIgw7K_MGZJfYdaX4mTvsYBx48ApdQ0HM8mNdA/edit"
LINKS_TAB_NAME = "AI_LINKS"
MEMORY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1DDxAADCvTUcvKdeTb76giFBLIa3Yb1XOeGievJ_cung/edit"
STOCK_SHEET_URL = "https://docs.google.com/spreadsheets/d/1E2GQfGkxkdbz0RmbbPcaIrMzmkJLC3MlNbGr4FT6FvM/edit?gid=2110353921#gid=2110353921"

LOGS_TAB_NAME = "CHAT_LOGS"
REF_DATA_TAB_NAME = "Ref_Data"

# 1. Page Config
st.set_page_config(page_title="Project Hub", layout="wide", initial_sidebar_state="expanded")

# --- CSS ---
st.markdown("""
    <style>
        [data-testid="stSidebar"] { min-width: 300px; }
        div.stButton > button { width: 100%; border-radius: 5px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# 2. Setup Gemini
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('models/gemini-2.0-flash')
else:
    st.error("Missing Gemini API Key in Secrets")

# 3. Setup GSpread
if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
    secrets = st.secrets["connections"]["gsheets"]
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_info({
        "type": secrets["type"],
        "project_id": secrets["project_id"],
        "private_key_id": secrets["private_key_id"],
        "private_key": secrets["private_key"],
        "client_email": secrets["client_email"],
        "client_id": secrets["client_id"],
        "auth_uri": secrets["auth_uri"],
        "token_uri": secrets["token_uri"],
        "auth_provider_x509_cert_url": secrets["auth_provider_x509_cert_url"],
        "client_x509_cert_url": secrets["client_x509_cert_url"]
    }, scopes=scope)
    client = gspread.authorize(creds)
else:
    st.error("Secrets not configured correctly.")

# --- DATABASE FUNCTIONS ---
def get_all_history():
    try:
        sh = client.open_by_url(MEMORY_SHEET_URL)
        ws = sh.get_worksheet(0)
        return pd.DataFrame(ws.get_all_records())
    except:
        return pd.DataFrame()

def load_session_messages(session_id):
    df = get_all_history()
    if df.empty: return []
    df['Session_ID'] = df['Session_ID'].astype(str)
    session_data = df[df['Session_ID'] == str(session_id)]
    messages = []
    for index, row in session_data.iterrows():
        messages.append({"role": row["Role"], "content": row["Content"]})
    return messages

def save_message(session_id, role, content):
    try:
        sh = client.open_by_url(MEMORY_SHEET_URL)
        ws = sh.get_worksheet(0)
        if ws.row_count > 0:
            val = ws.acell('A1').value
            if not val:
                 ws.append_row(["Session_ID", "Role", "Content", "Timestamp"])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([str(session_id), role, content, timestamp])
    except Exception as e:
        print(f"Save failed: {e}")

# --- HELPER FUNCTIONS ---

@st.cache_data(ttl=600)
def get_project_map():
    try:
        sh = client.open_by_url(MASTER_SHEET_URL)
        ws = sh.worksheet(LINKS_TAB_NAME)
        return ws.get_all_records()
    except Exception as e:
        return []

def read_target_sheet(url, sheet_title_hint="Sheet"):
    try:
        sh = client.open_by_url(url)
        all_content = []
        for ws in sh.worksheets():
            if ws.title in ["Instructions", "Admin"]: continue
            raw_data = ws.get_all_values()
            truncated_data = raw_data[:300] 
            tab_text = f"--- DATA FROM '{sheet_title_hint}' (Tab: {ws.title}) ---\n{str(truncated_data)}\n"
            all_content.append(tab_text)
        return "\n".join(all_content)
    except Exception as e:
        return f"Error reading {sheet_title_hint}: {e}"

def read_master_task_tabs():
    try:
        sh = client.open_by_url(MASTER_SHEET_URL)
        all_content = []
        ignore_list = [LINKS_TAB_NAME, LOGS_TAB_NAME, "Ref_Data", "Instructions"]
        for ws in sh.worksheets():
            if ws.title in ignore_list: continue
            raw_data = ws.get_all_values()
            truncated_data = raw_data[:100]
            tab_text = f"--- INTERNAL TASKS: '{ws.title}' ---\n{str(truncated_data)}\n"
            all_content.append(tab_text)
        return "\n".join(all_content)
    except Exception as e:
        return str(e)

def get_recent_context():
    if "messages" not in st.session_state: return ""
    history = st.session_state.messages[:-1][-3:]
    context_text = ""
    for msg in history:
        context_text += f"{msg['role'].upper()}: {msg['content']}\n"
    return context_text

def identify_project_in_prompt(prompt, project_map):
    """Finds if a project name exists in the user prompt."""
    prompt_lower = prompt.lower()
    if isinstance(project_map, list):
        # We no longer need to filter out 'Inventory' because it's hardcoded
        project_names = set(row['Project Name'] for row in project_map)
        
        # Sort by length descending to catch longer names first
        for name in sorted(project_names, key=len, reverse=True):
            if name.lower() in prompt_lower:
                return name
    return None

# --- APP STARTUP ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- SIDEBAR ---
with st.sidebar:
    st.title("🗂️ Menu")
    if st.button("➕ START NEW CHAT", type="primary"):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    st.divider()
    
    with st.spinner("Loading history..."):
        df_history = get_all_history()

    if not df_history.empty and 'Session_ID' in df_history.columns:
        unique_sessions = df_history[['Session_ID', 'Timestamp']].drop_duplicates(subset=['Session_ID']).sort_values(by='Timestamp', ascending=False)
        for index, row in unique_sessions.head(10).iterrows():
            sid = row['Session_ID']
            ts = row['Timestamp']
            if st.button(f"📅 {ts}", key=sid):
                st.session_state.session_id = sid
                st.session_state.messages = load_session_messages(sid)
                st.rerun()

# --- MAIN CHAT ---
st.title("🤖 Project Hub")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about projects, estimation, or tasks..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_message(st.session_state.session_id, "user", prompt)

    with st.spinner("Processing request..."):
        project_map = get_project_map()
        chat_context = get_recent_context()
        detected_project = identify_project_in_prompt(prompt, project_map)
        
        final_answer = ""
        
        # --- PATH A: PROJECT DETECTED (MULTI-SHEET MODE) ---
        if detected_project:
            status_text = f"Analying **{detected_project}** + **Stock Levels**..."
            st.toast(status_text)
            
            # 1. Gather Project Sheets
            target_urls = []
            for row in project_map:
                if row['Project Name'] == detected_project:
                    target_urls.append({"url": row['Raw Link'], "name": f"{detected_project} - {row['Category']}"})
            
            # 2. AUTOMATICALLY Add Hardcoded Stock Sheet
            if STOCK_SHEET_URL:
                target_urls.append({"url": STOCK_SHEET_URL, "name": "Global Inventory & Wood Stock"})

            # 3. Read Data
            mega_context = ""
            for target in target_urls:
                if target['url']:
                    data = read_target_sheet(target['url'], target['name'])
                    mega_context += f"\n\n=== FILE: {target['name']} ===\n{data}"
            
            # 4. Estimation Prompt
            final_prompt = f"""
            You are an expert Production Estimator.
            
            USER QUESTION: "{prompt}"
            CONTEXT: {chat_context}
            
            DATA SOURCES (Includes Project Sheets + Global Inventory):
            {mega_context}
            
            INSTRUCTIONS FOR ESTIMATION:
            1. Look at 'Manufacturing' / 'Room Schedule' to see how many items are COMPLETE vs TOTAL.
               - Calculate % Complete.
            2. Look at 'Project Overview' (in Inventory Sheet) to see wood USED SO FAR.
            3. ESTIMATE: If we used X wood to build Y%, how much wood is needed for the remaining (100-Y)%?
               - Show your math: (Used / % Complete) * % Remaining.
            4. Compare this requirement against 'Wood Stock' (Live Counts).
            5. Final Answer: "We need approx X more sheets. We have Y in stock. Result: Buy Z sheets."
            """
            
            try:
                final_answer = model.generate_content(final_prompt).text
            except Exception as e:
                final_answer = f"Error generating estimation: {e}"

        # --- PATH B: NO PROJECT DETECTED (STANDARD ROUTER) ---
        else:
            # We add Stock manually to the router options so you can still ask "Do we have Oak?"
            router_prompt = f"""
            You are a Routing Assistant. 
            CONTEXT: {chat_context}
            QUESTION: "{prompt}"
            
            OPTION 1: EXTERNAL PROJECT SHEETS
            {json.dumps(project_map)}
            
            OPTION 2: GLOBAL STOCK
            URL: {STOCK_SHEET_URL}
            Category: Stock
            
            OPTION 3: INTERNAL TASKS
            If asking about "Tasks", "Schedule", "People", return {{"url": "INTERNAL_TASKS", "reason": "Task request", "category": "Tasks"}}
            
            Return JSON in format: {{"url": "...", "reason": "...", "category": "..."}}
            """
            try:
                router_response = model.generate_content(router_prompt)
                clean_json = router_response.text.strip().replace("```json", "").replace("```", "")
                decision = json.loads(clean_json)
                target_url = decision.get("url")

                if target_url == "INTERNAL_TASKS":
                    sheet_data = read_master_task_tabs()
                    final_answer = model.generate_content(f"Answer using Tasks:\n{sheet_data}\nQuestion: {prompt}").text
                elif target_url and target_url != "None":
                    sheet_data = read_target_sheet(target_url, "Selected Sheet")
                    final_answer = model.generate_content(f"Answer using Data:\n{sheet_data}\nQuestion: {prompt}\nCite sources!").text
                else:
                    final_answer = "I couldn't find a relevant sheet. If asking about a job, use the exact Project Name."
            except Exception as e:
                final_answer = f"System Error: {e}"

        st.chat_message("assistant").markdown(final_answer)
        st.session_state.messages.append({"role": "assistant", "content": final_answer})
        save_message(st.session_state.session_id, "assistant", final_answer)
        st.rerun()
