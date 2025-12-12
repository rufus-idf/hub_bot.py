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

# 2. Your NEW Memory Sheet URL (The Database)
MEMORY_SHEET_URL = "https://docs.google.com/spreadsheets/d/1DDxAADCvTUcvKdeTb76giFBLIa3Yb1XOeGievJ_cung/edit"
LOGS_TAB_NAME = "CHAT_LOGS"
REF_DATA_TAB_NAME = "Ref_Data"

# 1. Page Config (Aggressive Sidebar Expansion)
st.set_page_config(page_title="Project Hub", layout="wide", initial_sidebar_state="expanded")

# --- CSS TO FORCE SIDEBAR VISIBILITY ---
st.markdown("""
    <style>
        [data-testid="stSidebar"] {
            min-width: 300px; /* Make it wider */
        }
        /* Highlight the New Chat Button */
        div.stButton > button {
            width: 100%;
            border-radius: 5px;
            font-weight: bold;
        }
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
    except Exception as e:
        # If headers are missing or sheet is empty, return empty DF
        return pd.DataFrame()

def load_session_messages(session_id):
    df = get_all_history()
    if df.empty: return []
    # Ensure Session_ID is treated as string for comparison
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
def get_project_map():
    try:
        sh = client.open_by_url(MASTER_SHEET_URL)
        ws = sh.worksheet(LINKS_TAB_NAME)
        return ws.get_all_records()
    except Exception as e:
        return f"Error: {e}"

def read_target_sheet(url):
    try:
        sh = client.open_by_url(url)
        all_content = []
        for ws in sh.worksheets():
            if ws.title in ["Instructions", "Admin"]: continue
            raw_data = ws.get_all_values()
            truncated_data = raw_data[:50]
            tab_text = f"--- DATA FROM TAB: '{ws.title}' ---\n{str(truncated_data)}\n"
            all_content.append(tab_text)
        return "\n".join(all_content), sh.title
    except Exception as e:
        return None, str(e)

def read_master_task_tabs():
    try:
        sh = client.open_by_url(MASTER_SHEET_URL)
        all_content = []
        ignore_list = [LINKS_TAB_NAME, LOGS_TAB_NAME, REF_DATA_TAB_NAME, "Instructions"]
        for ws in sh.worksheets():
            if ws.title in ignore_list: continue
            raw_data = ws.get_all_values()
            truncated_data = raw_data[:50]
            tab_text = f"--- INTERNAL TASK LIST: '{ws.title}' ---\n{str(truncated_data)}\n"
            all_content.append(tab_text)
        return "\n".join(all_content)
    except Exception as e:
        return str(e)

# --- APP STARTUP ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- SIDEBAR UI (THE CRITICAL PART) ---
with st.sidebar:
    st.title("🗂️ Menu")
    
    # 1. NEW CHAT BUTTON (Big and Red)
    if st.button("➕ START NEW CHAT", type="primary"):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    
    st.divider()
    st.subheader("Previous Chats")

    # 2. LOAD HISTORY
    with st.spinner("Loading history..."):
        df_history = get_all_history()

    if not df_history.empty and 'Session_ID' in df_history.columns:
        # Group by Session ID to get unique sessions
        unique_sessions = df_history[['Session_ID', 'Timestamp']].drop_duplicates(subset=['Session_ID'])
        # Sort by latest
        unique_sessions = unique_sessions.sort_values(by='Timestamp', ascending=False)
        
        # Limit to last 10 sessions to keep it clean
        for index, row in unique_sessions.head(10).iterrows():
            sid = row['Session_ID']
            ts = row['Timestamp']
            
            # Button for each session
            if st.button(f"📅 {ts}", key=sid):
                st.session_state.session_id = sid
                st.session_state.messages = load_session_messages(sid)
                st.rerun()
    else:
        st.info("No history found yet.")

# --- MAIN CHAT UI ---
st.title("🤖 Project Hub")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about projects, prices, or tasks..."):
    # Save & Show User Msg
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_message(st.session_state.session_id, "user", prompt)

    with st.spinner("Processing..."):
        # A. MAP
        project_map = get_project_map()
        
        # B. ROUTER
        router_prompt = f"""
        You are a Routing Assistant. 
        USER QUESTION: "{prompt}"
        
        OPTION 1: EXTERNAL SHEETS
        {json.dumps(project_map)}
        
        OPTION 2: INTERNAL TASKS
        If asking about "Tasks", "Schedule", "People", return {{"url": "INTERNAL_TASKS", "reason": "Task request", "category": "Tasks"}}
        
        Return JSON.
        """
        
        try:
            router_response = model.generate_content(router_prompt)
            clean_json = router_response.text.strip().replace("```json", "").replace("```", "")
            decision = json.loads(clean_json)
            
            target_url = decision.get("url")
            
            if target_url == "INTERNAL_TASKS":
                sheet_data = read_master_task_tabs()
                final_answer = model.generate_content(f"Answer using Internal Tasks:\n{sheet_data}\nQuestion: {prompt}").text

            elif target_url and target_url != "None":
                sheet_data, sheet_name = read_target_sheet(target_url)
                if sheet_data:
                    final_answer = model.generate_content(f"Answer using {sheet_name}:\n{sheet_data}\nQuestion: {prompt}").text
                else:
                    final_answer = f"Error opening sheet '{sheet_name}'."
            else:
                final_answer = "I couldn't find a relevant sheet."

        except Exception as e:
            final_answer = f"System Error: {e}"

        # Save & Show AI Msg
        st.chat_message("assistant").markdown(final_answer)
        st.session_state.messages.append({"role": "assistant", "content": final_answer})
        save_message(st.session_state.session_id, "assistant", final_answer)
        
        # RERUN to refresh the sidebar history immediately
        st.rerun()
