import os
import json
import base64
import requests
import pandas as pd
import streamlit as st
from io import BytesIO

# =============================
# Config
# =============================
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
TIMEOUT = 30

# =============================
# Small HTTP helpers
# =============================
def api_get(path: str, params: dict | None = None):
    try:
        r = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}
    except Exception as e:
        st.error(f"GET {path} failed: {e}")
        return None


def api_post(path: str, json_body: dict | None = None, data: dict | None = None, files: dict | None = None):
    try:
        if files is not None:
            r = requests.post(f"{API_BASE_URL}{path}", data=data, files=files, timeout=TIMEOUT)
        else:
            r = requests.post(f"{API_BASE_URL}{path}", json=json_body, timeout=TIMEOUT)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}
    except Exception as e:
        st.error(f"POST {path} failed: {e}")
        return None


def api_delete(path: str, params: dict | None = None, json_body: dict | None = None):
    try:
        r = requests.delete(f"{API_BASE_URL}{path}", params=params, json=json_body, timeout=TIMEOUT)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}
    except Exception as e:
        st.error(f"DELETE {path} failed: {e}")
        return None


# =============================
# Session defaults
# =============================
st.session_state.setdefault("user_id", "")
st.session_state.setdefault("name", "")
st.session_state.setdefault("email", "")
st.session_state.setdefault("passcode", "")
st.session_state.setdefault("mode", "Simple Mode")
st.session_state.setdefault("data_source", "Upload")
st.session_state.setdefault("saved", False)

st.session_state.setdefault("simple_subject", "")
st.session_state.setdefault("simple_body", "")

st.session_state.setdefault("mongo", {
    "mongo_url": "",
    "db_name": "",
    "collection_name": ""
})

# =============================
# UI: Sidebar
# =============================
with st.sidebar:
    st.title("⚙️ Settings")

    # --- User profile block ---
    st.subheader("👤 User Info")
    if not st.session_state.get("saved"):
        st.session_state.user_id = st.text_input("User ID", value=st.session_state.user_id)
        st.session_state.name = st.text_input("Name", value=st.session_state.name)
        st.session_state.email = st.text_input("Email", value=st.session_state.email)
        st.session_state.passcode = st.text_input("Passcode", type="password", value=st.session_state.passcode)
        if st.button("💾 Save", use_container_width=True):
            if all([st.session_state.user_id, st.session_state.name, st.session_state.email, st.session_state.passcode]):
                st.session_state.saved = True
                st.success("Saved user info.")
            else:
                st.warning("Please complete all fields.")
    else:
        st.write(f"**User ID:** {st.session_state.user_id}")
        st.write(f"**Name:** {st.session_state.name}")
        st.write(f"**Email:** {st.session_state.email}")
        st.write("**Passcode:** ••••••••")
        cols = st.columns(2)
        with cols[0]:
            if st.button("✏️ Edit", use_container_width=True):
                st.session_state.saved = False
        with cols[1]:
            if st.button("🧹 Clear", use_container_width=True):
                for k in ["user_id", "name", "email", "passcode"]:
                    st.session_state[k] = ""
                st.session_state.saved = False

    st.markdown("---")

    # --- Mode switch ---
    st.subheader("🧭 Mode")
    st.session_state.mode = st.radio(
        "Select Mode",
        ["Simple Mode", "DB Mode"],
        horizontal=True,
        index=0 if st.session_state.mode == "Simple Mode" else 1,
    )

    # --- Data source section ---
    st.subheader("🔌 Data Source")
    st.session_state.data_source = st.radio(
        "Source",
        ["MongoDB", "Upload"],
        horizontal=True,
        index=0 if st.session_state.data_source == "MongoDB" else 1,
    )

    # Mongo controls
    if st.session_state.data_source == "MongoDB":
        with st.expander("MongoDB Connection", expanded=False):
            st.session_state.mongo["mongo_url"] = st.text_input("Connection String", value=st.session_state.mongo["mongo_url"], placeholder="mongodb+srv://...")
            st.session_state.mongo["db_name"] = st.text_input("DB Name", value=st.session_state.mongo["db_name"])
            st.session_state.mongo["collection_name"] = st.text_input("Collection", value=st.session_state.mongo["collection_name"])
            if st.button("🔗 Connect", use_container_width=True):
                if not st.session_state.user_id:
                    st.warning("Please save User Info first.")
                else:
                    resp = api_post(
                        "/connect-mongo",
                        json_body={
                            "user_id": st.session_state.user_id,
                            **st.session_state.mongo,
                        },
                    )
                    if resp and resp.get("status") == "success":
                        st.success("Mongo connected & configured.")

        with st.expander("📦 Browse Mongo Data", expanded=False):
            if st.button("🔄 Refresh", use_container_width=True):
                if st.session_state.user_id:
                    info = api_get(f"/data-sources/{st.session_state.user_id}")
                    st.session_state.setdefault("mongo_sources", info)
                else:
                    st.warning("Save User Info first.")
            if src := st.session_state.get("mongo_sources"):
                st.json(src)
            # Quick view of current contacts from Mongo
            if st.button("👁️ View Contacts", use_container_width=True):
                contacts_resp = api_get(f"/get-contacts/{st.session_state.user_id}")
                if contacts_resp and contacts_resp.get("status") == "success":
                    df = pd.DataFrame(contacts_resp.get("contacts", []))
                    st.dataframe(df, use_container_width=True, height=300)

    # Upload controls
    if st.session_state.data_source == "Upload":
        with st.expander("⬆️ Upload CSV/Excel", expanded=False):
            up = st.file_uploader("Choose CSV/XLS/XLSX", type=["csv", "xls", "xlsx"])
            if up and st.button("📤 Upload", use_container_width=True):
                if not st.session_state.user_id:
                    st.warning("Please save User Info first.")
                else:
                    files = {"file": (up.name, up.getvalue(), "application/octet-stream")}
                    data = {"user_id": st.session_state.user_id}
                    resp = api_post("/upload-contacts", data=data, files=files)
                    if resp and resp.get("status") in ("success", "warning"):
                        st.success(resp.get("message", "Uploaded."))
        with st.expander("📚 Previously Uploaded Data", expanded=False):
            if st.button("👁️ Load My Contacts", use_container_width=True):
                res = api_get(f"/get-contacts/{st.session_state.user_id}")
                st.session_state["uploaded_contacts_cache"] = res
            if cache := st.session_state.get("uploaded_contacts_cache"):
                if cache.get("status") == "success":
                    df = pd.DataFrame(cache.get("contacts", []))
                    st.dataframe(df, use_container_width=True, height=300)


# =============================
# UI: Main area
# =============================
st.title("✉️ AI Email Assistant – Client App")

# Connection banner
ping = api_get("/")
if ping:
    st.success("Backend reachable.")
else:
    st.warning("Backend not reachable. Start FastAPI on API_BASE_URL.")

# Guard
if not st.session_state.saved:
    st.info("Save your User Info in the sidebar to begin.")
    st.stop()

# =============================
# SIMPLE MODE
# =============================
if st.session_state.mode == "Simple Mode":
    st.subheader("✉️ Simple Mail")
    col1, col2 = st.columns(2)
    with col1:
        recipient_name = st.text_input("Recipient Name")
        recipient_email = st.text_input("Recipient Email")
    with col2:
        title = st.text_input("Email Title (e.g., Interview Invite)")
        tone = st.selectbox("Tone", ["professional", "friendly", "formal"], index=0)

    cols = st.columns(3)
    with cols[0]:
        if st.button("📝 Generate", use_container_width=True):
            if not recipient_name or not title:
                st.warning("Enter recipient name and title.")
            else:
                ctx = f"Title: {title}\nPlease generate a professional email. Start with 'Subject:' on the first line, then the body."
                resp = api_post("/generate-email", json_body={
                    "contact_name": recipient_name,
                    "company_name": "",
                    "context": ctx,
                    "tone": tone,
                })
                if resp and resp.get("email"):
                    content = str(resp["email"]) or ""
                    # split subject/body
                    subject = ""
                    if "Subject:" in content:
                        subject = content.split("Subject:", 1)[1].split("\n", 1)[0].strip()
                    st.session_state.simple_subject = subject or title
                    body = content
                    if "\n\n" in content:
                        body = content.split("\n\n", 1)[1]
                    elif "\n" in content:
                        body = content.split("\n", 1)[1]
                    st.session_state.simple_body = body.strip()
                    st.success("Generated.")
    with cols[1]:
        if st.button("🧹 Clear", use_container_width=True):
            st.session_state.simple_subject = ""
            st.session_state.simple_body = ""
    with cols[2]:
        if st.button("📨 Send", use_container_width=True):
            if not recipient_email:
                st.warning("Enter recipient email.")
            elif not st.session_state.simple_subject or not st.session_state.simple_body:
                st.warning("Generate or write the email first.")
            else:
                resp = api_post("/send-email-only", json_body={
                    "user_id": st.session_state.user_id,
                    "recipient_email": recipient_email,
                    "subject": st.session_state.simple_subject,
                    "body": st.session_state.simple_body,
                })
                if resp and resp.get("status") == "success":
                    st.success("Email sent.")
                else:
                    st.error(resp.get("message", "Send failed."))

    st.text_input("Subject", value=st.session_state.simple_subject, key="simple_subject_box")
    st.text_area("Body", value=st.session_state.simple_body, height=260, key="simple_body_box")
    # keep edits
    st.session_state.simple_subject = st.session_state.simple_subject_box
    st.session_state.simple_body = st.session_state.simple_body_box

# =============================
# DB MODE
# =============================
else:
    st.subheader("🗃️ Database Mode")

    # ---------------- Contacts Explorer ----------------
    with st.expander("👥 Contacts Explorer", expanded=True):
        cols = st.columns([1,1,1,1])
        with cols[0]:
            if st.button("🔄 Refresh Contacts", use_container_width=True):
                res = api_get(f"/get-contacts/{st.session_state.user_id}")
                st.session_state["contacts_cache"] = res
        with cols[1]:
            topk = st.number_input("Top K", min_value=1, max_value=50, value=10)
        with cols[2]:
            query = st.text_input("Search query", placeholder="e.g., CTO in Mumbai fintech")
        with cols[3]:
            if st.button("🔍 Search", use_container_width=True):
                payload = {
                    "user_id": st.session_state.user_id,
                    "query": query or "",
                    "top_k": int(topk),
                }
                res = api_post("/search-contacts", json_body=payload)
                st.session_state["search_results"] = res

        if cc := st.session_state.get("contacts_cache"):
            if cc.get("status") == "success":
                df = pd.DataFrame(cc.get("contacts", []))
                st.dataframe(df, use_container_width=True, height=280)

        if sr := st.session_state.get("search_results"):
            if sr.get("status") == "success":
                st.markdown("**Search Results:**")
                df = pd.DataFrame(sr.get("results", []))
                st.dataframe(df, use_container_width=True, height=280)

                # delete support (for uploaded records only, by _id string)
                ids_for_delete = st.multiselect("Select _id to delete (uploaded or Mongo _id)", [str(x) for x in df.get("_id", [])])
                colx, coly = st.columns(2)
                with colx:
                    if st.button("🗑️ Delete from Uploaded", use_container_width=True):
                        if ids_for_delete:
                            resp = api_delete("/delete-records", json_body={
                                "user_id": st.session_state.user_id,
                                "record_ids": ids_for_delete,
                                "source": "uploaded",
                            })
                            if resp and resp.get("status") == "success":
                                st.success(f"Deleted {resp.get('deleted_count', 0)} records from uploaded.")
                with coly:
                    if st.button("🗑️ Delete from Mongo", use_container_width=True):
                        if ids_for_delete:
                            resp = api_delete("/delete-records", json_body={
                                "user_id": st.session_state.user_id,
                                "record_ids": ids_for_delete,
                                "source": "mongo",
                            })
                            if resp and resp.get("status") == "success":
                                st.success(f"Deleted {resp.get('deleted_count', 0)} records from mongo.")

    # ---------------- Email Generator/Sender ----------------
    with st.expander("✉️ Generate & Send Emails", expanded=True):
        st.markdown("Use a template or one-off generation. Sending uses `/send-email-only`.\n\n")

        tabs = st.tabs(["📝 Generate", "📨 Send Same to Many", "📬 History", "📦 Templates"]) 

        # --- Generate one email (does not send by itself) ---
        with tabs[0]:
            col1, col2 = st.columns(2)
            with col1:
                c_name = st.text_input("Contact Name")
                c_company = st.text_input("Company Name")
            with col2:
                tone = st.selectbox("Tone", ["professional", "friendly", "formal"], index=0)
                context = st.text_area("Context / Prompt", height=140)
            if st.button("🧠 Generate Email", key="gen_one"):
                res = api_post("/generate-email", json_body={
                    "contact_name": c_name,
                    "company_name": c_company,
                    "context": context,
                    "tone": tone,
                })
                if res and res.get("email"):
                    st.session_state["gen_email_text"] = res["email"]
            gen_txt = st.text_area("Generated Content", value=st.session_state.get("gen_email_text", ""), height=220)
            st.session_state["gen_email_text"] = gen_txt

            # quick send
            rcpt = st.text_input("Recipient Email")
            subj = st.text_input("Subject")
            body = st.text_area("Body", height=160)
            if st.button("📨 Send Now", key="send_now"):
                if not rcpt:
                    st.warning("Recipient required.")
                else:
                    payload = {
                        "user_id": st.session_state.user_id,
                        "recipient_email": rcpt,
                        "subject": subj,
                        "body": body or st.session_state.get("gen_email_text", ""),
                    }
                    r = api_post("/send-email-only", json_body=payload)
                    if r and r.get("status") == "success":
                        st.success("Sent.")

        # --- Bulk send: same template personalized ---
        with tabs[1]:
            st.caption("Pick contacts via /get-contacts and send a templated mail. Server will also generate body per contact.")
            if st.button("Load Contacts", key="bulk_load"):
                res = api_get(f"/get-contacts/{st.session_state.user_id}")
                st.session_state["bulk_contacts"] = res
            bulk_cache = st.session_state.get("bulk_contacts")
            all_ids = []
            if bulk_cache and bulk_cache.get("status") == "success":
                df = pd.DataFrame(bulk_cache.get("contacts", []))
                st.dataframe(df, use_container_width=True, height=260)
                # contact_ids can be either emails or _id strings per API
                all_ids = [str(x) for x in df.get("_id", []) if pd.notna(x)] + [str(x) for x in df.get("email", []) if pd.notna(x)]
            chosen = st.multiselect("Select IDs or Emails", options=all_ids)
            tone2 = st.selectbox("Tone", ["professional", "friendly", "formal"], index=0, key="tone2")
            context2 = st.text_area("Context for bulk", height=130, key="ctx2")
            if st.button("🚀 Send Bulk", use_container_width=True):
                if not chosen:
                    st.warning("Select at least one id/email.")
                else:
                    resp = api_post("/send-bulk-emails", json_body={
                        "user_id": st.session_state.user_id,
                        "contact_ids": chosen,
                        "context": context2,
                        "tone": tone2,
                    })
                    if resp and resp.get("status") == "success":
                        st.success("Bulk send initiated/processed.")
                        st.json(resp)

        # --- History ---
        with tabs[2]:
            cols = st.columns(3)
            with cols[0]:
                if st.button("🔄 Refresh JSON History"):
                    h = api_get("/get-email-history", params={"user_id": st.session_state.user_id})
                    st.session_state["hist_json"] = h
            with cols[1]:
                if st.button("🔄 Refresh CSV History"):
                    h = api_get("/mail_history")
                    st.session_state["hist_csv"] = h
            with cols[2]:
                if st.button("🗑️ Delete My JSON History"):
                    r = api_delete("/delete-email-history", params={"user_id": st.session_state.user_id})
                    if r and r.get("status") == "success":
                        st.success("Deleted.")

            if jh := st.session_state.get("hist_json"):
                st.markdown("**Per-user JSON history:**")
                st.json(jh)
            if ch := st.session_state.get("hist_csv"):
                st.markdown("**Global CSV history:**")
                df = pd.DataFrame(ch)
                st.dataframe(df, use_container_width=True, height=280)

        # --- Templates ---
        with tabs[3]:
            tcols = st.columns(3)
            with tcols[0]:
                if st.button("🔄 Load My Templates"):
                    res = api_get(f"/get-templates/{st.session_state.user_id}")
                    st.session_state["my_templates"] = res
            with tcols[1]:
                new_id = st.text_input("Template ID")
                t_subject = st.text_input("Subject (vars like [NAME])")
                t_body = st.text_area("Body", height=140)
                t_vars = st.text_input("Variables (comma separated)", placeholder="NAME, COMPANY")
                if st.button("💾 Save Template"):
                    tpl = {
                        "template_id": new_id,
                        "subject": t_subject,
                        "body": t_body,
                        "variables": [v.strip() for v in (t_vars or "").split(",") if v.strip()],
                    }
                    r = api_post("/save-template", json_body=tpl, data=None)
                    # note: /save-template expects query param user_id; FastAPI def accepts (user_id: str, template: EmailTemplate)
                    # We'll send as params by switching to requests directly
                    try:
                        r = requests.post(
                            f"{API_BASE_URL}/save-template",
                            params={"user_id": st.session_state.user_id},
                            json=tpl,
                            timeout=TIMEOUT,
                        )
                        r.raise_for_status()
                        st.success("Saved template.")
                    except Exception as e:
                        st.error(f"Save failed: {e}")
            with tcols[2]:
                del_id = st.text_input("Template ID to delete")
                if st.button("🗑️ Delete Template"):
                    r = api_delete("/delete-template", params={
                        "user_id": st.session_state.user_id,
                        "template_id": del_id,
                    })
                    if r and r.get("status") == "success":
                        st.success("Deleted template.")

            if mt := st.session_state.get("my_templates"):
                st.json(mt)

    # ---------------- Data-Sources Control ----------------
    with st.expander("🧩 Data-Sources Control", expanded=False):
        st.caption("Inspect and configure priorities/activation of 'uploaded' and 'mongo' sources.")
        if st.button("🔄 Inspect Sources"):
            res = api_get(f"/data-sources/{st.session_state.user_id}")
            st.session_state["ds_meta"] = res
        if meta := st.session_state.get("ds_meta"):
            st.json(meta)
        src = st.selectbox("Source to configure", ["uploaded", "mongo"])
        active = st.checkbox("Active", value=True)
        priority = st.number_input("Priority", min_value=1, max_value=10, value=1)
        if st.button("💾 Save Config"):
            payload = {
                "user_id": st.session_state.user_id,
                "source_name": src,
                "config": {"active": bool(active), "priority": int(priority)},
            }
            r = api_post("/configure-source", json_body=payload)
            if r and r.get("status") == "success":
                st.success("Config saved.")

    # ---------------- Health / Raw tools ----------------
    with st.expander("🧪 Raw Tools & Health", expanded=False):
        st.code(json.dumps(ping or {}, indent=2), language="json")
        st.caption("This app integrates the 17 endpoints from your FastAPI server: \n"
                   "1) GET /  2) GET /data-sources/{user_id}  3) POST /configure-source  4) DELETE /delete-records  \n"
                   "5) POST /connect-mongo  6) POST /upload-contacts  7) GET /get-contacts/{user_id}  8) POST /search-contacts  \n"
                   "9) POST /generate-email  10) POST /generate-and-send-email  11) POST /send-email-only  12) POST /send-bulk-emails  \n"
                   "13) GET /get-email-history  14) GET /mail_history  15) DELETE /delete-email-history  \n"
                   "16) POST /save-template  17) GET /get-templates/{user_id}  18) DELETE /delete-template")
        st.caption("Note: list shows 18 including templates delete; your earlier count of 17 can exclude /generate-and-send-email (non-sending) or group template ops.")
