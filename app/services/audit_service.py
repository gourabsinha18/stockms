from flask import request
from flask_login import current_user
from app.extensions import db
from app.models import AuditLog


def log_action(action, entity, entity_id=None, previous_value=None, new_value=None, user=None):
    """Write an immutable audit record. Never edit or delete AuditLog rows elsewhere."""
    uid = None
    if user is not None:
        uid = user.id
    elif current_user and getattr(current_user, "is_authenticated", False):
        uid = current_user.id

    ip = None
    try:
        ip = request.remote_addr
    except RuntimeError:
        ip = None

    entry = AuditLog(
        user_id=uid,
        action=action,
        entity=entity,
        entity_id=entity_id,
        previous_value=str(previous_value) if previous_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        ip_address=ip,
    )
    db.session.add(entry)
    # Caller is responsible for the outer db.session.commit() as part of its own transaction.
    return entry
