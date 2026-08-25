import os
import re
import json
import ssl
import smtplib
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# The 3 FPSC pages to track
PAGES = {
    "New Job Advertisements (GR)": "https://www.fpsc.gov.pk/Jobs?section=GR",
    "Job Syllabuses (GR)": "https://www.fpsc.gov.pk/Syllabuses?section=GR%20Syllabus",
    "Job Nominations": "https://www.fpsc.gov.pk/Results?section=Nominations"
}

STATE_FILE = "seen_items.json"

# Bypass SSL verification issues commonly found on government portal certificates
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

def clean_url(url: str) -> str:
    url = url.replace('\\', '').strip('\"\'')
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        return 'https://www.fpsc.gov.pk' + url
    return url

def fetch_page_items(url: str):
    """Scrapes PDF links and document titles from the FPSC page."""
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as response:
            html = response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error loading {url}: {e}")
        return []

    items = []
    found_urls = set()

    # Match all PDF links in HTML and Next.js server payload
    matches = re.findall(r'href=[\"\']([^\"\']+\.pdf[^\"\']*)[\"\']', html, re.IGNORECASE)
    matches += re.findall(r'(\/(?:uploads\/content|gr_one)[a-zA-Z0-9_\-\.\/]+\.pdf)', html, re.IGNORECASE)
    matches += re.findall(r'(https?:\/\/[^\s\"\'<>]+\.pdf)', html, re.IGNORECASE)

    for raw_link in matches:
        full_url = clean_url(raw_link)
        if full_url in found_urls:
            continue
        found_urls.add(full_url)

        filename = full_url.split('/')[-1]
        # Clean title by removing numeric prefixes and extensions
        clean_title = re.sub(r'^\d+_', '', filename)
        clean_title = clean_title.replace('.pdf', '').replace('_', ' ').replace('-', ' ').strip()

        items.append({
            "title": clean_title,
            "url": full_url,
            "filename": filename
        })

    return items

def send_email_alert(category: str, title: str, url: str):
    sender_email = os.environ.get("EMAIL_SENDER")
    sender_password = os.environ.get("EMAIL_PASSWORD")
    receiver_email = os.environ.get("EMAIL_RECEIVER")

    if not sender_email or not sender_password or not receiver_email:
        print("Email configuration missing. Skipping email alert.")
        return

    subject = f"🚨 FPSC Alert: New Upload in {category}"
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 20px; background-color: #f4f6f8;">
        <div style="max-width: 600px; margin: auto; background-color: #ffffff; padding: 24px; border: 1px solid #dcdfe4; border-radius: 8px;">
          <h2 style="color: #0A3C30; border-bottom: 2px solid #0A3C30; padding-bottom: 8px; margin-top: 0;">
            FPSC New Upload Alert
          </h2>
          <p>A new document has been posted on the FPSC website:</p>
          <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr>
              <td style="font-weight: bold; padding: 8px 0; width: 120px; color: #555;">Category:</td>
              <td style="padding: 8px 0; font-weight: 600;">{category}</td>
            </tr>
            <tr>
              <td style="font-weight: bold; padding: 8px 0; color: #555;">Title:</td>
              <td style="padding: 8px 0;">{title}</td>
            </tr>
          </table>
          <div style="margin-top: 25px; margin-bottom: 15px;">
            <a href="{url}" style="background-color: #0A3C30; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
              📄 View / Download PDF
            </a>
          </div>
          <p style="font-size: 12px; color: #888; margin-top: 30px; border-top: 1px solid #eee; padding-top: 10px;">
            This is an automated 24/7 alert from your FPSC GitHub Actions Monitor.
          </p>
        </div>
      </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"FPSC Monitor <{sender_email}>"
    msg["To"] = receiver_email
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print(f"Email alert successfully sent for: {title}")
    except Exception as e:
        print(f"Failed to send email alert: {e}")

def main():
    # Load previously seen items
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                seen_data = json.load(f)
            except Exception:
                seen_data = {}
    else:
        seen_data = {}

    is_first_run = len(seen_data) == 0
    new_found = False

    for category, page_url in PAGES.items():
        print(f"Checking: {category}...")
        current_items = fetch_page_items(page_url)
        known_links = set(seen_data.get(category, []))

        for item in current_items:
            link = item["url"]
            if link not in known_links:
                known_links.add(link)
                new_found = True

                if is_first_run:
                    print(f"Initial discovery: [{item['title']}]({link})")
                else:
                    print(f"🚨 NEW ITEM DETECTED: {item['title']}")
                    send_email_alert(category, item['title'], link)

        seen_data[category] = list(known_links)

    # Save current state
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_data, f, indent=2)

    if is_first_run:
        print("First run complete. Current existing items memorized. Future runs will alert on new uploads.")
    elif new_found:
        print("New updates were found and alerts were dispatched.")
    else:
        print("No new uploads detected.")

if __name__ == "__main__":
    main()
