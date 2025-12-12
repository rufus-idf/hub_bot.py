import streamlit as st
import pandas as pd
import google.generativeai as genai
import gspread
import json
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
# 1. PASTE YOUR MASTER SCHEDULE URL HERE
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1azbcaaIgw7K_MGZJfYdaX4mTvsYBx48ApdQ0HM8mNdA/edit?gid=774364743#gid=774364743/edit"

# 2. NAME OF THE TAB WITH THE LINKS
LINKS_TAB_NAME = "AI_LINKS" 

# 1. Page Config (Clean Interface for Embedding)
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

# 3. Setup GSpread (The engine to open sheets)
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

# --- FUNCTION 1: GET THE MAP (Read Master Sheet) ---
def get_project_map():
    try:
        sh = client.open_by_url(MASTER_SHEET_URL)
        ws = sh.worksheet(LINKS_TAB_NAME)
        # Get all records (Dictionary format)
        data = ws.get_all_records()
        return data
    except Exception as e:
        return f"Error reading Master Sheet: {e}"

# --- FUNCTION 2: READ THE TARGET (Read Linked Sheet) ---
def read_target_sheet(url):
    try:
        sh = client.open_by_url(url)
        # Just read the first worksheet of the target
        ws = sh.get_worksheet(0)
        # Limit to top 100 rows to save speed/tokens
        raw_data = ws.get_all_values()
        return raw_data[:100], sh.title
    except Exception as e:
        return None, str(e)

# --- SIDEBAR DEBUGGER ---
with st.sidebar:
    st.header("🕵️‍♂️ Debug Tools")
    st.info("Use this to check if the bot sees your 'AI_LINKS' tab.")
    
    if st.button("1. Check Master Map"):
        with st.spinner("Reading Master Sheet..."):
            map_data = get_project_map()
            st.write(map_data) # Shows the raw data

# --- CHAT INTERFACE ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about a project (e.g. 'Is Project A finished?')..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.spinner("🤖 Routing your request..."):
        
        # STEP A: GET THE MAP
        project_map = get_project_map()
        
        if isinstance(project_map, str) and "Error" in project_map:
            st.error(project_map)
            st.stop()

        # STEP B: DECIDE WHICH SHEET TO OPEN
        # We send the map to Gemini and ask it to pick the right URL
        router_prompt = f"""
        You are a Routing Assistant. 
        USER QUESTION: "{prompt}"
        
        Below is the map of available sheets. 
        Based on the 'Content Description' and 'Project Name', pick the single best URL.
        
        MAP:
        {json.dumps(project_map)}
        
        INSTRUCTIONS:
        - Return ONLY JSON. Format: {{"url": "THE_URL", "reason": "Why you picked it", "category": "The Category Name"}}
        - If no sheet matches, return {{"url": "None", "reason": "No match"}}
        """
        
        try:
            router_response = model.generate_content(router_prompt)
            # Clean the response to ensure valid JSON
            decision_text = router_response.text.strip().replace("```json", "").replace("```", "")
            decision = json.loads(decision_text)
            
            # DEBUG: Show the decision in the chat (hidden inside an expander)
            with st.expander("See Routing Decision"):
                st.write(f"**Selected Category:** {decision.get('category')}")
                st.write(f"**Reason:** {decision.get('reason')}")
                st.write(f"**Target URL:** {decision.get('url')}")

            target_url = decision.get("url")
            
            if target_url and target_url != "None":
                # STEP C: OPEN THE TARGET SHEET
                sheet_data, sheet_name = read_target_sheet(target_url)
                
                if sheet_data:
                    # STEP D: ANSWER QUESTION
                    final_prompt = f"""
                    You are an Expert Project Assistant.
                    USER QUESTION: "{prompt}"
                    
                    DATA FROM SHEET '{sheet_name}':
                    {sheet_data}
                    
                    Answer the question using ONLY this data.
                    """
                    final_answer = model.generate_content(final_prompt).text
                else:
                    final_answer = f"I tried to open the sheet '{sheet_name}' but failed. (Error: {sheet_data})"
            else:
                final_answer = "I couldn't find a relevant sheet in your Master Schedule to answer that."

        except Exception as e:
            final_answer = f"System Error: {e}"

        st.chat_message("assistant").markdown(final_answer)
        st.session_state.messages.append({"role": "assistant", "content": final_answer})
