import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:root@localhost:5432/flask_doctrack'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'a-very-long-random-string-1234567890!@#$%^&*()'