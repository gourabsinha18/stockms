from flask import Blueprint, render_template, request
from flask_login import login_required
from app.models import AuditLog
from app.services.permission_service import admin_required

bp = Blueprint("audit", __name__)


@bp.route("/")
@login_required
@admin_required
def list_audit_logs():
    action_filter = request.args.get("action", "")
    entity_filter = request.args.get("entity", "")

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if entity_filter:
        query = query.filter(AuditLog.entity == entity_filter)

    logs = query.order_by(AuditLog.created_at.desc()).limit(300).all()
    actions = [row[0] for row in AuditLog.query.with_entities(AuditLog.action).distinct().all()]
    entities = [row[0] for row in AuditLog.query.with_entities(AuditLog.entity).distinct().all()]

    return render_template("audit/list.html", logs=logs, actions=actions, entities=entities,
                           action_filter=action_filter, entity_filter=entity_filter)
