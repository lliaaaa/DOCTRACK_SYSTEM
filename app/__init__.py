from flask import Flask
from flask_migrate import Migrate
from flask_login import LoginManager

from .models import db
from config import Config

migrate = Migrate()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"  # ✅ FIX
    login_manager.login_message = "You must login first"
    login_manager.login_message_category = "warning"

    # Register blueprints
    from .auth import bp as auth_bp
    from .routes import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()

    return app


@login_manager.user_loader
def load_user(user_id):
    from .models import User
    return User.query.get(int(user_id))
