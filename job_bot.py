import os
import imaplib
import email
import requests
import PyPDF2
import gspread
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from email.header import decode_header
from google.oauth2.service_account import Credentials
from telegram import Bot

# ===============================
# LOAD ENV VARIABLES
# ===============================
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ===============================
# TELEGRAM
# ===============================
bot = Bot(token=TELEGRAM_TOKEN)

# ===============================
# GOOGLE SHEETS
# ===============================
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

# ===============================
# LOAD RESUME TEXT
# ===============================
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

resume_words = set(resume_text.split())

# ===============================
# SMART KEYWORD WEIGHT SYSTEM
# ===============================
IMPORTANT_KEYWORDS = {
    "python": 6,
    "django": 5,
    "flask": 4,
    "sql": 4,
    "machine learning": 6,
    "data": 4,
    "analysis": 4,
    "developer": 3,
    "engineer": 3,
    "pandas": 3,
    "numpy": 3,
    "api": 3,
    "backend": 4,
}

def calculate_score(job_text):
    if not job_text:
        return 0

    text = job_text.lower()
    score = 0

    # weighted keywords
    for keyword, weight in IMPORTANT_KEYWORDS.items():
        if keyword in text:
            score += weight

    # resume similarity bonus
    job_words = set(text.split())
    common = job_words.intersection(resume_words)

    score += min(len(common), 15)

    return score

# ===============================
# DECODE SUBJECT
# ===============================
def decode_subject(subject):
    decoded = decode_header(subject)
    text = ""
    for part, enc in decoded:
        if isinstance(part, bytes):
            text += part.decode(enc or "utf-8", errors="ignore")
        else:
            text += part
    return text

# ===============================
# EXTRACT LINKS
# ===============================
def extract_links(text):
    urls = re.findall(r'https?://[^\s"]+', text)
    clean = []

    for url in urls:
        lower = url.lower()

        if "unsubscribe" in lower:
            continue
        if "privacy" in lower:
            continue

        clean.append(url)

    return list(set(clean))

# ===============================
# RESOLVE REDIRECT
# ===============================
def resolve_redirect(url):
    try:
        response = requests.get(url, timeout=15, allow_redirects=True)
        return response.url
    except:
        return url

# ===============================
# FETCH JOB PAGE
# ===============================
def fetch_job_page(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else "Unknown Role"
        description = soup.get_text()

        return title, description
    except:
        return "Unknown Role", ""

# ===============================
# DUPLICATE CHECK
# ===============================
def is_duplicate(link):
    try:
        links = sheet.col_values(4)
        return link in links
    except:
        return False

# ===============================
# MAIN FUNCTION
# ===============================
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

        if not msg["subject"]:
            continue

        subject = decode_subject(msg["subject"])
        subject_lower = subject.lower()

        # Filter only job-related emails
        if not any(word in subject_lower for word in [
            "job", "hiring", "developer", "engineer", "python", "data"
        ]):
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

        links = extract_links(email_text)

        for link in links:
            final_url = resolve_redirect(link)

            if is_duplicate(final_url):
                continue

            title, description = fetch_job_page(final_url)

            score = calculate_score(description)

            if score < 12:   # Smart threshold
                continue

            ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
            time_str = ist_time.strftime("%d-%m-%Y %H:%M IST")

            sheet.append_row([
                "Smart Classified",
                title,
                "Job Link",
                final_url,
                score,
                time_str
            ])

            bot.send_message(
                chat_id=CHAT_ID,
                text=f"""🚀 Smart Job Alert

Role: {title}
Score: {score}
Time: {time_str}

Apply Here:
{final_url}
"""
            )

    mail.logout()


if __name__ == "__main__":
    check_emails()
