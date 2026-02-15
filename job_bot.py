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
    try:
        with open("resume.pdf", "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                if page.extract_text():
                    text += page.extract_text()
            return text.lower()
    except Exception as e:
        print(f"Error reading resume: {e}")
        return ""

resume_text = extract_resume_text()

# --- Match Score ---
def calculate_match(job_text):
    if not job_text:
        return 0, ""
        
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

        if "unsubscribe" in url_lower:
            continue

        # Allow Google job links
        if "google.com" in url_lower:
            clean_links.append(url)
            continue

        if any(site in url_lower for site in [
            "linkedin.com",
            "indeed.com",
            "naukri.com",
            "foundit.in",
            "monster.com",
            "timesjobs.com"
        ]):
            clean_links.append(url)

    return list(set(clean_links))

# --- Fetch Job Page ---
def fetch_job_details(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else "Unknown Role"
        paragraphs = soup.find_all("p")
        description = " ".join([p.get_text() for p in paragraphs])

        return title, description

    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return "Unknown Role", ""

# --- Gmail Reader ---
def check_emails():
    print("Connecting to Gmail...")
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

        # --- DEBUG PRINTS ---
        print("----- EMAIL SUBJECT -----")
        print(subject)
        print("----- EMAIL TEXT PREVIEW -----")
        print(email_text[:500])

        relevant_jobs = []

        # ---------- STEP 1: CHECK ALL LINKS ----------
        job_links = extract_job_links(email_text)
        print("Extracted Links:", job_links)

        for link in job_links:
            print("Checking link:", link)
            role_title, job_description = fetch_job_details(link)
            score, missing = calculate_match(job_description)
            print("Score:", score)

            if score >= 30:
                relevant_jobs.append((role_title, link, score, missing))

        # ---------- STEP 2: IF NO MATCH FROM LINKS → CHECK EMAIL TEXT ----------
        if not relevant_jobs:
            print("No links matched. Checking direct email text...")
            score, missing = calculate_match(email_text)
            print("Email Content Score:", score)

            if score >= 30:
                relevant_jobs.append((
                    subject,
                    "From Email Content",
                    score,
                    missing
                ))

        # If still nothing relevant → skip
        if not relevant_jobs:
            print("No relevant jobs found in this email.")
            continue

        # --- Convert UTC to IST ---
        ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
        formatted_time = ist_time.strftime("%d-%m-%Y %H:%M IST")

        telegram_message = "🚀 High Match Job Found\n\n"

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
        except Exception as e:
            print(f"Telegram error: {e}")

    mail.logout()
    print("Finished checking emails.")

if __name__ == "__main__":
    check_emails()
