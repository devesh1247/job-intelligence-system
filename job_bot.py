import os
import imaplib
import email
import requests
import PyPDF2
import gspread
import re
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from email.header import decode_header
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

creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
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
                page_text = page.extract_text()
                if page_text:
                    text += page_text
            return text.lower()
    except:
        return ""

resume_text = extract_resume_text()

# ==============================
# SMART KEYWORD WEIGHT SCORING
# ==============================
IMPORTANT_KEYWORDS = {
    "python": 5,
    "django": 4,
    "flask": 3,
    "sql": 3,
    "machine": 4,
    "learning": 4,
    "data": 4,
    "analysis": 3,
    "developer": 3,
    "engineer": 3,
    "pandas": 2,
    "numpy": 2,
}

def calculate_match(job_text):
    if not job_text:
        return 0

    text = job_text.lower()
    score = 0

    for keyword, weight in IMPORTANT_KEYWORDS.items():
        if keyword in text:
            score += weight

    # Bonus if many resume words match
    job_words = set(text.split())
    resume_words = set(resume_text.split())
    common = job_words.intersection(resume_words)

    score += min(len(common), 10)

    return score

# ==============================
# SUBJECT DECODER
# ==============================
def decode_subject(subject):
    decoded_parts = decode_header(subject)
    subject_text = ""

    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            subject_text += part.decode(encoding or "utf-8", errors="ignore")
        else:
            subject_text += part

    return subject_text

# ==============================
# EXTRACT JOB LINKS
# ==============================
def extract_links(text):
    urls = re.findall(r'https?://[^\s"]+', text)
    clean = []

    for url in urls:
        lower = url.lower()

        if "unsubscribe" in lower:
            continue

        if any(site in lower for site in [
            "linkedin.com",
            "indeed.com",
            "naukri.com",
            "foundit",
            "monster",
            "timesjobs",
            "google.com"
        ]):
            clean.append(url)

    return list(set(clean))

# ==============================
# FETCH JOB PAGE
# ==============================
def fetch_job(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else "Unknown Role"
        paragraphs = soup.find_all("p")
        description = " ".join(p.get_text() for p in paragraphs)

        return title, description
    except:
        return "Unknown Role", ""

# ==============================
# DUPLICATE CHECK
# ==============================
def is_duplicate(link):
    try:
        records = sheet.col_values(4)  # link column
        return link in records
    except:
        return False

# ==============================
# MAIN EMAIL CHECKER
# ==============================
def check_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    result, data = mail.search(None, '(UNSEEN)')
    mail_ids = data[0].split()[-10:]

    for num in mail_ids:
        result, msg_data = mail.fetch(num, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        raw_subject = msg["subject"]
        if not raw_subject:
            continue

        subject = decode_subject(raw_subject)
        subject_lower = subject.lower()

        # FILTER NON JOB EMAILS
        if not any(word in subject_lower for word in [
            "job", "hiring", "developer", "engineer", "python", "data"
        ]):
            continue

        # SKIP SUMMARY ALERTS
        if "new jobs for" in subject_lower:
            continue

        # EXTRACT BODY
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode(errors="ignore")
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        soup = BeautifulSoup(body, "html.parser")
        email_text = soup.get_text()

        links = extract_links(email_text)
        found_relevant = False

        # =========================
        # CHECK ALL LINKS
        # =========================
        for link in links:
            if is_duplicate(link):
                continue

            title, description = fetch_job(link)
            score = calculate_match(description)

            if score >= 8:   # Smart threshold
                found_relevant = True

                ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
                time_str = ist_time.strftime("%d-%m-%Y %H:%M IST")

                sheet.append_row([
                    "Extracted",
                    title,
                    "Link",
                    link,
                    score,
                    time_str
                ])

                bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🚀 Job Alert Found\n\nRole: {title}\nMatch Score: {score}\nTime: {time_str}\nLink: {link}"
                )

        # =========================
        # FALLBACK TO EMAIL TEXT
        # =========================
        if not links:
            score = calculate_match(email_text)

            if score >= 10:
                ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
                time_str = ist_time.strftime("%d-%m-%Y %H:%M IST")

                bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🚀 Job Alert Found\n\nRole: {subject}\nMatch Score: {score}\nTime: {time_str}\nSource: Email Content"
                )

    mail.logout()


if __name__ == "__main__":
    check_emails()
