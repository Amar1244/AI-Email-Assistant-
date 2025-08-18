import requests

BASE_URL = "http://127.0.0.1:8000"  # Change if deployed
USER_ID = "test_user_1"

# Step 1 — Upload a CSV file
files = {
    "file": open("contacts.csv", "rb")  # replace with your CSV or Excel file path
}
params = {
    "user_id": USER_ID
}

upload_res = requests.post(f"{BASE_URL}/upload-contacts", params=params, files=files)
print("Upload Response:", upload_res.json())

# Step 2 — Search contacts
search_payload = {
    "user_id": USER_ID,
    "query": "CEO of a software company",
    "top_k": 5
}

search_res = requests.post(f"{BASE_URL}/search-contacts", json=search_payload)
print("Search Results:", search_res.json())
