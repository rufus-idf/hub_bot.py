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
def load_memory_from_sheet():
    try:
        sh = client.open_by_url(MEMORY_SHEET_URL)
        ws = sh.get_worksheet(0)
        records = ws.get_all_records()
        messages = []
        for r in records:
            messages.append({"role": r["Role"], "content": r["Content"]})
        return messages
    except:
        return []

def save_message_to_sheet(role, content):
    try:
        sh = client.open_by_url(MEMORY_SHEET_URL)
        ws = sh.get_worksheet(0)
        if ws.row_count > 0:
            val = ws.acell('A1').value
            if not val:
                 ws.append_row(["Role", "Content", "Timestamp"])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([role, content, timestamp])
    except Exception as e:
        st.error(f"Failed to save memory: {e}")

def clear_memory_sheet():
    try:
        sh = client.open_by_url(MEMORY_SHEET_URL)
        ws = sh.get_worksheet(0)
        ws.clear()
        ws.append_row(["Role", "Content", "Timestamp"])
        return True
    except Exception as e:
        st.error(f"Failed to clear memory: {e}")
        return False

# --- HELPER: READ MAP ---
def get_project_map():
    try:
        sh = client.open_by_url(MASTER_SHEET_URL)
        ws = sh.worksheet(LINKS_TAB_NAME)
        return ws.get_all_records()
    except Exception as e:
        return f"Error reading Master Sheet: {e}"

# --- HELPER: READ EXTERNAL TARGET ---
def read_target_sheet(url):
    """Opens an external sheet and reads ALL tabs."""
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

# --- HELPER: READ INTERNAL TASKS (NEW) ---
def read_master_task_tabs():
    """
    Opens the MASTER sheet, but skips the Admin/Link/Log tabs.
    Only reads the tabs that contain Tasks/People.
    """
    try:
        sh = client.open_by_url(MASTER_SHEET_URL)
        all_content = []
        
        # Tabs to IGNORE (System tabs)
        ignore_list = [LINKS_TAB_NAME, LOGS_TAB_NAME, REF_DATA_TAB_NAME, "Instructions"]
        
        for ws in sh.worksheets():
            if ws.title in ignore_list:
                continue # Skip the system tabs
                
            raw_data = ws.get_all_values()
            truncated_data = raw_data[:50]
            tab_text = f"--- INTERNAL TASK LIST: '{ws.title}' ---\n{str(truncated_data)}\n"
            all_content.append(tab_text)
            
        return "\n".join(all_content)
    except Exception as e:
        return str(e)

# --- INIT SESSION STATE ---
if "messages" not in st.session_state:
    st.session_state.messages = load_memory_from_sheet()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Memory Controls")
    if st.button("🗑️ Clear Conversation History"):
        if clear_memory_sheet():
            st.session_state.messages = []
            st.success("History deleted!")
            st.rerun()

# --- CHAT INTERFACE ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about projects or tasks..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_message_to_sheet("user", prompt)

    with st.spinner("Analyzing request..."):
        
        # A. GET MAP
        project_map = get_project_map()
        if isinstance(project_map, str) and "Error" in project_map:
            st.error(project_map)
            st.stop()

        # B. ROUTING (UPDATED LOGIC)
        # We teach the Router about the "INTERNAL_TASKS" option.
        router_prompt = f"""
        You are a Routing Assistant. 
        USER QUESTION: "{prompt}"
        
        OPTION 1: EXTERNAL PROJECT SHEETS (Use the Map below)
        {json.dumps(project_map)}
        
        OPTION 2: INTERNAL TASK LIST
        If the user asks about "Tasks", "To-Dos", "Schedule", or "What a specific person has to do", 
        return {{"url": "INTERNAL_TASKS", "reason": "User asked for internal tasks", "category": "Tasks"}}.
        
        INSTRUCTIONS:
        - Return ONLY JSON. 
        - If matching Option 1, return {{"url": "THE_URL", "reason": "...", "category": "..."}}
        - If matching Option 2, return {{"url": "INTERNAL_TASKS", "reason": "...", "category": "Tasks"}}
        - If no match, return {{"url": "None", "reason": "No match"}}
        """
        
        try:
            router_response = model.generate_content(router_prompt)
            decision_text = router_response.text.strip().replace("```json", "").replace("```", "")
            decision = json.loads(decision_text)
            
            with st.expander(f"Routing: {decision.get('category')}"):
                st.caption(f"Reason: {decision.get('reason')}")

            target_url = decision.get("url")
            
            if target_url == "INTERNAL_TASKS":
                # --- BRANCH: READ MASTER SHEET TASKS ---
                sheet_data = read_master_task_tabs()
                sheet_name = "Master Internal Tasks"
                
                final_prompt = f"""
                Assistant.
                QUESTION: "{prompt}"
                
                DATA (From Internal Task Tabs):
                {sheet_data}
                
                Answer based on the tasks listed above.
                """
                final_answer = model.generate_content(final_prompt).text

            elif target_url and target_url != "None":
                # --- BRANCH: READ EXTERNAL LINK ---
                sheet_data, sheet_name = read_target_sheet(target_url)
                
                if sheet_data:
                    final_prompt = f"""
                    Assistant. 
                    QUESTION: "{prompt}"
                    DATA (From Linked Sheet '{sheet_name}'): 
                    {sheet_data}
                    
                    Answer based on data.
                    """
                    final_answer = model.generate_content(final_prompt).text
                else:
                    final_answer = f"Error opening sheet '{sheet_name}'. Check permissions."
            else:
                final_answer = "I couldn't find a relevant sheet or task list."

        except Exception as e:
            final_answer = f"System Error: {e}"

        st.chat_message("assistant").markdown(final_answer)
        st.session_state.messages.append({"role": "assistant", "content": final_answer})
        save_message_to_sheet("assistant", final_answer)
