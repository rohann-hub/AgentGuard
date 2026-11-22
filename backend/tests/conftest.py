import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db(tmp_path):
    """A throwaway SQLite database with the app's tables; yields a sync Session for seeding."""
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from app.database.models import Base

    path = tmp_path / "test.db"
    sync_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync_engine)
    # NullPool: TestClient runs the app on its own event loop, so never share connections.
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    sessions = async_sessionmaker(async_engine, expire_on_commit=False)
    with Session(sync_engine) as seed:
        seed.sessions = sessions
        yield seed
    sync_engine.dispose()


@pytest.fixture
def make_client(db):
    """Build a TestClient whose requests use the `db` fixture's database."""
    from app.database.connection import get_session

    async def override():
        async with db.sessions() as session:
            yield session

    clients = []

    def make(**kwargs):
        app = create_app()
        app.dependency_overrides[get_session] = override
        c = TestClient(app, **kwargs)
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)
