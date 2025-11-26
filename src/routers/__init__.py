# src/routers/__init__.py
from .employees.main import router as users_router
from .feedback.main import router as feedback_router
from .dashboard.main import  router as dashboard_route
from .election_services.main import router as election_services_router
from .admin.employees.main import router as admin_router
from .admin.waiting_employees.main import router as waiting_employees_router
from .admin.dashboard.main import  router as admin_dashboard_router
from .election_services.verification.main import router as verification_routes
from .social_media.Instagram.main import  router as ig_router
from .users_dashboard.main import router as user_dashboard_route
from .social_media.facebook.main import router as fb_router
from .assembly.main import router as assembly_routers
from .social_media.x.login import router as x_router
from .user_management.main import router as user_management_router
__all__ = [
    "users_router",
    "feedback_router",
    "dashboard_route",
    "election_services_router",
    "admin_router",
    "waiting_employees_router",
    "admin_dashboard_router",
    "verification_routes",
    "ig_router",
    "user_dashboard_route",
    "fb_router",
    "assembly_routers",
    "x_router",
    "user_management_router"
           ]
