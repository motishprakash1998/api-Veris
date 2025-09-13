import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import os
from dotenv import load_dotenv 
from loguru import logger
load_dotenv()

SMTP_SERVER = os.getenv('SMTP_SERVER')   # Replace if using other provider
SMTP_PORT = os.getenv('SMTP_PORT')       # Usually 587 for TLS
SMTP_USERNAME = os.getenv('EMAIL')  
SMTP_PASSWORD = os.getenv('APP_PASSWORD')   
ORG_NAME = os.getenv('ORG_NAME')

HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Account Created</title>
    <style>
      /* Simple, inline-friendly styles */
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin:0; padding:0; background:#f5f7fa; }}
      .container {{ max-width:600px; margin:28px auto; background:#ffffff; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.08); overflow:hidden; }}
      .header {{ background:#0b5fff; color:#ffffff; padding:20px 24px; text-align:left; }}
      .header h1 {{ margin:0; font-size:20px; font-weight:600; }}
      .content {{ padding:24px; color:#0f1724; line-height:1.5; }}
      .btn {{ display:inline-block; margin-top:18px; padding:10px 16px; background:#0b5fff; color:#fff; text-decoration:none; border-radius:6px; }}
      .meta {{ margin-top:20px; font-size:13px; color:#6b7280; }}
      .footer {{ padding:16px 24px; font-size:13px; color:#6b7280; background:#fafafa; text-align:center; }}
      @media (max-width:420px) {{
        .container {{ margin:12px; }}
        .content {{ padding:16px; }}
      }}
    </style>
  </head>
  <body>
    <div class="container" role="article" aria-label="Account created">
      <div class="header">
        <h1>Account Created — Pending Approval</h1>
      </div>

      <div class="content">
        <p>Dear {full_name},</p>

        <p>
          We are pleased to inform you that your employee account has been successfully created.
          Your account is currently under review and is <strong>pending approval</strong> by our Administrator.
        </p>

        <p>
          Once approved, the Administrator will assign your <strong>State</strong> and
          <strong>Parliamentary Constituency</strong>. You will receive a notification when this process is complete.
        </p>

        <p class="meta">
          If you have any questions or require assistance, please reply to this email or contact your HR representative.
        </p>

        <a class="btn" href="mailto:{support_email}">Contact HR</a>

        <div style="margin-top:18px;">
          <small>Thank you for joining us.</small>
        </div>
      </div>

      <div class="footer">
        <div>{org_name}</div>
        <div style="margin-top:6px;">This is an automated message — please do not reply to this address.</div>
      </div>
    </div>
  </body>
</html>
"""

PLAIN_TEXT_TEMPLATE = """
Dear {full_name},

We are pleased to inform you that your employee account has been successfully created.
Your account is currently under review and is pending approval by our Administrator.

Once approved, the Administrator will assign your State and Parliamentary Constituency.
You will receive a notification when this process is complete.

If you have any questions, please reply to this email or contact your HR representative.

Thank you,
{org_name}
"""

def send_account_creation_email(to_email: str, full_name: str, support_email: str = SMTP_USERNAME, org_name: str = ORG_NAME):
    """
    Send professional HTML + plain-text email notifying the user that their account
    was created and is pending admin approval.
    """
    try:
        logger.info(f"[EMAIL TASK] Sending account creation email to {to_email} ({full_name})")

        subject = "Your Employee Account Has Been Created — Pending Approval"

        # build message
        msg = MIMEMultipart("alternative")
        msg["From"] = SMTP_USERNAME
        msg["To"] = to_email
        msg["Subject"] = subject

        # render templates
        html_body = HTML_TEMPLATE.format(full_name=full_name, support_email=support_email, org_name=org_name)
        text_body = PLAIN_TEXT_TEMPLATE.format(full_name=full_name, org_name=org_name)

        # attach parts
        part_text = MIMEText(text_body, "plain")
        part_html = MIMEText(html_body, "html")
        msg.attach(part_text)
        msg.attach(part_html)

        # send via SMTP
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)

        logging.info("Account creation email sent to %s", to_email)

    except Exception as exc:
        logging.exception("Failed to send account creation email to %s: %s", to_email, exc)