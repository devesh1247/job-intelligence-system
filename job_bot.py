import os
import imaplib
import email
import requests
import PyPDF2
import gspread
import re
from datetime import datetime, timedelta
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
    "service_account.json", scopes=SCOPES
)
client = gspread.authorize(creds)
sheet = client.open("Job Tracker").sheet1

# ==============================
# TELEGRAM BOT
# ==============================

bot = Bot(token=TELEGRAM_TOKEN)

# ==============================
# EXTRACT RESUME TEXT
# ==============================

def extract_resume_text():
    try:
        with open("resume.pdf", "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                if page.extract_text():
                    text += page.extract_text()
            print("Resume loaded successfully.")
            return text.lower()
    except Exception as e:
        print("Resume read error:", e)
        return ""

resume_text = extract_resume_text()

# ==============================
# MATCH SCORE
# ==============================

def calculate_match(job_text):
    if not job_text:
        return 0

    job_words = set(job_text.lower().split())
    resume_words = set(resume_text.split())

    if not job_words:
        return 0

    common = job_words.intersection(resume_words)
    score = int((len(common) / len(job_words)) * 100)

    return score

# ==============================
# EXTRACT JOB LINKS
# ==============================

def extract_job_links(text):
    urls = re.findall(r'https?://[^\s"]+', text)
    clean_links = []

    for url in urls:
        url_lower = url.lower()

        if "unsubscribe" in url_lower:
            continue

        if any(site in url_lower for site in [
            "linkedin.com",
            "indeed.com",
            "naukri.com",
            "foundit",
            "monster",
            "timesjobs",
            "google.com"
        ]):
            clean_links.append(url)

    return list(set(clean_links))

# ==============================
# FETCH JOB PAGE
# ==============================

def fetch_job_details(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else "Unknown Role"
        paragraphs = soup.find_all("p")
        description = " ".join([p.get_text() for p in paragraphs])

        return title, description
    except Exception as e:
        print("Error fetching job page:", e)
        return "Unknown Role", ""

# ==============================
# MAIN EMAIL CHECK
# ==============================

def check_emails():
    print("Connecting to Gmail...")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    # ✅ CHECK LAST 2 DAYS EMAILS (NOT UNSEEN)
    date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
    result, data = mail.search(None, f'(SINCE "{date}")')

    mail_ids = data[0].split()

    print("Emails found:", len(mail_ids))

    for num in mail_ids[-10:]:
        result, msg_data = mail.fetch(num, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg["subject"]
        if not subject:
            continue

        subject_lower = subject.lower()

        if "has been created" in subject_lower:
            continue

        print("\nChecking email:", subject)

        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode(errors="ignore")
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        soup = BeautifulSoup(body, "html.parser")
        email_text = soup.get_text()

        relevant_jobs = []

        # -------- STEP 1: CHECK LINKS --------
        job_links = extract_job_links(email_text)
        print("Links found:", len(job_links))

        for link in job_links:
            title, description = fetch_job_details(link)
            score = calculate_match(description)

            print("Role:", title)
            print("Score:", score)

            # ⚠ TEMPORARY FOR TESTING → always notify
            if score >= 0:
                relevant_jobs.append((title, link, score))

        # -------- STEP 2: CHECK EMAIL TEXT DIRECTLY --------
        if not relevant_jobs:
            score = calculate_match(email_text)
            print("Email Content Score:", score)

            if score >= 0:
                relevant_jobs.append((subject, "From Email Content", score))

        # -------- SEND TELEGRAM --------
        if relevant_jobs:
            ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
            formatted_time = ist_time.strftime("%d-%m-%Y %H:%M IST")

            telegram_message = "🚀 Job Alert Found\n\n"

            for role_title, link, score in relevant_jobs:

                sheet.append_row([
                    "Extracted",
                    role_title,
                    link,
                    score,
                    formatted_time
                ])

                telegram_message += (
                    f"Role: {role_title}\n"
                    f"Match: {score}%\n"
                    f"Source: {link}\n\n"
                )

            try:
                bot.send_message(
                    chat_id=CHAT_ID,
                    text=telegram_message
                )
                print("Telegram notification sent.")
            except Exception as e:
                print("Telegram error:", e)

    mail.logout()
    print("Finished checking emails.")

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    check_emails()
