import streamlit as st
import pandas as pd
import google.generativeai as genai
import gspread
import json
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

# 1. Page Config
st.set_page_config(page_title="Hub Agent", layout="wide")
st.markdown("""
    <style>
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .stApp {background-color: transparent;}
        .block-container {padding-top: 0rem; padding-bottom: 0rem;}
        /* Make sidebar buttons look like chat history items */
        .stButton button {
            width: 100%;
            text-align: left;
            border: none;
            background: transparent;
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
    """Reads entire sheet to find unique sessions."""
    try:
        sh = client.open_by_url(MEMORY_SHEET_URL)
        ws = sh.get_worksheet(0)
        return pd.DataFrame(ws.get_all_records())
    except:
        return pd.DataFrame()

def load_session_messages(session_id):
    """Loads specific messages for one session ID."""
    df = get_all_history()
    if df.empty: return []
    # Filter by Session ID
    session_data = df[df['Session_ID'] == str(session_id)]
    messages = []
    for index, row in session_data.iterrows():
        messages.append({"role": row["Role"], "content": row["Content"]})
    return messages

def save_message(session_id, role, content):
    """Saves message with the specific Session ID."""
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
        st.error(f"Save failed: {e}")

# --- HELPER FUNCTIONS (Routing & Reading) ---
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

# --- APP LOGIC ---

# 1. Initialize Session ID
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4()) # Generate random ID for new user

# 2. Initialize Messages for that ID
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- SIDEBAR: HISTORY LIST ---
with st.sidebar:
    st.title("💬 Chats")
    
    # NEW CHAT BUTTON
    if st.button("➕ Start New Chat", type="primary"):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.caption("History")

    # Load all history to find past sessions
    df_history = get_all_history()
    if not df_history.empty and 'Session_ID' in df_history.columns:
        # Get unique sessions (reverse order to show newest first)
        unique_sessions = df_history[['Session_ID', 'Timestamp']].drop_duplicates(subset=['Session_ID']).sort_values(by='Timestamp', ascending=False)
        
        for index, row in unique_sessions.iterrows():
            sid = row['Session_ID']
            time_label = row['Timestamp']
            
            # Create a button for each past session
            # Use the timestamp as the label (or first few words of first message if we wanted to be fancy)
            if st.button(f"📅 {time_label}", key=sid):
                st.session_state.session_id = sid
                st.session_state.messages = load_session_messages(sid)
                st.rerun()

# --- MAIN CHAT INTERFACE ---

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about projects or tasks..."):
    # 1. Update UI & Save User Msg
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_message(st.session_state.session_id, "user", prompt)

    with st.spinner("Thinking..."):
        # A. MAP
        project_map = get_project_map()
        
        # B. ROUTER
        router_prompt = f"""
        You are a Routing Assistant. 
        USER QUESTION: "{prompt}"
        
        OPTION 1: EXTERNAL PROJECT SHEETS (Map below)
        {json.dumps(project_map)}
        
        OPTION 2: INTERNAL TASK LIST
        If asking about "Tasks", "To-Dos", "Schedule", or "What a specific person has to do", 
        return {{"url": "INTERNAL_TASKS", "reason": "Internal tasks", "category": "Tasks"}}.
        
        INSTRUCTIONS:
        - Return ONLY JSON. 
        - If Option 1: {{"url": "THE_URL", "reason": "...", "category": "..."}}
        - If Option 2: {{"url": "INTERNAL_TASKS", "reason": "...", "category": "Tasks"}}
        - If No Match: {{"url": "None", "reason": "No match"}}
        """
        
        try:
            router_response = model.generate_content(router_prompt)
            decision = json.loads(router_response.text.strip().replace("```json", "").replace("```", ""))
            
            target_url = decision.get("url")
            
            if target_url == "INTERNAL_TASKS":
                sheet_data = read_master_task_tabs()
                final_answer = model.generate_content(f"Answer using Internal Tasks:\n{sheet_data}\nQuestion: {prompt}").text

            elif target_url and target_url != "None":
                sheet_data, sheet_name = read_target_sheet(target_url)
                if sheet_data:
                    final_answer = model.generate_content(f"Answer using data from {sheet_name}:\n{sheet_data}\nQuestion: {prompt}").text
                else:
                    final_answer = f"Error opening sheet '{sheet_name}'."
            else:
                final_answer = "I couldn't find a relevant sheet or task list."

        except Exception as e:
            final_answer = f"System Error: {e}"

        # 2. Update UI & Save AI Msg
        st.chat_message("assistant").markdown(final_answer)
        st.session_state.messages.append({"role": "assistant", "content": final_answer})
        save_message(st.session_state.session_id, "assistant", final_answer)
        
        # Rerun to update the sidebar history list immediately
        st.rerun()
