import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rsa_checkins import db  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.sqlite3")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def fake_client_factory():
    from fakes import FakeClient
    return lambda responses=None, responder=None: FakeClient(responses, responder)
