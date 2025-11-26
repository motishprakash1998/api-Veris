import os
import boto3
import smtplib
from typing import Optional
from jose import JWTError, jwt
from dotenv import load_dotenv
from urllib.parse import urlparse
from loguru import logger as logging
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from fastapi import HTTPException, status
from email.mime.multipart import MIMEMultipart
from botocore.exceptions import NoCredentialsError, ClientError, BotoCoreError
from botocore.client import Config

# Load environment variables
load_dotenv()

# ==============================
# Constants
# ==============================
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

EMAIL = os.getenv("EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("REGION_NAME")
S3_BUCKET_NAME = os.getenv("SOURCE_BUCKET_NAME")

# Initialize S3 Client
s3_client = boto3.client("s3", region_name=AWS_REGION)


# ============================================
# JWT TOKEN FUNCTIONS (USER VERSION)
# ============================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT token for authenticated users.
    """
    if not SECRET_KEY:
        logging.error("SECRET_KEY is missing in environment variables.")
        raise ValueError("SECRET_KEY is missing.")

    to_encode = data.copy()

    expire = datetime.utcnow() + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    logging.info("User access token created successfully.")
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """
    Decode and validate JWT user token.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logging.info("User token decoded successfully.")
        return payload

    except jwt.ExpiredSignatureError:
        logging.error("User token expired.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )

    except JWTError as e:
        logging.error(f"Invalid user token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )


# ============================================
# EMAIL (USER PASSWORD RESET)
# ============================================
def send_password_reset_email(email: str, token: str):
    """
    Send a password reset email with user reset link.
    """
    if not EMAIL or not APP_PASSWORD:
        logging.error("Email credentials missing.")
        raise ValueError("Email credentials missing.")

    reset_link = f"http://localhost:5001/reset-password?token={token}"
    subject = "User Password Reset Request"
    body = f"Click this link to reset your password:\n\n{reset_link}"

    msg = MIMEMultipart()
    msg["From"] = EMAIL
    msg["To"] = email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL, APP_PASSWORD)
            server.sendmail(EMAIL, email, msg.as_string())

        logging.info(f"Password reset email sent to user {email}")

    except Exception as e:
        logging.error(f"Email sending failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to send reset email. Try again later.",
        )


# ============================================
# S3 HELPERS (USER VERSION)
# ============================================
def s3_file_exists(profile_path: str) -> bool:
    """
    Check if a user's profile picture exists in S3.
    """
    try:
        parsed = urlparse(profile_path)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")

        if not bucket or not key:
            raise ValueError(f"Invalid S3 path: {profile_path}")

        s3 = boto3.client(
            "s3",
            region_name=AWS_REGION,
            config=Config(signature_version="s3v4"),
        )

        s3.head_object(Bucket=bucket, Key=key)
        logging.info(f"S3 file exists: {key}")
        return True

    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "404":
            return False
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"S3 error: {str(e)}",
        )

    except NoCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AWS credentials missing.",
        )

    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve),
        )

    except Exception as e:
        logging.error(f"Unexpected error checking S3: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected S3 error.",
        )


def generate_presigned_url(source_bucket: str, s3_image_path: str, expires_in: int = 7 * 24 * 60 * 60) -> str:
    """
    Generate pre-signed URL for user profile picture.
    """
    try:
        s3 = boto3.client(
            "s3",
            region_name=AWS_REGION,
            config=Config(signature_version="s3v4"),
        )

        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": source_bucket, "Key": s3_image_path},
            ExpiresIn=expires_in,
        )

        logging.info("Presigned URL generated successfully.")
        return url

    except (NoCredentialsError, ClientError, BotoCoreError) as e:
        logging.error(f"Failed to generate S3 URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate S3 presigned URL.",
        )
