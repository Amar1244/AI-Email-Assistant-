import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load .env file variables
load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

def send_email(subject: str, body: str, to_email: str):
    """
    Sends an email using Gmail SMTP with App Password.
    """
    try:
        if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
            return {"status": "error", "message": "Email credentials not set in .env"}

        # Create the email message
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Connect to Gmail's SMTP server
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to_email, msg.as_string())

        return {"status": "success", "message": f"Email sent to {to_email}"}

    except smtplib.SMTPAuthenticationError:
        return {"status": "error", "message": "SMTP Authentication failed. Check Gmail App Password."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
