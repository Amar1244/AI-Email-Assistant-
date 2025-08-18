import base64
import streamlit as st
import smtplib
from email.message import EmailMessage
import requests
import os
import json
import pandas as pd
from dotenv import load_dotenv
import warnings
from datetime import datetime
import re
from io import BytesIO
from pymongo import MongoClient

# Suppress warnings
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
warnings.filterwarnings("ignore")

# Load environment variables
load_dotenv()

# ------------------ Config & Helper Functions ------------------
USERNAME_FILE = "username.txt"
EMAIL_CONFIG_FILE = "email_config.txt"
HISTORY_FILE = "email_history.json"
API_BASE_URL = "http://localhost:8000"  # Update with your FastAPI server URL

# ------------------ Core Functions ------------------
def generate_email_groq(recipient_name, prompt, sender_name):
    """Generate email content with robust subject/body parsing"""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: 
        raise ValueError("GROQ_API_KEY not set.")
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}", 
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama3-70b-8192",
        "messages": [
            {
                "role": "system", 
                "content": f"""You are a professional email assistant. Always format replies as:
                
Subject: [Clear subject line]

[Email body content here]

Best regards,
{sender_name}"""
            },
            {
                "role": "user", 
                "content": f"Write a professional email to {recipient_name} about: {prompt}"
            }
        ],
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        
        subject = "No Subject"
        if "Subject:" in content:
            subject_line = content.split("Subject:", 1)[1]
            subject = subject_line.split("\n")[0].strip()
        else:
            for line in content.split("\n"):
                if line.strip():
                    subject = line.strip()[:100]
                    break
        
        body = content
        if "\n\n" in content:
            body = content.split("\n\n", 1)[1].strip()
        elif "\n" in content:
            body = content.split("\n", 1)[1].strip()
            
        return subject, body
        
    except Exception as e:
        st.error(f"⚠️ Email generation failed: {str(e)}")
        return "Error", f"Could not generate email: {str(e)}"

def save_username(name):
    with open(USERNAME_FILE, "w") as f:
        f.write(name)

def load_username():
    if os.path.exists(USERNAME_FILE):
        with open(USERNAME_FILE, "r"):
            pass
    return open(USERNAME_FILE).read().strip() if os.path.exists(USERNAME_FILE) else ""

def save_email_config(email, password):
    encoded = base64.b64encode(f"{email}:{password}".encode()).decode()
    with open(EMAIL_CONFIG_FILE, "w") as f:
        f.write(encoded)

def load_email_config():
    if os.path.exists(EMAIL_CONFIG_FILE):
        decoded = base64.b64decode(open(EMAIL_CONFIG_FILE).read().strip()).decode()
        return decoded.split(":")
    return ("", "")

def load_email_history():
    if os.path.exists(HISTORY_FILE):
        return json.load(open(HISTORY_FILE))
    return {}

def save_email_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def call_api(endpoint, method="GET", data=None, files=None, params=None):
    try:
        url = f"{API_BASE_URL}{endpoint}"
        if method == "GET":
            # IMPORTANT: GET must use query/path parameters, not JSON body
            response = requests.get(url, params=params)
        elif files is not None:
            # Multipart for file uploads
            response = requests.post(url, data=data, files=files)
        else:
            response = requests.post(url, json=data)
        response.raise_for_status()
        # Some endpoints might return non-JSON (rare); safe-guard:
        try:
            return response.json()
        except Exception:
            return {"raw": response.text}
    except Exception as e:
        st.error(f"API Error: {str(e)}")
        return None

def log_email(user_id, recipient, subject, body):
    history = load_email_history()
    if user_id not in history:
        history[user_id] = []
    history[user_id].append({
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "timestamp": datetime.now().isoformat()
    })
    save_email_history(history)

def extract_subject_and_body(text: str, fallback_subject: str = "Generated Email"):
    """
    Accepts any string returned by /generate-email. 
    If it includes a 'Subject:' line, extract it; else synthesize from first line or fallback.
    Cleans escaped sequences and stray quotes.
    """
    if not isinstance(text, str):
        text = str(text)
    # Unescape common artifacts
    text = text.replace("\\n", "\n").replace('\\"', '"').strip().strip("'").strip('"')

    # If backend returns dict-like string, try to parse minimally
    if text.startswith("{") and text.endswith("}"):
        try:
            # very cautious eval—still keep fallback
            parsed = eval(text, {"__builtins__": {}})
            if isinstance(parsed, dict) and "email" in parsed:
                text = parsed["email"]
        except Exception:
            pass

    # Try to find an explicit Subject line
    m = re.search(r"^\s*Subject\s*:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    if m:
        subject = m.group(1).strip()
        # remove that line from body
        body = re.sub(r"^\s*Subject\s*:\s*.+\n?", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
        return subject if subject else fallback_subject, body

    # Otherwise synthesize subject from the first non-empty line or fallback
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    subject = lines[0][:120] if lines else fallback_subject
    body = "\n".join(lines[1:]).strip() if len(lines) > 1 else text
    return subject, body

# ------------------ UI Components ------------------
def sidebar():
    st.sidebar.title("⚙️ Settings")
    
    # Mode selection at the very top
    mode = st.sidebar.radio("Select Mode", ["Simple Email", "Database Mode"], horizontal=True)
    
    # Your Info Section
    st.sidebar.subheader("👤 Your Info")
    
    # Load saved info
    saved_name = load_username()
    saved_email, saved_password = load_email_config()
    
    # Show current info if saved, otherwise show input fields
    if saved_name and saved_email and saved_password:
        # Display saved info
        st.sidebar.write(f"**Name:** {saved_name}")
        st.sidebar.write(f"**Email:** {saved_email}")
        st.sidebar.write("**Password:** ••••••••")
        
        # Option to change
        if st.sidebar.button("✏️ Change Info", key="change_info_btn"):
            st.session_state.show_edit_form = True
        
        # Show edit form if requested
        if st.session_state.get("show_edit_form", False):
            st.sidebar.markdown("---")
            st.sidebar.subheader("✏️ Edit Your Info")
            
            new_name = st.sidebar.text_input("Your Name", value=saved_name, key="edit_name")
            new_email = st.sidebar.text_input("Your Email", value=saved_email, key="edit_email")
            new_password = st.sidebar.text_input("Your Password", type="password", key="edit_password")
            
            col1, col2 = st.sidebar.columns(2)
            with col1:
                if st.button("💾 Save Changes", key="save_changes"):
                    if new_name and new_email and new_password:
                        save_username(new_name)
                        save_email_config(new_email, new_password)
                        st.session_state.show_edit_form = False
                        st.sidebar.success("✅ Info updated successfully!")
                        st.rerun()
                    else:
                        st.sidebar.warning("Please fill all fields")
            
            with col2:
                if st.button("❌ Cancel", key="cancel_edit"):
                    st.session_state.show_edit_form = False
                    st.rerun()
    else:
        # Show input form for first time setup
        st.sidebar.info("Please enter your information to get started")
        
        name = st.sidebar.text_input("Your Name", key="setup_name")
        email = st.sidebar.text_input("Your Email", key="setup_email")
        password = st.sidebar.text_input("Your Password", type="password", key="setup_password")
        
        if st.sidebar.button("💾 Save Info", key="save_info"):
            if name and email and password:
                save_username(name)
                save_email_config(email, password)
                st.sidebar.success("✅ Info saved successfully!")
                st.rerun()
            else:
                st.sidebar.warning("Please fill all fields")
    
    # Email History with dropdown
    st.sidebar.markdown("---")
    st.sidebar.write("📜 **Email History**")
    
    history = load_email_history()
    if saved_name and saved_name in history and history[saved_name]:
        # Create dropdown for email history
        email_titles = [f"📧 {email_data.get('subject', 'No Subject')[:25]}..." for email_data in history[saved_name]]
        selected_email = st.sidebar.selectbox("Select email to view:", ["Choose an email..."] + email_titles, key="email_history_dropdown")
        
        if selected_email != "Choose an email...":
            # Find the selected email data
            email_index = email_titles.index(selected_email)
            email_data = history[saved_name][email_index]
            
            # Display email details below dropdown
            st.sidebar.markdown("---")
            st.sidebar.write(f"**Subject:** {email_data.get('subject', 'No Subject')}")
            st.sidebar.write(f"**To:** {email_data.get('recipient', 'Unknown')}")
            st.sidebar.write(f"**Sent:** {email_data.get('timestamp', 'Unknown time')}")
            
            if st.sidebar.button("📖 View Full Email", key=f"view_full_{email_index}"):
                st.session_state.viewing_email = email_data
    else:
        st.sidebar.info("No email history yet")

    # Return the current values (either saved or from form)
    current_name = saved_name if saved_name else st.session_state.get("setup_name", "")
    current_email = saved_email if saved_email else st.session_state.get("setup_email", "")
    current_password = saved_password if saved_password else st.session_state.get("setup_password", "")
    
    return current_name, current_email, current_password, mode

def simple_mail_ui(name, email, password):
    """Simple email composition mode with title-only input"""
    st.subheader("✉️ Simple Mail Mode")

    col1, col2 = st.columns(2)
    with col1:
        recipient_name = st.text_input("Recipient Name", key="simple_recipient_name")
    with col2:
        recipient_email = st.text_input("Recipient Email", key="simple_recipient_email")

    title = st.text_input("Email Title (e.g., 'Interview Invite')", key="simple_title")
    tone = st.selectbox("Tone", ["professional", "friendly", "formal"], key="simple_tone")

    if st.button("🤖 Generate Email", key="simple_generate"):
        if not name:
            st.warning("Please set your name in the sidebar")
            return
        if not recipient_name or not title:
            st.warning("Please enter recipient name and title")
            return

        with st.spinner("Generating subject & body..."):
            # Ask backend to create a full email with a visible Subject line
            context = f"Title: {title}\nPlease generate a professional email. Start with a line 'Subject: ...' then the body."
            resp = call_api(
                "/generate-email",
                method="POST",
                data={
                    "contact_name": recipient_name,
                    "company_name": "",
                    "context": context,
                    "tone": tone
                }
            )
            if not resp:
                st.error("Failed to generate email")
                return

            # /generate-email returns {"email": "..."} in your backend
            raw = resp.get("email", resp)
            subject, body = extract_subject_and_body(raw, fallback_subject=title)
            # Personalize signature
            body = body.replace("[Your Name]", name)

            st.session_state.subject = subject
            st.session_state.body = body
            st.success("Email generated!")

    if st.session_state.get("subject"):
        st.subheader("📧 Email Preview")
        st.session_state.subject = st.text_input("Subject", value=st.session_state.subject, key="simple_subject_edit")
        email_body = st.text_area("Body", value=st.session_state.body, height=300, key="simple_body_display")

        if st.button("📨 Send Email", key="simple_send"):
            if not all([email, password]):
                st.error("Please configure your email in the sidebar")
                return
            try:
                msg = EmailMessage()
                msg['From'] = f"{name} <{email}>"
                msg['To'] = recipient_email
                msg['Subject'] = st.session_state.subject
                msg.set_content(email_body)

                with st.spinner("Sending..."):
                    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                        smtp.login(email, password)
                        smtp.send_message(msg)

                log_email(name, recipient_email, st.session_state.subject, email_body)
                st.success("✅ Email sent successfully!")
            except Exception as e:
                st.error(f"❌ Failed to send: {str(e)}")

def database_fetch_ui(name, email, password):
    """
    Database mode with proper flow: Data Source → View/Download/Reset → Search → Email Options
    """
    st.subheader("📂 Database Mode")
    
    # ---------------- Step 1: Data Source Selection ----------------
    st.subheader("🔗 Step 1: Choose Your Data Source")
    
    data_source = st.radio("Select Data Source:", ["MongoDB", "Upload Data"], horizontal=True, key="main_data_source")
    
    if data_source == "MongoDB":
        st.subheader("🗄️ MongoDB Connection")
        mongo_url = st.text_input("Connection String", placeholder="mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority", key="mongo_url_main")
        db_name = st.text_input("Database Name", placeholder="Emailuserdata", key="db_name_main")
        collection_name = st.text_input("Collection Name", placeholder="Contacts", key="collection_name_main")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔗 Connect to MongoDB", key="connect_mongo_main", type="primary"):
                if not name.strip():
                    st.warning("Set your Name in the sidebar first")
                elif not mongo_url or not db_name or not collection_name:
                    st.warning("Please fill all MongoDB connection fields")
                else:
                    try:
                        from pymongo import MongoClient
                        # Test connection and load data
                        client = MongoClient(mongo_url)
                        db = client[db_name]
                        collection = db[collection_name]
                        
                        # Get data count
                        data_count = collection.count_documents({})
                        
                        if data_count > 0:
                            # Load data
                            collection_data = list(collection.find({}, {"_id": 0}))
                            st.session_state.mongo_users = collection_data
                            st.session_state.mongo_connected = True
                            
                            # Store connection in session state
                            if "mongo_connections" not in st.session_state:
                                st.session_state.mongo_connections = {}
                            st.session_state.mongo_connections[name] = {
                                "mongo_url": mongo_url,
                                "db_name": db_name,
                                "collection_name": collection_name
                            }
                            
                            st.success(f"✅ Successfully Connected! Loaded {len(collection_data)} records from {collection_name}")
                            client.close()
                        else:
                            st.warning(f"Collection '{collection_name}' exists but is empty")
                            client.close()
                            
                    except Exception as e:
                        st.error(f"❌ Connection failed: {str(e)}")
        
        with col2:
            if st.button("🗑️ Reset MongoDB Connection", key="reset_mongo_main", type="secondary"):
                st.session_state.mongo_users = None
                st.session_state.mongo_connected = False
                if "mongo_connections" in st.session_state and name in st.session_state.mongo_connections:
                    del st.session_state.mongo_connections[name]
                st.success("✅ MongoDB connection reset successfully!")
    
    elif data_source == "Upload Data":
        st.subheader("📤 Upload Data")
        uploaded_file = st.file_uploader("Choose CSV or Excel file", type=["csv", "xls", "xlsx"], key="file_uploader_main")
        
        if uploaded_file:
            if not name:
                st.warning("Set your Name in the sidebar first (used as user_id)")
            else:
                # Prepare proper multipart
                file_bytes = uploaded_file.getvalue()
                files = {
                    "file": (uploaded_file.name, file_bytes, "application/octet-stream")
                }
                data = {"user_id": name}
                with st.spinner("Uploading contacts..."):
                    resp = call_api("/upload-contacts", method="POST", files=files, data=data)
                if resp and resp.get("status") in ("success", "warning"):
                    st.success(f"✅ Successfully Uploaded! {resp.get('contact_count', 0)} contacts saved.")
                    # Pull/refresh contacts into session from backend
                    refres = call_api(f"/get-contacts/{name}", method="GET")
                    if refres and refres.get("status") == "success":
                        st.session_state.uploaded_contacts = refres.get("contacts", [])
                        st.success(f"✅ Successfully loaded {len(st.session_state.uploaded_contacts)} contacts from your upload!")
                    else:
                        st.info("Uploaded successfully, but could not immediately fetch contacts.")
                else:
                    st.error(resp.get("message", "Upload failed") if resp else "Upload request failed")
    
    # ---------------- Step 2: Data Actions (View/Download/Reset) ----------------
    if st.session_state.get("mongo_users") or st.session_state.get("uploaded_contacts"):
        st.markdown("---")
        st.subheader("📊 Step 2: Data Actions")
        
        # Determine which data to show
        if st.session_state.get("mongo_users"):
            current_data = st.session_state.mongo_users
            data_source_name = "MongoDB"
        else:
            current_data = st.session_state.uploaded_contacts
            data_source_name = "Uploaded Data"
        
        col1_actions, col2_actions, col3_actions = st.columns(3)
        
        with col1_actions:
            if st.button("👁️ View Data", key="view_data"):
                st.dataframe(pd.DataFrame(current_data), use_container_width=True, height=400)
                st.info(f"📈 Total {data_source_name} records: {len(current_data)}")
        
        with col2_actions:
            if st.button("📥 Download Data", key="download_data"):
                df = pd.DataFrame(current_data)
                csv = df.to_csv(index=False)
                st.download_button(
                    label="📥 Download as CSV",
                    data=csv,
                    file_name=f"{data_source_name.lower()}_data_{name}.csv",
                    mime="text/csv"
                )
        
        with col3_actions:
            if st.button("🗑️ Reset Data", key="reset_data"):
                if data_source_name == "MongoDB":
                    st.session_state.mongo_users = None
                    st.session_state.mongo_connected = False
                else:
                    st.session_state.uploaded_contacts = None
                st.success(f"✅ {data_source_name} data cleared!")
    
    # ---------------- Step 3: Natural Language Search ----------------
    if st.session_state.get("mongo_users") or st.session_state.get("uploaded_contacts"):
        st.markdown("---")
        st.subheader("🔍 Step 3: Natural Language Search")
        
        # Get current data for search
        if st.session_state.get("mongo_users"):
            search_data = st.session_state.mongo_users
        else:
            search_data = st.session_state.uploaded_contacts
        
        search_query = st.text_input("Enter your search query", placeholder="e.g., 'Find contacts from tech companies in Mumbai'", key="search_query_main")
        
        if st.button("🔍 Search Contacts", key="search_button_main"):
            if not search_query:
                st.warning("Please enter a search query first")
            elif not name:
                st.warning("Please set your name in the sidebar first")
            else:
                with st.spinner("Searching contacts..."):
                    try:
                        # Use nlp_engine for natural language search
                        from nlp_engine import NaturalEmailAssistant
                        nlp = NaturalEmailAssistant()
                        
                        # Perform search using nlp_engine
                        search_results = nlp.enhanced_search(search_data, search_query, top_k=10)
                        
                        if search_results:
                            st.session_state.current_search_results = search_results
                            st.success(f"✅ Found {len(search_results)} relevant contacts!")
                            
                            # Display search results in dataframe
                            st.subheader("📋 Search Results")
                            df_results = pd.DataFrame(search_results)
                            st.dataframe(df_results, use_container_width=True, height=400)
                            
                            # Action buttons for search results
                            col1_search, col2_search, col3_search = st.columns(3)
                            
                            with col1_search:
                                if st.button("📥 Download Search Results", key="download_search_results"):
                                    csv = df_results.to_csv(index=False)
                                    st.download_button(
                                        label="📥 Download as CSV",
                                        data=csv,
                                        file_name=f"search_results_{name}.csv",
                                        mime="text/csv"
                                    )
                            
                            with col2_search:
                                if st.button("✅ Use Results for Emails", key="use_search_results"):
                                    st.session_state.current_search_results = search_results
                                    st.success(f"✅ {len(search_results)} search results ready for email sending!")
                            
                            with col3_search:
                                if st.button("🗑️ Clear Search Results", key="clear_search_results"):
                                    st.info("Search results cleared. Perform a new search to see results.")
                        else:
                            st.warning("No contacts found matching your search query.")
                            
                    except Exception as e:
                        st.error(f"Search failed: {str(e)}")
    
    # ---------------- Step 4: Email Sending Options (Only after search results) ----------------
    if st.session_state.get("current_search_results"):
        st.markdown("---")
        st.subheader("✉️ Step 4: Email Sending Options")
        
        st.info(f"📊 **Active Data:** {len(st.session_state.current_search_results)} search results available for email sending")
        
        email_mode = st.radio(
            "Choose sending mode:",
            ["Send Individual", "Send Same to All", "Send Data to Personal Email"],
            horizontal=True,
            key="search_email_mode"
        )
        
        results = st.session_state.current_search_results
        
        # A) Send Individual
        if email_mode == "Send Individual":
            # Build choices for search results
            options = []
            for u in results:
                nm = u.get("name", "")
                em = u.get("email", "")
                options.append(f"{nm} ({em})" if em else nm or "(Unnamed)")

            choice = st.selectbox("Select Contact", options=options, key="search_individual_select")
            # Map selection back to record
            idx = options.index(choice) if choice in options else 0
            recipient = results[idx]

            title = st.text_input("Email Title (e.g., 'Interview Invite')", key="search_indiv_title")
            tone = st.selectbox("Tone", ["professional", "friendly", "formal"], key="search_indiv_tone")

            # Step 1: Generate Email
            if st.button("📝 Generate Email", key="search_indiv_generate", use_container_width=True):
                if not title:
                    st.warning("Please enter an email title first")
                else:
                    emaddr = recipient.get("email", "")
                    if not emaddr:
                        st.warning("Selected contact has no email")
                    else:
                        # Use local email generation instead of API call
                        context = f"Title: {title}\nPlease generate a professional email. Start with 'Subject:' on the first line, then body."
                        with st.spinner("Generating email..."):
                            try:
                                # Generate email locally using the working function
                                subject, body = generate_email_groq(recipient.get("name", ""), context, name)
                                
                                # Store generated email in session state
                                st.session_state.generated_individual_email = f"Subject: {subject}\n\n{body}"
                                st.session_state.individual_recipient = recipient
                                st.session_state.individual_title = title
                                st.success("✅ Email generated successfully!")
                            except Exception as e:
                                st.error(f"Error during email generation: {str(e)}")
                                st.write("Full error details:", e)

            # Step 2: Review and Send (only show if email was generated)
            if st.session_state.get("generated_individual_email"):
                st.markdown("---")
                st.subheader("📧 Review Generated Email")
                
                # Extract subject and body
                gen_email = st.session_state.generated_individual_email
                subject, body = extract_subject_and_body(gen_email, fallback_subject=st.session_state.get("individual_title", ""))
                
                # Show subject and body for review (editable)
                edited_subject = st.text_input("Subject", value=subject, key="review_indiv_subject")
                edited_body = st.text_area("Email Body", value=body, height=200, key="review_indiv_body")
                
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    # Send button
                    if st.button("📨 Send Email", key="search_indiv_send", type="primary", use_container_width=True):
                        recipient = st.session_state.get("individual_recipient", {})
                        emaddr = recipient.get("email", "")
                        if not emaddr:
                            st.warning("Selected contact has no email")
                        else:
                            # Send email locally using SMTP (use edited fields)
                            try:
                                msg = EmailMessage()
                                msg['From'] = email
                                msg['To'] = emaddr
                                msg['Subject'] = edited_subject
                                msg.set_content(edited_body)
                                
                                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                                    smtp.login(email, password)
                                    smtp.send_message(msg)
                                
                                log_email(name, emaddr, edited_subject, edited_body)
                                st.success("✅ Email sent successfully!")
                                # Clear generated email
                                del st.session_state.generated_individual_email
                                del st.session_state.individual_recipient
                                del st.session_state.individual_title
                            except Exception as e:
                                st.error(f"❌ Failed to send email: {str(e)}")
                
                with col2:
                    # Option to regenerate
                    if st.button("🔄 Regenerate", key="regenerate_indiv", use_container_width=True):
                        del st.session_state.generated_individual_email
                        del st.session_state.individual_recipient
                        del st.session_state.individual_title
                
                with col3:
                    # Option to clear
                    if st.button("❌ Clear", key="clear_indiv", use_container_width=True):
                        del st.session_state.generated_individual_email
                        del st.session_state.individual_recipient
                        del st.session_state.individual_title

        # B) Send Same to All
        elif email_mode == "Send Same to All":
            title = st.text_input("Email Title for everyone", key="search_bulk_title")
            tone = st.selectbox("Tone", ["professional", "friendly", "formal"], key="search_bulk_tone")
            
            # Step 1: Generate the email template
            if st.button("📝 Generate Email Template", key="generate_template", use_container_width=True):
                if not title:
                    st.warning("Please enter an email title first")
                else:
                    with st.spinner("Generating email template..."):
                        # Generate template using first contact as example
                        sample_contact = results[0] if results else {}
                        template_context = f"Title: {title}\nPlease generate a professional email template that can be personalized for multiple recipients. Start with 'Subject:' on the first line, then body. Use placeholders like [NAME] for personalization."
                        
                        # Generate email locally using the working function
                        subject, body = generate_email_groq(sample_contact.get("name", "Recipient"), template_context, name)
                        
                        # Store template in session state
                        st.session_state.email_template = f"Subject: {subject}\n\n{body}"
                        st.session_state.bulk_title = title
                        st.success("✅ Email template generated!")
            
            # Step 2: Review template and show preview
            if st.session_state.get("email_template"):
                st.markdown("---")
                st.subheader("📧 Review Email Template")
                
                template = st.session_state.email_template
                subject, body = extract_subject_and_body(template, fallback_subject=st.session_state.get("bulk_title", ""))
                
                # Show subject and body for review (editable)
                edited_bulk_subject = st.text_input("Subject Template", value=subject, key="review_bulk_subject")
                edited_bulk_body = st.text_area("Email Body Template", value=body, height=200, key="review_bulk_body")
                
                # Show preview with first contact
                if results:
                    st.markdown("**Preview with first contact:**")
                    preview_subject = subject.replace("[NAME]", results[0].get("name", "Recipient")).replace("[COMPANY]", results[0].get("company", ""))
                    preview_body = body.replace("[NAME]", results[0].get("name", "Recipient")).replace("[COMPANY]", results[0].get("company", ""))
                    st.info(f"**Subject:** {preview_subject}")
                    st.info(f"**Body:** {preview_body}")
                
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    # Step 3: Send to all contacts
                    if st.button("🚀 Send to All", type="primary", key="search_bulk_send", use_container_width=True):
                        contacts = results
                        if not contacts:
                            st.warning("No contacts to send")
                        else:
                            progress = st.progress(0)
                            success_count = 0

                            for i, c in enumerate(contacts):
                                emaddr = c.get("email", "")
                                if not emaddr:
                                    progress.progress((i + 1) / len(contacts))
                                    continue
                                
                                # Personalize the template for this contact
                                personalized_subject = edited_bulk_subject.replace("[NAME]", c.get("name", "Recipient")).replace("[COMPANY]", c.get("company", ""))
                                personalized_body = edited_bulk_body.replace("[NAME]", c.get("name", "Recipient")).replace("[COMPANY]", c.get("company", ""))
                                
                                # Send the personalized email
                                try:
                                    msg = EmailMessage()
                                    msg['From'] = email
                                    msg['To'] = emaddr
                                    msg['Subject'] = personalized_subject
                                    msg.set_content(personalized_body)
                                    
                                    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                                        smtp.login(email, password)
                                        smtp.send_message(msg)
                                    
                                    log_email(name, emaddr, personalized_subject, personalized_body)
                                    success_count += 1
                                except Exception as e:
                                    st.error(f"Failed to send to {emaddr}: {str(e)}")
                                
                                progress.progress((i + 1) / len(contacts))

                            st.success(f"✅ Personalized email sent to {success_count}/{len(contacts)} contacts!")
                            # Clear template after sending
                            if "email_template" in st.session_state:
                                del st.session_state.email_template
                            if "bulk_title" in st.session_state:
                                del st.session_state.bulk_title
                
                with col2:
                    # Option to regenerate template
                    if st.button("🔄 Regenerate", key="regenerate_bulk", use_container_width=True):
                        del st.session_state.email_template
                        del st.session_state.bulk_title
                
                with col3:
                    # Option to clear
                    if st.button("❌ Clear", key="clear_bulk", use_container_width=True):
                        del st.session_state.email_template
                        del st.session_state.bulk_title

        # C) Send Data to Personal Email
        elif email_mode == "Send Data to Personal Email":
            recipient_email = st.text_input("Recipient Email", value=email, key="search_data_recipient")
            email_title = st.text_input("Title (for subject generation)", value="Search Results Export", key="search_data_title")

            # Step 1: Generate Email
            if st.button("📝 Generate Email", key="search_data_generate", use_container_width=True):
                if not email_title:
                    st.warning("Please enter an email title first")
                else:
                    df = pd.DataFrame(results)
                    html_content = df.to_html(index=False)

                    # Generate email content
                    context = f"Title: {email_title}\nPlease draft an email and include the following data in the body:\n{html_content}\nStart with 'Subject:' then body."
                    with st.spinner("Generating email..."):
                        # Generate email locally using the working function
                        subject, body = generate_email_groq("Data Recipient", context, name)
                        
                        # Store generated email in session state
                        st.session_state.generated_data_email = f"Subject: {subject}\n\n{body}"
                        st.session_state.data_recipient = recipient_email
                        st.session_state.data_title = email_title
                        st.success("✅ Email generated successfully!")

            # Step 2: Review and Send (only show if email was generated)
            if st.session_state.get("generated_data_email"):
                st.markdown("---")
                st.subheader("📧 Review Generated Email")
                
                # Extract subject and body
                gen_email = st.session_state.generated_data_email
                subject, body = extract_subject_and_body(gen_email, fallback_subject=st.session_state.get("data_title", ""))
                
                # Show subject and body for review (editable)
                edited_data_subject = st.text_input("Subject", value=subject, key="review_data_subject")
                edited_data_body = st.text_area("Email Body", value=body, height=200, key="review_data_body")
                
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    # Send button
                    if st.button("📤 Send Data Email", key="search_data_send", type="primary", use_container_width=True):
                        recipient_email = st.session_state.get("data_recipient", "")
                        if not recipient_email:
                            st.warning("Please enter recipient email")
                        else:
                            # Send email locally using SMTP
                            try:
                                msg = EmailMessage()
                                msg['From'] = email
                                msg['To'] = recipient_email
                                msg['Subject'] = edited_data_subject
                                msg.set_content(edited_data_body)
                                
                                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                                    smtp.login(email, password)
                                    smtp.send_message(msg)
                                
                                log_email(name, recipient_email, edited_data_subject, edited_data_body)
                                st.success("✅ Data email sent successfully!")
                                # Clear generated email
                                del st.session_state.generated_data_email
                                del st.session_state.data_recipient
                                del st.session_state.data_title
                            except Exception as e:
                                st.error(f"❌ Failed to send data email: {str(e)}")
                
                with col2:
                    # Option to regenerate
                    if st.button("🔄 Regenerate", key="regenerate_data", use_container_width=True):
                        del st.session_state.generated_data_email
                        del st.session_state.data_recipient
                        del st.session_state.data_title
                
                with col3:
                    # Option to clear
                    if st.button("❌ Clear", key="clear_data", use_container_width=True):
                        del st.session_state.generated_data_email
                        del st.session_state.data_recipient
                        del st.session_state.data_title

    # Reset All Data Button
    st.markdown("---")
    col1_reset, col2_reset = st.columns([3, 1])
    with col1_reset:
        st.info("💡 Use the buttons above to view, download, or use your data for emails")
    with col2_reset:
        if st.button("🗑️ Reset All Data", key="reset_all_data", type="secondary"):
            # Clear MongoDB data
            st.session_state.mongo_users = None
            st.session_state.mongo_connected = False
            st.session_state.mongo_collections = []
            
            # Clear uploaded data
            st.session_state.uploaded_contacts = None
            
            # Clear MongoDB connections
            if "mongo_connections" in st.session_state and name in st.session_state.mongo_connections:
                del st.session_state.mongo_connections[name]
            
            # Clear file uploader
            st.session_state.file_uploader_main = None
            
            st.success("✅ All data sources (MongoDB + Uploaded files) cleared! Only email history remains.")
            # Don't call st.rerun() - let the UI update naturally

        st.markdown("---")
    

    
        # ---------------- Email Sending Section ----------------
    # This section is now integrated with the search functionality above
    # Use the search results to send emails with the 3 options

        # Email History Viewer
        if st.session_state.get('viewing_email'):
            with st.expander("📜 Viewing Sent Email", expanded=True):
                email_data = st.session_state.viewing_email
                st.write(f"**Subject:** {email_data.get('subject', 'No Subject')}")
                st.write(f"**To:** {email_data.get('recipient', 'Unknown')}")
                st.write(f"**Sent:** {email_data.get('timestamp', 'Unknown time')}")
                st.text_area("Body", value=email_data.get('body', 'No content'), height=300, disabled=True)
                if st.button("Close", key="close_history"):
                    st.session_state.viewing_email = None

# ------------------ Main App ------------------
def main():
    st.set_page_config(page_title="AI Email Assistant", page_icon="✉️", layout="wide")
    st.title("✉️ AI Email Assistant")

    # Initialize session state
    st.session_state.setdefault('subject', "")
    st.session_state.setdefault('body', "")
    st.session_state.setdefault('mongo_users', None)
    st.session_state.setdefault('uploaded_data', None)
    st.session_state.setdefault('viewing_email', None)

    name, email, password, mode = sidebar()

    if mode == "Simple Email":
        simple_mail_ui(name, email, password)
    else:
        database_fetch_ui(name, email, password)

if __name__ == "__main__":
    main()
