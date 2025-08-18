# test_send.py
from utils.send_email import send_email

result = send_email(
    subject="Test Email",
    body="This is a test from my FastAPI project.",
    to_email="your_test_email@gmail.com"
)
print(result)
