import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ai.mock import MockAIProvider
from tests.fakes import FakeDB


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def provider():
    return MockAIProvider()


@pytest.fixture
def client(db, provider):
    app = create_app()
    app.state.db = db
    app.state.provider = provider
    with TestClient(app) as test_client:
        yield test_client
