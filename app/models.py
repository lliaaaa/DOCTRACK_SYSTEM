from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default="user")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def __repr__(self):
        return f"<User {self.email}>"

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

class Record(db.Model):
    __tablename__ = "records"

    id = db.Column(db.Integer, primary_key=True)
    control = db.Column(db.String(100))
    department = db.Column(db.String(100))
    type = db.Column(db.String(100))
    amount = db.Column(db.Float)
    payee = db.Column(db.String(100))
    source = db.Column(db.String(100))
    date_in = db.Column(db.String(100))
    clock_in = db.Column(db.String(100))
    date_returned = db.Column(db.String(100))
    clock_out = db.Column(db.String(100))
    status = db.Column(db.String(100))
    remarks = db.Column(db.String(200))

    def __repr__(self):
        return f"<Record {self.control}>"
