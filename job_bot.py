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

# --- Extract ALL Job Links ---
def extract_job_links(text):
    urls = re.findall(r'https?://[^\s"]+', text)
    clean_links = []

    for url in urls:
        url_lower = url.lower()

        # Skip unsubscribe and tracking links
        if "unsubscribe" in url_lower:
            continue
        if "google.com" in url_lower and "jobs" not in url_lower:
            continue

        # Keep common job platforms
        if any(site in url_lower for site in [
            "linkedin.com",
            "indeed.com",
            "naukri.com",
            "foundit.in",
            "monster.com",
            "timesjobs.com"
        ]):
            clean_links.append(url)

    # Remove duplicates
    return list(set(clean_links))

# --- Fetch Job Page ---
def fetch_job_details(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else "Unknown Role"
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

        # Skip alert creation emails
        if "has been created" in subject_lower:
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

        # --- Extract ALL job links ---
        job_links = extract_job_links(email_text)

        if not job_links:
            continue

        relevant_jobs = []

        for link in job_links:
            role_title, job_description = fetch_job_details(link)
            score, missing = calculate_match(job_description)

            # Only notify if strong match
            if score >= 30:   # Adjust threshold if needed
                relevant_jobs.append((role_title, link, score, missing))

        # If no relevant jobs → skip email
        if not relevant_jobs:
            continue

        # --- Convert UTC to IST ---
        ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
        formatted_time = ist_time.strftime("%d-%m-%Y %H:%M IST")

        telegram_message = "🚀 High Match Jobs Found\n\n"

        for role_title, link, score, missing in relevant_jobs:

            sheet.append_row([
                "Extracted",
                role_title,
                "Email Link",
                link,
                score,
                missing,
                formatted_time
            ])

            telegram_message += (
                f"Role: {role_title}\n"
                f"Match: {score}%\n"
                f"Link: {link}\n\n"
            )

        bot.send_message(
            chat_id=CHAT_ID,
            text=telegram_message
        )

    mail.logout()

check_emails()
