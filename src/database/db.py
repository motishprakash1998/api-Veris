from src.database import Database

# Dependency to get database session
db_util = Database()

def get_db():
    db = db_util.get_session()
    try:
        yield db
    finally:
        db.close()