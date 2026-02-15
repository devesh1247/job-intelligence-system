import imaplib
import email
from email.header import decode_header
import os
import re
import requests
from datetime import datetime
import pytz

# ==============================
# ENV VARIABLES
# ==============================
EMAIL = os.environ.get("EMAIL")
PASSWORD = os.environ.get("PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ==============================
# SMART KEYWORDS (FREE SCORING)
# ==============================
KEYWORDS = {
    "python": 10,
    "django": 8,
    "flask": 8,
    "data analyst": 9,
    "machine learning": 10,
    "sql": 6,
    "pandas": 6,
    "developer": 5,
    "fresher": 5,
    "software engineer": 7
}

# ==============================
# TELEGRAM SEND
# ==============================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message
    }
    requests.post(url, data=data)

# ==============================
# DECODE SUBJECT CLEANLY
# ==============================
def decode_mime_words(s):
    decoded_words = decode_header(s)
    subject = ''
    for word, encoding in decoded_words:
        if isinstance(word, bytes):
            subject += word.decode(encoding if encoding else 'utf-8', errors='ignore')
        else:
            subject += word
    return subject

# ==============================
# SMART MATCH SCORING
# ==============================
def calculate_score(text):
    text = text.lower()
    score = 0
    for word, weight in KEYWORDS.items():
        if word in text:
            score += weight
    return score

# ==============================
# EXTRACT LINKS
# ==============================
def extract_links(text):
    return re.findall(r'https?://\S+', text)

# ==============================
# GET LATEST 5 UNREAD EMAILS
# ONLY SUBJECT CONTAINS "JOB"
# ==============================
def get_latest_unread_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")

    status, messages = mail.search(None, '(UNSEEN)')
    email_ids = messages[0].split()

    if not email_ids:
        print("No unread emails.")
        mail.logout()
        return []

    latest_5 = email_ids[-5:]
    emails_data = []

    for e_id in latest_5:
        res, msg = mail.fetch(e_id, "(RFC822)")
        for response in msg:
            if isinstance(response, tuple):
                msg_data = email.message_from_bytes(response[1])

                subject = decode_mime_words(msg_data["Subject"])

                # FILTER: Subject must contain "job"
                if "job" not in subject.lower():
                    continue

                body = ""

                if msg_data.is_multipart():
                    for part in msg_data.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                else:
                    body = msg_data.get_payload(decode=True).decode(errors="ignore")

                emails_data.append((subject, body))

        # Mark email as seen
        mail.store(e_id, '+FLAGS', '\\Seen')

    mail.logout()
    return emails_data

# ==============================
# MAIN LOGIC
# ==============================
def main():
    emails = get_latest_unread_emails()

    seen_roles = set()

    for subject, body in emails:
        full_text = subject + " " + body
        score = calculate_score(full_text)

        if score < 15:
            continue

        links = extract_links(body)
        link_text = links[0] if links else "No direct link found"

        if subject in seen_roles:
            continue

        seen_roles.add(subject)

        ist = pytz.timezone('Asia/Kolkata')
        time_now = datetime.now(ist).strftime("%d-%m-%Y %H:%M IST")

        message = f"""🚀 Job Alert Found

Role: {subject}
Match Score: {score}
Apply Link: {link_text}
Time: {time_now}
Source: Email"""

        send_telegram(message)

if __name__ == "__main__":
    main()
