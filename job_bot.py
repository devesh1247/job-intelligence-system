import os
import imaplib
import email
import requests
import PyPDF2
import gspread
import re
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup
from email.header import decode_header
from google.oauth2.service_account import Credentials
from telegram import Bot

# ===============================
# 🔐 LOAD ENV VARIABLES
# ===============================
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ===============================
# 📊 GOOGLE SHEETS SETUP
# ===============================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open("Job Tracker").sheet1

# ===============================
# 🤖 TELEGRAM BOT
# ===============================
bot = Bot(token=TELEGRAM_TOKEN)

# ===============================
# 🧠 JOB TRIGGER WORDS
# ===============================
JOB_TRIGGER_WORDS = [
    "job", "hiring", "opening", "opportunity",
    "vacancy", "career", "position",
    "walk-in", "recruitment", "apply", "urgent"
]

# ===============================
# 🎯 SKILL WEIGHT SYSTEM (FREE AI)
# ===============================
SKILL_WEIGHTS = {
    "python": 10,
    "django": 8,
    "flask": 8,
    "sql": 7,
    "data": 7,
    "machine learning": 9,
    "ai": 9,
    "analysis": 7,
    "pandas": 6,
    "numpy": 6,
    "developer": 5,
    "engineer": 5
}

# ===============================
# 📄 RESUME TEXT EXTRACTION
# ===============================
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

# ===============================
# 🔥 SMART MATCH SCORE
# ===============================
def calculate_match(text):
    text = text.lower()
    score = 0
    for skill, weight in SKILL_WEIGHTS.items():
        if skill in text:
            score += weight
    return score

# ===============================
# 🔗 EXTRACT JOB LINKS
# ===============================
def extract_links(text):
    urls = re.findall(r'https?://[^\s"]+', text)
    clean = []
    for url in urls:
        if "unsubscribe" in url.lower():
            continue
        clean.append(url)
    return list(set(clean))

# ===============================
# 🔁 FOLLOW REDIRECT LINKS
# ===============================
def resolve_link(url):
    try:
        r = requests.get(url, allow_redirects=True, timeout=10)
        return r.url
    except:
        return url

# ===============================
# 🧾 FETCH JOB DETAILS
# ===============================
def fetch_job_details(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title else "Job Opportunity"
        description = soup.get_text()
        return title, description
    except:
        return "Job Opportunity", ""

# ===============================
# 🧠 DECODE SUBJECT
# ===============================
def decode_subject(subject):
    decoded_parts = decode_header(subject)
    subject_decoded = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            subject_decoded += part.decode(encoding or "utf-8", errors="ignore")
        else:
            subject_decoded += part
    return subject_decoded

# ===============================
# 🚀 MAIN EMAIL CHECKER
# ===============================
def check_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    result, data = mail.search(None, '(UNSEEN)')
    mail_ids = data[0].split()[-5:]  # only last 5 unread

    for num in mail_ids:
        result, msg_data = mail.fetch(num, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg["subject"]
        if not subject:
            continue

        subject = decode_subject(subject)
        subject_lower = subject.lower()

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode(errors="ignore")
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        soup = BeautifulSoup(body, "html.parser")
        email_text = soup.get_text()

        # 🔎 Filter only job related emails
        combined_text = (subject + " " + email_text).lower()
        if not any(word in combined_text for word in JOB_TRIGGER_WORDS):
            continue

        links = extract_links(email_text)
        best_match_score = 0
        best_title = subject
        best_link = None

        for link in links:
            final_link = resolve_link(link)
            title, description = fetch_job_details(final_link)
            score = calculate_match(description)

            if score > best_match_score:
                best_match_score = score
                best_title = title
                best_link = final_link

        # fallback scoring from email body
        if best_match_score == 0:
            best_match_score = calculate_match(email_text)

        # minimum threshold
        if best_match_score < 15:
            continue

        # Remove duplicate using hash
        unique_id = hashlib.md5((best_title + str(best_link)).encode()).hexdigest()
        existing_ids = sheet.col_values(8)
        if unique_id in existing_ids:
            continue

        # IST Time
        now = datetime.now().strftime("%d-%m-%Y %H:%M IST")

        sheet.append_row([
            "Extracted",
            best_title,
            best_link or "Email Content",
            best_match_score,
            now,
            unique_id
        ])

        message = f"""🚀 Job Alert Found

Role: {best_title}
Match Score: {best_match_score}
Time: {now}
Apply Link: {best_link if best_link else "Check Email"}"""

        bot.send_message(chat_id=CHAT_ID, text=message)

    mail.logout()

# ===============================
# ▶ RUN
# ===============================
if __name__ == "__main__":
    check_emails()
