from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'clipper.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", testing_session_local)
    yield
    engine.dispose()
