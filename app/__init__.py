import os
from flask import Flask

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "rag-secret-key-2024")

from app import config, templates, services, data, routes
