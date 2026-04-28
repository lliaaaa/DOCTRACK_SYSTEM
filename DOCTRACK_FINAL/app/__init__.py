from flask import Flask
from flask_migrate import Migrate
from flask_login import LoginManager

from .models import db, Account, User, Department, DocumentStatus, DocumentType
from config import Config

migrate = Migrate()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "You must login first"
    login_manager.login_message_category = "warning"

    from .auth import bp as auth_bp
    from .routes import bp as main_bp
    from .routes_api import api_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    with app.app_context():
        db.create_all()
        _seed_data()

    return app


def _seed_data():
    """Seed departments, admin accounts, document types, and statuses."""

    department_names = [
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
        "Vice Mayor Office",
    ]

    # --- Departments ---
    for name in department_names:
        if not Department.query.filter_by(department_name=name).first():
            code = "".join(w[0] for w in name.split())[:6].upper()
            db.session.add(Department(department_name=name, department_code=code))
    db.session.flush()

    # --- Admin users (one per department) ---
    for dept_name in department_names:
        dept = Department.query.filter_by(department_name=dept_name).first()
        if not dept:
            continue
        email = f"{dept_name.lower().replace(' ', '')}@site.com"
        if not User.query.filter_by(email=email).first():
            user = User(
                first_name=dept_name,
                last_name="Admin",
                email=email,
                department_id=dept.department_id,
            )
            db.session.add(user)
            db.session.flush()
            account = Account(
                user_id=user.user_id,
                username=email,
                role="admin",
                status="active",
            )
            account.set_password("123")
            db.session.add(account)

    db.session.flush()

    # --- Document types ---
    for name in ["SVP", "Bidding", "Reimbursement of Diesel",
                 "Reimbursement of Tarpaulin", "Burial Assistance", "T.E.V"]:
        if not DocumentType.query.filter_by(type_name=name).first():
            db.session.add(DocumentType(type_name=name))

    # --- Document statuses ---
    for name in [
        "For Signature Mayor",
        "Request for PR",
        "Request for PO",
        "Request for OBR",
        "For Signature BAC Members - BAC Office",
        "For Accounting Staff Validation",
        "For Processing",
        "With Checked",
        "Closed",
    ]:
        if not DocumentStatus.query.filter_by(name=name).first():
            db.session.add(DocumentStatus(name=name))

    db.session.commit()


@login_manager.user_loader
def load_user(user_id):
    return Account.query.get(int(user_id))
