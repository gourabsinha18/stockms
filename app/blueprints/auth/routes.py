from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, limiter
from app.models import User
from app.services.audit_service import log_action
from .forms import LoginForm, ChangePasswordForm

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user is None or not user.check_password(form.password.data):
            log_action("LOGIN_FAILED", "User", entity_id=user.id if user else None,
                       new_value=f"username={form.username.data}")
            db.session.commit()
            flash("Invalid username or password.", "danger")
            return redirect(url_for("auth.login"))

        if not user.is_active:
            flash("This account has been deactivated. Contact your administrator.", "danger")
            return redirect(url_for("auth.login"))

        login_user(user, remember=form.remember_me.data)
        user.last_login_at = datetime.utcnow()
        log_action("LOGIN", "User", entity_id=user.id)
        db.session.commit()

        next_page = request.args.get("next")
        if not next_page or not next_page.startswith("/"):
            next_page = url_for("main.dashboard")
        return redirect(next_page)

    return render_template("auth/login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    log_action("LOGOUT", "User", entity_id=current_user.id)
    db.session.commit()
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
        elif form.new_password.data != form.confirm_password.data:
            flash("New passwords do not match.", "danger")
        else:
            current_user.set_password(form.new_password.data)
            log_action("PASSWORD_CHANGE", "User", entity_id=current_user.id)
            db.session.commit()
            flash("Password updated successfully.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/change_password.html", form=form)
