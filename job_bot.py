import os
import imaplib
import email
import requests
import PyPDF2
import gspread
import re
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
            if page.extract_text():
                text += page.extract_text()
        return text.lower()

resume_text = extract_resume_text()

# --- Match Score ---
def calculate_match(job_text):
    job_words = set(job_text.lower().split())
    resume_words = set(resume_text.split())

    if len(job_words) == 0:
        return 0, ""

    common = job_words.intersection(resume_words)
    score = int((len(common) / len(job_words)) * 100)
    missing = list(job_words - resume_words)[:5]

    return score, ", ".join(missing)

# --- Extract First URL From Email ---
def extract_job_link(text):
    urls = re.findall(r'https?://\S+', text)
    if urls:
        return urls[0]
    return None

# --- Fetch Job Page ---
def fetch_job_details(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string if soup.title else "Unknown Role"

        # Try to extract meaningful text
        paragraphs = soup.find_all("p")
        description = " ".join([p.get_text() for p in paragraphs])

        return title, description

    except:
        return "Unknown Role", ""

# --- Gmail Reader ---
def check_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    result, data = mail.search(None, '(UNSEEN)')
    mail_ids = data[0].split()[-5:]

    for num in mail_ids:
        result, msg_data = mail.fetch(num, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg["subject"]
        if subject is None:
            continue

        subject_lower = subject.lower()

        if "job" not in subject_lower:
            continue

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode(errors="ignore")
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        soup = BeautifulSoup(body, "html.parser")
        email_text = soup.get_text()

        job_link = extract_job_link(email_text)

        if not job_link:
            continue

        role_title, job_description = fetch_job_details(job_link)

        score, missing = calculate_match(job_description)

        sheet.append_row([
            "Extracted",
            role_title,
            "Email Link",
            job_link,
            score,
            missing,
            str(datetime.now())
        ])

        bot.send_message(
            chat_id=CHAT_ID,
            text=f"🚀 New Job Found\n\nRole: {role_title}\nMatch: {score}%\nLink: {job_link}"
        )

    mail.logout()

check_emails()
