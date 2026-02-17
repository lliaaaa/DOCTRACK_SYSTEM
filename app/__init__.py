from flask import Flask
from flask_migrate import Migrate
from flask_login import LoginManager

from .models import db, User, Department, DocumentStatus, DocumentType
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
    from .routes_api import api_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    with app.app_context():
        db.create_all()
        
        departments = [
        "ABC Office",
        "Accounting Office",
        "Agriculture Office",
        "Assessors Office",
        "Bids and Awards Committee",
        "COMELEC Office",
        "Engineering",
        "Human Resources Office",
        "Library Office",
        "Mayor Office",
        "MENRO Office",
        "MDRRMO Office",
        "MPDC Office",
        "Municipal Health Office",
        "Treasurer Office",
        "Vice Mayor Office"
    ]

        for dept in departments:
            # Check if admin for this department already exists
            if not User.query.filter_by(email=f"{dept.lower().replace(' ', '')}@site.com").first():
                # Create a new admin for the department
                admin = User(
                    full_name=f"{dept} Admin",
                    email=f"{dept.lower().replace(' ', '')}@site.com",
                    role="admin",
                    department=dept
                )
                admin.set_password("123")  # default password
                db.session.add(admin)

                db.session.commit()


        for name in departments:
            if not Department.query.filter_by(name=name).first():
                db.session.add(Department(name=name))
                db.session.commit()

        document_types = [
            "SVP",
            "Bidding",
            "Reimbursement of Diesel",
            "Reimbursement of Tarpaulin",
            "Burial Assistance",
            "T.E.V"
        ]

        for name in document_types:
            if not DocumentType.query.filter_by(name=name).first():
                db.session.add(DocumentType(name=name))
                db.session.commit()

        document_statuses = [
            "For Signature Mayor",
            "Request for PR",
            "Request for PO",
            "Request for OBR",
            "For Signature BAC Members - BAC Office",
            "For Accounting Staff Validation",
            "For Processing",
            "With Checked",
            "Closed"
        ]

        for name in document_statuses:
            if not DocumentStatus.query.filter_by(name=name).first():
                db.session.add(DocumentStatus(name=name))

        db.session.commit()

    return app


@login_manager.user_loader
def load_user(user_id):
    from .models import User
    return User.query.get(int(user_id))
