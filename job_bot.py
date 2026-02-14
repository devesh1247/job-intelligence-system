import os
import imaplib
import email
import requests
import pandas as pd
import PyPDF2
import gspread
from datetime import datetime
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from telegram import Bot

# --- Load Secrets ---
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# --- Google Sheets Setup ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open("Job Tracker").sheet1

# --- Telegram Bot ---
bot = Bot(token=TELEGRAM_TOKEN)

# --- Resume Text Extraction ---
def extract_resume_text():
    with open("resume.pdf", "rb") as f:
        reader = PyPDF2.PdfReader(f)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return text.lower()

resume_text = extract_resume_text()

# --- Match Score Function ---
def calculate_match(job_text):
    job_words = set(job_text.lower().split())
    resume_words = set(resume_text.split())
    common = job_words.intersection(resume_words)
    score = int((len(common) / len(job_words)) * 100) if len(job_words) > 0 else 0
    missing = list(job_words - resume_words)[:5]
    return score, ", ".join(missing)

# --- Gmail Reader ---
def check_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    result, data = mail.search(None, '(UNSEEN SUBJECT "Job Alert")')
    mail_ids = data[0].split()

    for num in mail_ids:
        result, msg_data = mail.fetch(num, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg["subject"]
        date = msg["date"]

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode()
        else:
            body = msg.get_payload(decode=True).decode()

        soup = BeautifulSoup(body, "html.parser")
        text = soup.get_text()

        score, missing = calculate_match(text)

        sheet.append_row([
            "Unknown Company",
            subject,
            "Email Alert",
            "Check Email",
            score,
            missing,
            str(datetime.now())
        ])

        bot.send_message(
            chat_id=CHAT_ID,
            text=f"🚀 New Job Alert\n\nRole: {subject}\nMatch Score: {score}%\nMissing: {missing}"
        )

    mail.logout()

check_emails()
