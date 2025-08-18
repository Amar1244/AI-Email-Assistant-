import os
import pandas as pd
import numpy as np
from pymongo import MongoClient
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer, util

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")
UPLOAD_DIR = "uploads"

embedding_model = None

def set_model_ready():
    global embedding_model
    if embedding_model is None:
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

def semantic_rank(texts, query, top_k=5):
    """Rank texts based on semantic similarity."""
    set_model_ready()
    query_emb = embedding_model.encode(query, convert_to_tensor=True)
    text_embs = embedding_model.encode(texts, convert_to_tensor=True)
    scores = util.pytorch_cos_sim(query_emb, text_embs)[0].cpu().numpy()
    ranked_idx = np.argsort(scores)[::-1][:top_k]
    return ranked_idx, scores

def search_data(query: str, source_type: str = "mongo", file_name: str = None, top_k: int = 5):
    """
    Search data from MongoDB or CSV/Excel file using semantic search.
    """
    if source_type == "mongo":
        if not (MONGO_URI and DB_NAME and COLLECTION_NAME):
            raise ValueError("MongoDB credentials not set in .env")
        
        client = MongoClient(MONGO_URI)
        collection = client[DB_NAME][COLLECTION_NAME]
        contacts = list(collection.find({}, {"_id": 0}))

        if not contacts:
            return []

        contact_texts = [
            f"{c.get('name', '')} ({c.get('email', '')}) from {c.get('company', '')}"
            for c in contacts
        ]

        ranked_idx, scores = semantic_rank(contact_texts, query, top_k)
        return [
            {
                "name": contacts[idx].get("name", ""),
                "email": contacts[idx].get("email", ""),
                "company": contacts[idx].get("company", ""),
                "similarity": float(scores[idx])
            }
            for idx in ranked_idx
        ]
    
    elif source_type == "file":
        if not file_name:
            raise ValueError("file_name is required when source_type='file'")

        file_path = os.path.join(UPLOAD_DIR, file_name)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File '{file_name}' not found in uploads")

        file_ext = os.path.splitext(file_name)[-1].lower()
        if file_ext == ".csv":
            df = pd.read_csv(file_path)
        elif file_ext == ".xlsx":
            df = pd.read_excel(file_path)
        else:
            raise ValueError("Unsupported file format")

        if df.empty:
            return []

        # Combine all columns into a search string
        row_texts = df.astype(str).agg(" ".join, axis=1).tolist()

        ranked_idx, scores = semantic_rank(row_texts, query, top_k)
        return [
            {**df.iloc[idx].to_dict(), "similarity": float(scores[idx])}
            for idx in ranked_idx
        ]

    else:
        raise ValueError("Invalid source_type. Choose 'mongo' or 'file'.")
