from functools import wraps
from flask import abort
from flask_login import current_user
from app.models import ROLE_MAIN_ADMIN, ROLE_STOCK_MANAGER, ROLE_EMPLOYEE


def roles_required(*roles):
    """Restrict a route to specific roles. Main Admin is NOT implicitly included unless listed."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def admin_required(fn):
    return roles_required(ROLE_MAIN_ADMIN)(fn)


def can_access_location(user, location_id):
    """Server-side authority check. NEVER trust a location_id from the client without this."""
    if user.role == ROLE_MAIN_ADMIN:
        return True
    return location_id in user.authorized_location_ids()


def require_location_access(location_id):
    if not can_access_location(current_user, location_id):
        abort(403, description="You are not authorized for this location.")


def accessible_location_ids(user):
    """None means 'all locations' (Main Admin). Otherwise a list of allowed IDs."""
    if user.role == ROLE_MAIN_ADMIN:
        return None
    return user.authorized_location_ids()
