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

# Constants
SECRET_KEY = os.getenv('SECRET_KEY')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
EMAIL = os.getenv('EMAIL')
APP_PASSWORD = os.getenv('APP_PASSWORD')

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("REGION_NAME")  # change as needed
S3_BUCKET_NAME = os.getenv("SOURCE_BUCKET_NAME")

# Initialize S3 Client
s3_client = boto3.client("s3", region_name=AWS_REGION)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token with an optional expiration time.
    """
    if not SECRET_KEY:
        logging.error("SECRET_KEY is not set in the environment variables.")
        raise ValueError("SECRET_KEY is missing.")

    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    logging.info("Access token successfully created.")
    logging.debug(f"Token payload: {to_encode}")
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """
    Decode a JWT access token and verify its signature.
    """
    logging.error(f"TOKEN ::{token}")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logging.info("Access token successfully decoded.")
        logging.debug(f"Decoded token payload: {payload}")
        return payload
    except jwt.ExpiredSignatureError:
        logging.error("Token has expired.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        logging.error(f"Invalid token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def send_password_reset_email(email: str, token: str):
    """
    Send a password reset email with a reset link containing the token.
    """
    if not EMAIL or not APP_PASSWORD:
        logging.error("EMAIL or APP_PASSWORD is not set in the environment variables.")
        raise ValueError("Email credentials are missing.")

    reset_link = f"http://localhost:5001?token={token}"
    subject = "Password Reset Request"
    body = f"Click the following link to reset your password: {reset_link}"

    msg = MIMEMultipart()
    msg['From'] = EMAIL
    msg['To'] = email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Start TLS encryption
            server.login(EMAIL, APP_PASSWORD)
            server.sendmail(EMAIL, email, msg.as_string())
        logging.info(f"Password reset email sent successfully to {email}.")
    except Exception as e:
        logging.error(f"Failed to send password reset email to {email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send email. Please try again later.",
        )


def s3_file_exists(profile_path: str) -> bool:
    """
    Check if the given profile path exists in the specified S3 bucket.

    Args:
        profile_path (str): Full S3 URI of the file, e.g., "s3://bucket_name/key_name".

    Returns:
        bool: True if the file exists, False otherwise.

    Raises:
        HTTPException: If AWS credentials are missing or another unexpected error occurs.
    """
    try:
        # Parse the S3 URI
        parsed_url = urlparse(profile_path)
        bucket_name = parsed_url.netloc
        key_name = parsed_url.path.lstrip("/")

        if not bucket_name or not key_name:
            raise ValueError(f"Invalid S3 path: {profile_path}")

        # Initialize S3 client with Signature v4
        s3_client = boto3.client(
            "s3",
            region_name=AWS_REGION,
            config=Config(signature_version="s3v4")
        )

        # Check if the file exists
        s3_client.head_object(Bucket=bucket_name, Key=key_name)
        logging.info(f"File '{key_name}' exists in S3 bucket '{bucket_name}'.")
        return True

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "404":
            logging.warning(f"File '{profile_path}' does not exist in S3 bucket '{bucket_name}'.")
            return False
        logging.error(f"Unexpected S3 ClientError: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected S3 error: {e}",
        )

    except NoCredentialsError:
        logging.error("AWS credentials not available.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="S3 credentials issue. Please contact the administrator.",
        )

    except ValueError as ve:
        logging.error(str(ve))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve),
        )

    except Exception as e:
        logging.exception(f"Unexpected error checking S3 file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred while checking S3 file.",
        )


def generate_presigned_url(source_bucket: str, s3_image_path: str, expires_in: int = 7*24*60*60) -> str:
    """
    Generate a pre-signed URL for accessing an S3 object.

    Args:
        source_bucket (str): S3 bucket name
        s3_image_path (str): Path/key of the object in S3
        expires_in (int): Expiration in seconds (default 7 days)

    Returns:
        str: Pre-signed URL

    Raises:
        HTTPException: On failure to generate the URL
    """
    try:
        s3_client = boto3.client(
            "s3",
            region_name=AWS_REGION,
            config=Config(signature_version="s3v4")
        )

        url = s3_client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': source_bucket, 'Key': s3_image_path},
            ExpiresIn=expires_in
        )

        logging.info(f"Generated presigned URL for '{s3_image_path}' in bucket '{source_bucket}'.")
        return url

    except (NoCredentialsError, ClientError, BotoCoreError) as e:
        logging.error(f"Error generating pre-signed URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate pre-signed URL. Please check AWS credentials and bucket configuration."
        )
