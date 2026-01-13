from datetime import datetime
from zoneinfo import ZoneInfo
import uuid
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(150), nullable=False)  # ✅ NEW

    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    department = db.Column(db.String(100), nullable=True)
    role = db.Column(db.String(50), default="user", nullable=False)
    is_deactivated = db.Column(db.Boolean, default=False)
    created_at = db.Column(
    db.DateTime(timezone=True),
    default=lambda: datetime.now(ZoneInfo("Asia/Manila"))
)


    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


    def get_id(self):
        return str(self.id)

class DocumentType(db.Model):
    __tablename__ = 'document_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
class DocumentStatus(db.Model):
    __tablename__ = 'document_status'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
class Record(db.Model):
    __tablename__ = 'records'

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    doc_type = db.Column(db.String(50), nullable=False)
    department = db.Column(db.String(100), nullable=False)

    implementing_office = db.Column(db.String(100), nullable=False)

    date_received = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=True)
    released_by = db.Column(db.String(100), nullable=False)
    received_by = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(ZoneInfo("Asia/Manila"))
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(ZoneInfo("Asia/Manila")),
        onupdate=lambda: datetime.now(ZoneInfo("Asia/Manila"))
    )

    history = db.relationship(
        'RecordHistory',
        back_populates='record',
        order_by='RecordHistory.timestamp'
    )

class RecordHistory(db.Model):
    __tablename__ = 'record_history'

    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('records.id'), nullable=False)
    action_type = db.Column(db.String(20), nullable=False) 
    status = db.Column(db.String(100), nullable=False) 
    from_department = db.Column(db.String(100), nullable=True)
    to_department = db.Column(db.String(100), nullable=True)
    action_by = db.Column(db.String(100), nullable=True) 
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    record = db.relationship('Record', back_populates='history')

class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<Record id={self.id} document_id={self.document_id} status={self.status}>"
