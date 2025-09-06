# src/config.py
import os
from dotenv import load_dotenv
load_dotenv()

APPNAME = "Veris API"
VERSION = "v1"
SECRET_KEY = os.getenv("SECRET_KEY", "mysecretkey")  
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 
DB_USERNAME  = os.environ['DB_USERNAME']
DB_PASSWORD  = os.environ['DB_PASSWORD']
DB_HOST     = os.environ['DB_HOST']
DB_NAME     =  os.environ['DB_NAME']