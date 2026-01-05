from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                # Let Flask-Login handle redirect to login
                return current_user  # do nothing, login_required will redirect
            if current_user.role != role:
                flash("You are not authorized to access this page.", "danger")
                # Redirect to a safe page that does NOT require this role
                return redirect(url_for("main.home"))  
            return f(*args, **kwargs)
        return wrapped
    return decorator
