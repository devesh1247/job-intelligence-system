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
 
# ------------------ LOAD SECRETS ------------------
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ------------------ GOOGLE SHEETS SETUP ------------------
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

# ------------------ TELEGRAM BOT ------------------
bot = Bot(token=TELEGRAM_TOKEN)

# ------------------ RESUME EXTRACTION ------------------
def extract_resume_text():
    try:
        with open("resume.pdf", "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                content = page.extract_text()
                if content:
                    text += content
            return text.lower()
    except:
        return ""

resume_text = extract_resume_text()
resume_words = set(resume_text.split())

# ------------------ MATCH SCORE ------------------
def calculate_match(job_text):
    if not job_text or not resume_words:
        return 0, ""

    job_words = set(job_text.lower().split())
    common = job_words.intersection(resume_words)

    # Resume-based scoring (more realistic)
    score = int((len(common) / len(resume_words)) * 100)

    missing = list(resume_words - job_words)[:5]

    return score, ", ".join(missing)

# ------------------ EXTRACT JOB LINKS ------------------
def extract_job_links(text):
    urls = re.findall(r'https?://[^\s"]+', text)
    clean_links = []

    for url in urls:
        lower = url.lower()

        if "unsubscribe" in lower:
            continue

        if any(site in lower for site in [
            "linkedin.com",
            "indeed.com",
            "naukri.com",
            "foundit.in",
            "monster.com",
            "timesjobs.com",
            "google.com"
        ]):
            clean_links.append(url)

    return list(set(clean_links))

# ------------------ FETCH JOB PAGE ------------------
def fetch_job_details(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(url, headers=headers, timeout=15)

        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else "Unknown Role"

        paragraphs = soup.find_all("p")
        description = " ".join([p.get_text() for p in paragraphs])

        return title, description

    except:
        return "Unknown Role", ""

# ------------------ GMAIL CHECK ------------------
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

        subject = msg.get("subject", "")
        subject_lower = subject.lower()

        # Skip confirmation emails
        if "has been created" in subject_lower:
            continue

        # Extract body
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

        for link in job_links:
            role_title, job_description = fetch_job_details(link)
            score, missing = calculate_match(job_description)

            if score >= 15:   # realistic threshold
                relevant_jobs.append((role_title, link, score, missing))

        # -------- STEP 2: IF NO LINK MATCH → CHECK EMAIL TEXT --------
        if not relevant_jobs:
            score, missing = calculate_match(email_text)

            if score >= 15:
                relevant_jobs.append((
                    subject,
                    "From Email Content",
                    score,
                    missing
                ))

        if not relevant_jobs:
            continue

        # -------- TIME --------
        ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
        formatted_time = ist_time.strftime("%d-%m-%Y %H:%M IST")

        telegram_message = "🚀 Relevant Job Found\n\n"

        for role_title, link, score, missing in relevant_jobs:

            sheet.append_row([
                "Extracted",
                role_title,
                "Email or Link",
                link,
                score,
                missing,
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
        except:
            pass

    mail.logout()

# ------------------ RUN ------------------
if __name__ == "__main__":
    check_emails()
