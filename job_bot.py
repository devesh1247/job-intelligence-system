import os
import imaplib
import email
import re
import hashlib
from datetime import datetime, timedelta
from email.header import decode_header

import PyPDF2
import gspread
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from telegram import Bot

# ==============================
# LOAD ENV VARIABLES
# ==============================
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ==============================
# GOOGLE SHEETS SETUP
# ==============================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file(
    "service_account.json",
    scopes=SCOPES
)
client = gspread.authorize(creds)
sheet = client.open("Job Tracker").sheet1

# ==============================
# TELEGRAM
# ==============================
bot = Bot(token=TELEGRAM_TOKEN)

# ==============================
# LOAD RESUME TEXT
# ==============================
def extract_resume_text():
    try:
        with open("resume.pdf", "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                if page.extract_text():
                    text += page.extract_text()
            return text.lower()
    except:
        return ""

resume_text = extract_resume_text()

# ==============================
# SMART KEYWORDS (Weighted)
# ==============================
PRIMARY_KEYWORDS = [
    "python", "data", "analysis", "analyst",
    "machine learning", "django", "sql",
    "backend", "developer", "software engineer"
]

SECONDARY_KEYWORDS = [
    "api", "pandas", "numpy", "flask",
    "automation", "ai", "deep learning",
    "etl", "cloud", "aws", "azure"
]

# ==============================
# CLEAN SUBJECT (Fix UTF Encoding)
# ==============================
def clean_subject(subject):
    decoded = decode_header(subject)
    result = ""
    for part, encoding in decoded:
        if isinstance(part, bytes):
            result += part.decode(encoding or "utf-8", errors="ignore")
        else:
            result += part
    return result

# ==============================
# SCORE FUNCTION (Weighted)
# ==============================
def calculate_score(text):
    text = text.lower()
    score = 0

    for word in PRIMARY_KEYWORDS:
        if word in text:
            score += 10

    for word in SECONDARY_KEYWORDS:
        if word in text:
            score += 5

    return score

# ==============================
# REMOVE DUPLICATES
# ==============================
def already_exists(unique_id):
    try:
        records = sheet.col_values(1)
        return unique_id in records
    except:
        return False

# ==============================
# MAIN EMAIL CHECK
# ==============================
def check_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    result, data = mail.search(None, '(UNSEEN)')
    mail_ids = data[0].split()

    for num in mail_ids:
        result, msg_data = mail.fetch(num, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg["subject"]
        if subject is None:
            continue

        subject = clean_subject(subject)

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode(errors="ignore")
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        soup = BeautifulSoup(body, "html.parser")
        email_text = soup.get_text()

        full_text = subject + " " + email_text

        score = calculate_score(full_text)

        # Skip low relevance
        if score < 10:
            continue

        # Unique ID to avoid duplicate alerts
        unique_id = hashlib.md5(subject.encode()).hexdigest()
        if already_exists(unique_id):
            continue

        # IST Time
        ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
        formatted_time = ist_time.strftime("%d-%m-%Y %H:%M IST")

        # Extract first link
        links = re.findall(r'https?://[^\s"]+', email_text)
        job_link = links[0] if links else "Check Email"

        # Save to sheet
        sheet.append_row([
            unique_id,
            subject,
            job_link,
            score,
            formatted_time
        ])

        # Send Telegram
        message = (
            f"🚀 Job Alert\n\n"
            f"Role: {subject}\n"
            f"Score: {score}\n"
            f"Time: {formatted_time}\n"
            f"Link: {job_link}"
        )

        bot.send_message(chat_id=CHAT_ID, text=message)

    mail.logout()

# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    check_emails()
