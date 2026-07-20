import os, sys, atexit, shutil, tempfile, sqlite3
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

_tmp_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp_dir
os.environ["LLM_API_KEY"] = ""

atexit.register(lambda: shutil.rmtree(_tmp_dir, ignore_errors=True))

_patcher = patch("sentence_transformers.SentenceTransformer")
_mock_st_cls = _patcher.start()
_mock_instance = MagicMock()
_mock_instance.encode.return_value = np.array([[0.1] * 768])
_mock_st_cls.return_value = _mock_instance


@pytest.fixture(scope="session")
def app():
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_data(app):
    yield
    from app.data import DB_PATH, client as chroma_client, _doc_counters
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    for c in chroma_client.list_collections():
        chroma_client.delete_collection(c.name)
    _doc_counters.clear()
