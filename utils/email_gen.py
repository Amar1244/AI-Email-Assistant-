# utils/email_gen.py
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()  # Load .env variables

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def generate_email_with_groq(contact_name, company_name, context, tone="professional"):
    """Generate email using Groq API"""
    try:
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY not set")
            
        client = Groq(api_key=GROQ_API_KEY)
        prompt = f"""
        You are an AI email assistant. Write a {tone} email to {contact_name} from {company_name}.
        Context: {context}
        The email should be clear, concise, and personalized.
        Start with 'Subject:' on the first line, then the email body.
        """

        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": "You are a helpful AI email generator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API error: {e}")
        return None

def generate_fallback_email(contact_name, company_name, context, tone="professional"):
    """Generate a simple email template without external APIs"""
    tone_style = {
        "professional": "I hope this email finds you well.",
        "friendly": "I hope you're doing great!",
        "formal": "I trust this message reaches you in good health."
    }
    
    opening = tone_style.get(tone, tone_style["professional"])
    
    # Extract title from context
    title = "Follow-up"
    if "Title:" in context:
        title_line = [line for line in context.split('\n') if line.strip().startswith('Title:')]
        if title_line:
            title = title_line[0].replace('Title:', '').strip()
    
    email_template = f"""Subject: {title}

Dear {contact_name},

{opening}

{context}

Best regards,
{company_name if company_name else 'Your Team'}"""
    
    return email_template

def generate_email(contact_name, company_name, context, tone="professional"):
    """Main email generation function with fallback"""
    # Try Groq API first
    email_content = generate_email_with_groq(contact_name, company_name, context, tone)
    
    # If Groq fails, use fallback
    if not email_content:
        email_content = generate_fallback_email(contact_name, company_name, context, tone)
    
    return email_content

