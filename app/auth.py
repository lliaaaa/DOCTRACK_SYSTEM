import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from .models import User
from . import db

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    # Get role from URL parameter (GET) or form hidden input (POST)
    role = request.args.get("role") or request.form.get("role") or "office"

    if request.method == "POST":
        email = request.form["email"].lower()
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        # Check login
        if user and user.check_password(password):
            if user.role != role:
                flash(f"You are not authorized for {role} login.", "danger")
                return redirect(url_for("auth.login", role=role))

            # Save session
            session["user_id"] = user.id
            session["role"] = user.role

            # Redirect based on role
            if user.role == "admin":
                return redirect(url_for("main.superadmin_home"))
            else:
                return redirect(url_for("main.department_home"))

        flash("Invalid email or password", "danger")
        return redirect(url_for("auth.login", role=role))

    # GET request
    return render_template("login.html", role=role)


@bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))
