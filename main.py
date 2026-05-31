from flask import Flask
from database import db
import os
from models import *
import secrets
from pathlib import Path



app=Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"]=f"sqlite:///{os.path.abspath(os.path.dirname(__file__))}/database/SE_proj.db"

SECRET_FILE_PATH = Path(".flask_secret")
try:
    with SECRET_FILE_PATH.open("r") as secret_file:
        app.secret_key = secret_file.read()
except FileNotFoundError:
    # Let's create a cryptographically secure code in that file
    with SECRET_FILE_PATH.open("w") as secret_file:
        app.secret_key = secrets.token_hex(32)
        secret_file.write(app.secret_key)


db.init_app(app)
os.makedirs(os.path.join(os.path.dirname(__file__), "database"), exist_ok=True)
app.app_context().push()
db.create_all()

from  controllers.controllers import *


if __name__ == '__main__':
    app.run(host='localhost', debug=True)