import os
import imaplib
import email
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from telegram import Bot
from email.header import decode_header

# ==============================
# ENV VARIABLES
# ==============================

EMAIL_ID = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = Bot(token=TELEGRAM_TOKEN)

# ==============================
# CONFIG
# ==============================

SEARCH_KEYWORDS = [
    "job", "hiring", "career", "vacancy",
    "opportunity", "position", "opening"
]

TARGET_SKILLS = {
    "python": 10,
    "django": 8,
    "flask": 6,
    "data": 7,
    "analysis": 7,
    "machine learning": 9,
    "sql": 8,
    "developer": 6,
    "engineer": 5,
    "ai": 9,
}

processed_links = set()

# ==============================
# DECODE SUBJECT PROPERLY
# ==============================

def decode_subject(subject):
    decoded_parts = decode_header(subject)
    final_subject = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            final_subject += part.decode(encoding or "utf-8", errors="ignore")
        else:
            final_subject += part
    return final_subject

# ==============================
# SMART SCORING SYSTEM
# ==============================

def calculate_score(text):
    score = 0
    text_lower = text.lower()

    for skill, weight in TARGET_SKILLS.items():
        if skill in text_lower:
            score += weight

    return score

# ==============================
# EXTRACT LINKS FROM HTML
# ==============================

def extract_links_from_html(html_body):
    soup = BeautifulSoup(html_body, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        url = a["href"]

        if any(x in url.lower() for x in ["unsubscribe", "privacy", "track"]):
            continue

        if url.startswith("http"):
            links.append(url)

    return list(set(links))

# ==============================
# RESOLVE REDIRECT LINKS
# ==============================

def resolve_link(url):
    try:
        session = requests.Session()
        response = session.get(url, allow_redirects=True, timeout=10)
        return response.url
    except:
        return None

# ==============================
# CHECK EMAILS
# ==============================

def check_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_ID, PASSWORD)
    mail.select("inbox")

    # Only unread emails
    result, data = mail.search(None, '(UNSEEN)')
    mail_ids = data[0].split()[-5:]  # Only last 5 unread

    for num in mail_ids:
        result, msg_data = mail.fetch(num, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg["subject"]
        if not subject:
            continue

        subject = decode_subject(subject)
        subject_lower = subject.lower()

        # Check job keywords in subject
        if not any(keyword in subject_lower for keyword in SEARCH_KEYWORDS):
            continue

        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode(errors="ignore")
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        if not body:
            continue

        soup = BeautifulSoup(body, "html.parser")
        email_text = soup.get_text()

        score = calculate_score(email_text)

        if score < 15:
            continue

        # Extract links
        links = extract_links_from_html(body)

        apply_link = None

        for link in links:
            final_url = resolve_link(link)
            if final_url and final_url not in processed_links:
                processed_links.add(final_url)
                apply_link = final_url
                break

        if not apply_link:
            apply_link = "No Direct Apply Link Found"

        # Convert to IST
        ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
        formatted_time = ist_time.strftime("%d-%m-%Y %H:%M IST")

        message = (
            f"🚀 Job Alert Found\n\n"
            f"Role: {subject}\n"
            f"Match Score: {score}\n"
            f"Time: {formatted_time}\n"
            f"Apply Link: {apply_link}"
        )

        try:
            bot.send_message(chat_id=CHAT_ID, text=message)
        except Exception as e:
            print("Telegram Error:", e)

    mail.logout()

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    check_emails()
