import os
from flask import Flask

from .config import DATA_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "rag-secret-key-2024")

from . import data
data.init_user_db()

from . import models
models.get_model()

from . import routes
