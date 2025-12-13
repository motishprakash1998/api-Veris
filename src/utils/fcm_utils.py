import asyncio  
import firebase_admin
from datetime import  datetime
from firebase_admin import messaging, credentials
import  os
# Initialize Firebase Admin SDK (use your Firebase credentials JSON)
# FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS")
# cred = credentials.Certificate(FIREBASE_CREDENTIALS)
# firebase_admin.initialize_app(cred)

def send_push_notification(fcm_token: str, title: str, body: str):
    """
    Send a push notification to a single device.
    """
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=fcm_token
        )
        response = messaging.send(message)
        print(f"Push notification sent: {response}")
        return response
    except Exception as e:
        print(f"Failed to send push notification: {e}")
        return None

async def send_scheduled_notification(fcm_token: str, title: str, body: str, send_time: datetime):
    """
    Waits until the specified time and then sends a notification.
    """
    delay = (send_time - datetime.now()).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)  # Wait until the scheduled time
    send_push_notification(fcm_token, title, body)