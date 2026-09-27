from app.extensions import db
from app.models import Notification, User, StockManagerAssignment, ROLE_MAIN_ADMIN


def notify_user(user_id, title, message, link=None):
    n = Notification(user_id=user_id, title=title, message=message, link=link)
    db.session.add(n)
    return n


def notify_main_admins(title, message, link=None):
    admins = User.query.filter_by(role=ROLE_MAIN_ADMIN, is_active=True).all()
    for admin in admins:
        notify_user(admin.id, title, message, link)


def notify_location_managers(location_id, title, message, link=None):
    assignments = StockManagerAssignment.query.filter_by(location_id=location_id, is_active=True).all()
    for a in assignments:
        notify_user(a.user_id, title, message, link)
