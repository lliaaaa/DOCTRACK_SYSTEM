from datetime import datetime
import uuid
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default="user", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.id)


class Record(db.Model):
    __tablename__ = "records"

    id = db.Column(db.Integer, primary_key=True)

    # ✅ RANDOM DOCUMENT ID (public)
    document_id = db.Column(
        db.String(32),
        unique=True,
        nullable=False,
        default=lambda: uuid.uuid4().hex.upper()
    )

    title = db.Column(db.String(200), nullable=False)
    doc_type = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    date_in = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=True)
    released_by = db.Column(db.String(100), nullable=False)
    received_by = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    remarks = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    head = db.Column(db.String(100), nullable=False)
    employees = db.Column(db.Integer, default=0)
    documents = db.Column(db.Integer, default=0)
    contact = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<Record id={self.id} document_id={self.document_id} status={self.status}>"
