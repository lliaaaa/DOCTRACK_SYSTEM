import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from .models import User
from . import db

bp = Blueprint("auth", __name__, url_prefix="/auth")

@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":

        password = request.form.get("password")

        password_regex = r'^(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$'

        if not re.match(password_regex, password):
            flash("Password must be at least 8 characters long, include one uppercase letter, one number, and one special character.", "danger")
            return redirect(url_for("main.register"))
        flash("Account created!", "success")
        return redirect(url_for("main.home"))

    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].lower()
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        # Check login
        if user and user.check_password(password):
            session["user_id"] = user.id
            session["role"] = user.role
            if user.role == "admin":
                return redirect(url_for("main.superadmin_home"))

            else:
                return redirect(url_for("main.department_home"))

        flash("Invalid email or password", "danger")

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))
