import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from .models import User
from flask_login import login_user, logout_user, login_required, current_user

from . import db

bp = Blueprint("auth", __name__, url_prefix="/auth")
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].lower().strip()
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if not user:
            flash("No account found with this email.", "danger")
            return redirect(url_for("auth.login"))

        if not user.check_password(password):
            flash("Incorrect password.", "danger")
            return redirect(url_for("auth.login"))

        # ✅ Login successful
        login_user(user)

        # Redirect based on role
        if user.role.lower() == "admin":
            return redirect(url_for("main.admin_home"))
        else:
            return redirect(url_for("main.department_home"))

    return render_template("login.html")


@bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password")
    new_password = request.form.get("new_password")
    confirm_password = request.form.get("confirm_password")

    # 🔒 Validate current password
    if not current_user.check_password(current_password):
        flash("Current password is incorrect.", "danger")
        return redirect(request.referrer)

    # 🔒 Validate new password match
    if new_password != confirm_password:
        flash("New passwords do not match.", "warning")
        return redirect(request.referrer)

    # 🔒 Optional: minimum length
    if len(new_password) < 6:
        flash("Password must be at least 6 characters long.", "warning")
        return redirect(request.referrer)

    # ✅ Update password
    current_user.set_password(new_password)
    db.session.commit()

    flash("Password updated successfully.", "success")
    return redirect(request.referrer)

@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("main.home"))
