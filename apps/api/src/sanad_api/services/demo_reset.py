from __future__ import annotations

import runpy
import shutil
from pathlib import Path

from sqlalchemy.orm import close_all_sessions, sessionmaker

from sanad_api.database import Base
from sanad_api.services.glossary import seed_default_glossary


def reset_demo_state(*, session_local: sessionmaker, storage_root: Path) -> dict[str, str | bool]:
    from sanad_api import models  # noqa: F401

    engine = session_local.kw.get("bind")
    if engine is None:
        with session_local() as db:
            engine = db.get_bind()

    close_all_sessions()
    Base.metadata.create_all(bind=engine)
    _clear_database(engine)
    with session_local() as db:
        seed_default_glossary(db)

    if storage_root.exists():
        shutil.rmtree(storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)

    _regenerate_demo_fixtures()

    return {
        "status": "reset",
        "fixtures_regenerated": True,
        "storage_root": str(storage_root),
    }


def _regenerate_demo_fixtures() -> None:
    # First try relative to cwd (works in Docker since WORKDIR is /workspace/apps/api)
    script_path = Path.cwd() / "scripts" / "create_demo_fixtures.py"
    if not script_path.exists():
        # Fallback to the original parents[3] logic for standard editable installs
        api_dir = Path(__file__).resolve().parents[3]
        script_path = api_dir / "scripts" / "create_demo_fixtures.py"
        
    if not script_path.exists():
        raise FileNotFoundError(f"Could not find fixture script. Tried: {script_path}")
        
    runpy.run_path(str(script_path), run_name="__main__")


def _clear_database(engine) -> None:
    tables = list(Base.metadata.tables.values())
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            for table in tables:
                connection.execute(table.delete())
        finally:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
