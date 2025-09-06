# src/routers/__init__.py
from .employees.main import router as users_router
from .feedback.main import router as feedback_router
from .dashboard.main import  router as dashboard_route

__all__ = [
    "users_router",
    "feedback_router",
    "dashboard_route",
    
           ]
