import os  # here it is used for file systems operations 
import json # it is used for json file reading / writing 
import shutil # it is used for file update/ deletion 
import datetime # for current date tim
import pandas as pd # for csv,excel files
import numpy as np  # for numric operation.
from fastapi import FastAPI, Query, UploadFile, File, Form, HTTPException # here it is FastApi imports for API buildings
from fastapi.middleware.cors import CORSMiddleware # to safely make a request to  my API
from pydantic import BaseModel  # for data validation models
from typing import Optional, List, Dict, Union
from pymongo import MongoClient
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer, util
import io
from utils.email_gen import generate_email
from utils.send_email import send_email
from bson import ObjectId
from typing import Any
from nlp_engine import NaturalEmailAssistant

# -------------------------
# Here i will be loading the .env files.
# -------------------------
load_dotenv()

# -------------------------
# App Setup
# -------------------------
app = FastAPI(
    title="AI Email API",
    description="API for semantic search from MongoDB or CSV/Excel, AI email generation, sending, and logging",
    version="2.1.0"  #  # API version (not FastAPI version itself)
)

# Enable CORS (frontend & backend communication without blocking)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # Allow all origins
    allow_methods=["*"],    # Allow all HTTP methods
    allow_headers=["*"],    # Allow all headers
)

# -------------------------
# Globals
# -------------------------
HISTORY_FILE = "email_history.json"
CONTACTS_FILE = "uploaded_contacts.json"
MONGO_FILE = "mongo_connections.json"
TEMPLATES_FILE = "email_templates.json"
UPLOAD_FOLDER = "uploaded_data"
MAIL_HISTORY_FILE = "mail_history.csv"
DATA_SOURCES_FILE = "data_sources.json"

# Initialize directories
# Create directory for uploads if not exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load or initialize data stores
uploaded_contacts = {}
if os.path.exists(CONTACTS_FILE):
    with open(CONTACTS_FILE, "r") as f:
        uploaded_contacts = json.load(f)

email_history = {}
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r") as f:
        email_history = json.load(f)

mongo_connections = {}
if os.path.exists(MONGO_FILE):
    with open(MONGO_FILE, "r") as f:
        mongo_connections = json.load(f)

email_templates = {}
if os.path.exists(TEMPLATES_FILE):
    with open(TEMPLATES_FILE, "r") as f:
        email_templates = json.load(f)

data_sources = {}
if os.path.exists(DATA_SOURCES_FILE):
    with open(DATA_SOURCES_FILE, "r") as f:
        data_sources = json.load(f)

# Initialize CSV mail history if not exists
if not os.path.exists(MAIL_HISTORY_FILE):
    pd.DataFrame(columns=["recipient", "subject", "body"]).to_csv(MAIL_HISTORY_FILE, index=False)

embedding_model = None

# -------------------------
# Helper Functions
# -------------------------
def save_uploaded_contacts():
    with open(CONTACTS_FILE, "w") as f:
        json.dump(uploaded_contacts, f, indent=4)

def save_email_history():
    with open(HISTORY_FILE, "w") as f:
        json.dump(email_history, f, indent=4)

def save_mongo_connections():
    with open(MONGO_FILE, "w") as f:
        json.dump(mongo_connections, f, indent=4)

def save_email_templates():
    with open(TEMPLATES_FILE, "w") as f:
        json.dump(email_templates, f, indent=4)

def save_data_sources():
    with open(DATA_SOURCES_FILE, "w") as f:
        json.dump(data_sources, f, indent=4)

def log_email_in_app(user_id: str, subject: str, body: str, recipient: str):
    if user_id not in email_history:
        email_history[user_id] = []
    email_history[user_id].append({
        "subject": subject,
        "body": body,
        "recipient": recipient,
        "timestamp": datetime.datetime.utcnow().isoformat()
    })
    save_email_history()
    
    df = pd.read_csv(MAIL_HISTORY_FILE)
    df.loc[len(df)] = [recipient, subject, body]
    df.to_csv(MAIL_HISTORY_FILE, index=False)

def set_model_ready():
    global embedding_model
    if embedding_model is None:
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

def get_mongo_client(mongo_url: str):
    return MongoClient(mongo_url, serverSelectionTimeoutMS=5000)

# -------------------------
# Data Management Models
# -------------------------
class DataSourceConfig(BaseModel):
    active: bool = True
    priority: int = 1

class DataSourceSelection(BaseModel):
    user_id: str
    source_name: str  # "uploaded" or "mongo"
    config: DataSourceConfig

class RecordDeletionRequest(BaseModel):
    user_id: str
    record_ids: List[str]
    source: str  # "uploaded" or "mongo"

# -------------------------
# FastAPI Routes
# -------------------------
@app.get("/")
def home():
    return {"message": "AI Email API is running!"}

# -------------------------
# Data Source Management
# -------------------------
@app.get("/data-sources/{user_id}")
def get_data_sources(user_id: str):
    """List all available data sources with stats"""
    sources = {}
    
    # Uploaded CSV/Excel data
    if user_id in uploaded_contacts:
        sources["uploaded"] = {
            "count": len(uploaded_contacts[user_id]),
            "sample": uploaded_contacts[user_id][:3],
            "config": data_sources.get(user_id, {}).get("uploaded", {"active": True, "priority": 1})
        }
    
    # MongoDB connection info
    if user_id in mongo_connections:
        try:
            creds = mongo_connections[user_id]
            client = get_mongo_client(creds["mongo_url"])
            db = client[creds["db_name"]]
            collection = db[creds["collection_name"]]
            count = collection.count_documents({})
            
            sources["mongo"] = {
                "count": count,
                "sample": list(collection.find({}, {"_id": 0}).limit(3)),
                "config": data_sources.get(user_id, {}).get("mongo", {"active": True, "priority": 2})
            }
        except Exception as e:
            sources["mongo"] = {
                "error": str(e),
                "config": data_sources.get(user_id, {}).get("mongo", {"active": False, "priority": 2})
            }
    
    return {"user_id": user_id, "sources": sources}

@app.post("/configure-source")
def configure_data_source(data: DataSourceSelection):
    """Enable/disable or prioritize data sources"""
    if data.user_id not in data_sources:
        data_sources[data.user_id] = {}
    
    data_sources[data.user_id][data.source_name] = data.config.dict()
    save_data_sources()
    
    return {"status": "success", "message": f"Source {data.source_name} configured"}

@app.delete("/delete-records")
async def delete_records(request: RecordDeletionRequest):
    """Delete specific records from a data source"""
    try:
        deleted_count = 0
        
        if request.source == "uploaded" and request.user_id in uploaded_contacts:
            # Create backup before deletion
            backup = uploaded_contacts[request.user_id]
            
            # Filter out records to delete
            uploaded_contacts[request.user_id] = [
                record for record in uploaded_contacts[request.user_id]
                if str(record.get("_id", "")) not in request.record_ids
            ]
            deleted_count = len(backup) - len(uploaded_contacts[request.user_id])
            save_uploaded_contacts()
            
        elif request.source == "mongo" and request.user_id in mongo_connections:
            creds = mongo_connections[request.user_id]
            client = get_mongo_client(creds["mongo_url"])
            db = client[creds["db_name"]]
            collection = db[creds["collection_name"]]
            
            # Convert string IDs to ObjectId
            object_ids = [ObjectId(rid) for rid in request.record_ids]
            result = collection.delete_many({"_id": {"$in": object_ids}})
            deleted_count = result.deleted_count
            
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "remaining": get_data_sources(request.user_id)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# -------------------------
# MongoDB Connection
# -------------------------
class MongoConnectRequest(BaseModel):
    user_id: str
    mongo_url: str
    db_name: str
    collection_name: str

@app.post("/connect-mongo")
def connect_mongo(data: MongoConnectRequest):
    mongo_connections[data.user_id] = {
        "mongo_url": data.mongo_url,
        "db_name": data.db_name,
        "collection_name": data.collection_name
    }
    save_mongo_connections()
    
    # Initialize source configuration
    if data.user_id not in data_sources:
        data_sources[data.user_id] = {}
    data_sources[data.user_id]["mongo"] = {"active": True, "priority": 1}
    save_data_sources()
    
    return {"status": "success", "message": f"MongoDB connected for user {data.user_id}"}

# -------------------------
# File Operations
# -------------------------
@app.post("/upload-contacts")
async def upload_contacts(user_id: str = Form(...), file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith((".csv", ".xls", ".xlsx")):
            return {
                "status": "error",
                "message": "Only CSV or Excel files are supported",
                "supported_formats": ["csv", "xls", "xlsx"]
            }

        contents = await file.read()
        file_like = io.BytesIO(contents)
        
        if file.filename.lower().endswith(".csv"):
            df = pd.read_csv(file_like)
        else:
            df = pd.read_excel(file_like)

        contacts = df.replace({np.nan: None}).to_dict(orient="records")
        
        # Add unique IDs for management
        for i, contact in enumerate(contacts):
            contact["_id"] = str(i)  # Simple ID for management
            
        uploaded_contacts[user_id] = contacts
        save_uploaded_contacts()
        
        # Initialize source configuration
        if user_id not in data_sources:
            data_sources[user_id] = {}
        data_sources[user_id]["uploaded"] = {"active": True, "priority": 1}
        save_data_sources()

        return {
            "status": "success",
            "message": f"Uploaded {len(contacts)} contacts",
            "user_id": user_id,
            "contact_count": len(contacts),
            "first_contact": contacts[0] if contacts else None
        }
    except Exception as e:
        return {"status": "error", "message": f"Processing error: {str(e)}"}
    finally:
        await file.close()

@app.get("/get-contacts/{user_id}")
def get_contacts(user_id: str):
    """Get contacts for a user from uploaded data (in-memory/file) or MongoDB."""
    # 1) Check uploaded (in-memory/file-backed)
    if user_id in uploaded_contacts:
        return {
            "status": "success",
            "source": "uploaded",
            "contacts": uploaded_contacts[user_id]
        }

    # 2) Fallback to MongoDB connection if configured
    if user_id in mongo_connections:
        creds = mongo_connections[user_id]
        client = get_mongo_client(creds["mongo_url"])
        db = client[creds["db_name"]]
        collection = db[creds["collection_name"]]
        contacts = list(collection.find({}, {"_id": 0}))
        return {
            "status": "success",
            "source": "mongo",
            "contacts": contacts
        }

    # 3) Nothing found
    return {
        "status": "error",
        "message": "No contacts found for this user"
    }

# @app.get("/get-contacts/{user_id}")
# def get_contacts(user_id: str):
#     """Get uploaded contacts for a specific user"""
#     if user_id in uploaded_contacts:
#         return {
#             "status": "success",
#             "contacts": uploaded_contacts[user_id],
#             "count": len(uploaded_contacts[user_id])
#         }
#     else:
#         return {
#             "status": "error",
#             "message": "No contacts found for this user"
#         }

# -------------------------
# Enhanced Search Endpoint
# -------------------------
class SearchRequest(BaseModel):
    user_id: str
    query: str
    top_k: int = 5
    use_sources: Optional[List[str]] = None  # ["uploaded", "mongo"]

@app.post("/search-contacts")
async def search_contacts_api(data: SearchRequest):
    """Enhanced search with source selection"""
    try:
        all_contacts = []
        active_sources = data.use_sources or ["uploaded", "mongo"]
        
        # Get from uploaded contacts if enabled
        if "uploaded" in active_sources and data.user_id in uploaded_contacts:
            upload_config = data_sources.get(data.user_id, {}).get("uploaded", {})
            if upload_config.get("active", True):
                all_contacts.extend(uploaded_contacts[data.user_id])
        
        # Get from MongoDB if enabled
        if "mongo" in active_sources and data.user_id in mongo_connections:
            mongo_config = data_sources.get(data.user_id, {}).get("mongo", {})
            if mongo_config.get("active", True):
                creds = mongo_connections[data.user_id]
                client = get_mongo_client(creds["mongo_url"])
                db = client[creds["db_name"]]
                collection = db[creds["collection_name"]]
                all_contacts.extend(list(collection.find({}, {"_id": 0})))
        
        if not all_contacts:
            return {"status": "error", "message": "No contacts available"}
        
        # Use advanced NLP engine for search
        nlp = NaturalEmailAssistant()
        results = nlp.enhanced_search(all_contacts, data.query, data.top_k)
        
        return {
            "status": "success",
            "results": results,
            "source_counts": {
                "uploaded": len(uploaded_contacts.get(data.user_id, [])),
                "mongo": len(all_contacts) - len(uploaded_contacts.get(data.user_id, []))
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# -------------------------
# Email Endpoints
# -------------------------
class EmailRequest(BaseModel):
    contact_name: str
    company_name: str
    context: str
    tone: str = "professional"

@app.post("/generate-email")
def generate_email_api(data: EmailRequest):
    email_content = generate_email(
        contact_name=data.contact_name,
        company_name=data.company_name,
        context=data.context,
        tone=data.tone
    )
    return {"email": email_content}

class EmailSendRequest(EmailRequest):
    recipient_email: str
    user_id: str

@app.post("/generate-and-send-email")
def generate_and_send_email(data: EmailSendRequest):
    try:
        email_body = generate_email(
            contact_name=data.contact_name,
            company_name=data.company_name,
            context=data.context,
            tone=data.tone
        )
        
        # Just return the generated email content, don't try to send it
        return {
            "generated_email": email_body,
            "status": "success",
            "message": "Email generated successfully"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to generate email: {str(e)}"
        }

class BulkEmailRequest(BaseModel):
    user_id: str
    contact_ids: List[str]  # Can be email addresses or contact IDs
    context: str
    tone: str = "professional"

class SendEmailOnlyRequest(BaseModel):
    user_id: str
    recipient_email: str
    subject: str
    body: str

@app.post("/send-email-only")
async def send_email_only(data: SendEmailOnlyRequest):
    """Send email without generating content - just send existing content"""
    try:
        send_status = send_email(data.subject, data.body, data.recipient_email)
        
        if send_status["status"] == "success":
            log_email_in_app(data.user_id, data.subject, data.body, data.recipient_email)
            return {"status": "success", "message": "Email sent successfully"}
        else:
            return {"status": "error", "message": send_status.get("message", "Failed to send email")}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/send-bulk-emails")
async def send_bulk_emails(data: BulkEmailRequest):
    """Send personalized emails to multiple contacts"""
    contacts_response = get_contacts(data.user_id)
    if contacts_response["status"] != "success":
        return {"status": "error", "message": "Failed to get contacts"}
    
    contacts = contacts_response.get("contacts", [])
    selected_contacts = [c for c in contacts if c.get("email") in data.contact_ids or str(c.get("_id", "")) in data.contact_ids]
    
    if not selected_contacts:
        return {"status": "error", "message": "No matching contacts found"}
    
    results = []
    for contact in selected_contacts:
        email_body = generate_email(
            contact_name=contact.get("name", ""),
            company_name=contact.get("company", ""),
            context=data.context,
            tone=data.tone
        )
        send_status = send_email(
            f"Follow-up from {contact.get('company', '')}",
            email_body,
            contact.get("email")
        )
        
        if send_status["status"] == "success":
            log_email_in_app(
                data.user_id,
                f"Follow-up from {contact.get('company', '')}",
                email_body,
                contact.get("email")
            )
        
        results.append({
            "email": contact.get("email"),
            "status": send_status,
            "generated_email": email_body
        })
    
    return {"status": "success", "results": results}

# -------------------------
# History Endpoints
# -------------------------
@app.get("/get-email-history")
def get_email_history(user_id: str):
    """Get email history from JSON storage"""
    return {"user_id": user_id, "history": email_history.get(user_id, [])}

@app.get("/mail_history")
def api_mail_history():
    """Get all email history from CSV storage"""
    if os.path.exists(MAIL_HISTORY_FILE):
        df = pd.read_csv(MAIL_HISTORY_FILE)
        return df.to_dict(orient="records")
    return []

@app.delete("/delete-email-history")
def delete_email_history(user_id: str):
    if user_id in email_history:
        del email_history[user_id]
        save_email_history()
        return {"status": "success", "message": f"History for user {user_id} deleted"}
    return {"status": "error", "message": f"No history found for user {user_id}"}

@app.delete("/reset-user/{user_id}")
def reset_user(user_id: str):
    """Completely remove a user's data: uploaded contacts, history, templates, mongo config, and data source config.
    Also attempts to delete any files under the upload folder that are prefixed with the user_id.
    """
    summary = {
        "uploaded": 0,
        "history": 0,
        "templates": 0,
        "mongo": 0,
        "data_sources": 0,
        "files_deleted": 0
    }

    # Uploaded contacts
    if user_id in uploaded_contacts:
        summary["uploaded"] = len(uploaded_contacts[user_id])
        del uploaded_contacts[user_id]
        save_uploaded_contacts()

    # Email history
    if user_id in email_history:
        summary["history"] = len(email_history[user_id])
        del email_history[user_id]
        save_email_history()

    # Templates
    if user_id in email_templates:
        summary["templates"] = len(email_templates[user_id])
        del email_templates[user_id]
        save_email_templates()

    # Mongo connection
    if user_id in mongo_connections:
        del mongo_connections[user_id]
        save_mongo_connections()
        summary["mongo"] = 1

    # Data source config
    if user_id in data_sources:
        del data_sources[user_id]
        save_data_sources()
        summary["data_sources"] = 1

    # Try deleting any files in the upload folder scoped to the user (best-effort)
    deleted_count = 0
    try:
        for fname in os.listdir(UPLOAD_FOLDER):
            if fname.startswith(f"{user_id}_"):
                fpath = os.path.join(UPLOAD_FOLDER, fname)
                try:
                    os.remove(fpath)
                    deleted_count += 1
                except Exception:
                    pass
    except Exception:
        pass

    summary["files_deleted"] = deleted_count

    return {
        "status": "success",
        "message": f"Reset data for user {user_id}",
        "summary": summary
    }

# -------------------------
# Template Management
# -------------------------
class EmailTemplate(BaseModel):
    template_id: str
    subject: str
    body: str
    variables: List[str]

@app.post("/save-template")
def save_template(user_id: str, template: EmailTemplate):
    if user_id not in email_templates:
        email_templates[user_id] = {}
    email_templates[user_id][template.template_id] = template.dict()
    save_email_templates()
    return {"status": "success", "message": "Template saved"}

@app.get("/get-templates/{user_id}")
def get_templates(user_id: str):
    return {"templates": email_templates.get(user_id, {})}

@app.delete("/delete-template")
def delete_template(user_id: str, template_id: str):
    if user_id in email_templates and template_id in email_templates[user_id]:
        del email_templates[user_id][template_id]
        save_email_templates()
        return {"status": "success", "message": "Template deleted"}
    return {"status": "error", "message": "Template not found"}