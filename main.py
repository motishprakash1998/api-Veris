import uvicorn
from fastapi import FastAPI
from src.config import APPNAME, VERSION
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from src.routers import (users_router, 
                        feedback_router,election_services_router,admin_router,waiting_employees_router,
                        admin_dashboard_router,verification_routes)

# Defining the application
app = FastAPI(
    title=APPNAME,
    version=VERSION,
)

# Define allowed origins
origins = [
    "http://localhost:8081",  # Frontend during development
    "http://127.0.0.1:8081",  # Alternate localhost
    "http://localhost:5173",  # Frontend on port 5173
    "http://127.0.0.1:5173",  # Alternate localhost on port 5173
    "http://localhost:3000",  # Frontend on port 3000
    "http://127.0.0.1:3000",  # Alternate localhost on port 3000
    "https://*",              # Allow HTTPS for any origin
    "*"                       # Allow all other origins
]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # List of allowed origins
    allow_credentials=True, # Allow cookies and credentials
    allow_methods=["*"],    # Allow all HTTP methods
    allow_headers=["*"],    # Allow all headers
)

# Including all the routes for the 'users' module
app.include_router(users_router)
app.include_router(feedback_router)
app.include_router(election_services_router)
app.include_router(admin_router)
app.include_router(waiting_employees_router)
app.include_router(admin_dashboard_router)
app.include_router(verification_routes)

@app.get("/")
def main_function():
    """
    Redirect to documentation (`/docs/`).
    """
    return RedirectResponse(url="/docs/")

@app.post("/token")
def forward_to_login():
    """
    Redirect to token-generation (`/auth/token`). Used to make Auth in Swagger-UI work.
    """
    return RedirectResponse(url="/token")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5001)
