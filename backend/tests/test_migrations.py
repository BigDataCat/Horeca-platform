import os
import shutil
import subprocess

from tests.conftest import TEST_DATABASE_URL


def test_models_match_migrations():
    """`alembic check` fails if the models have schema changes without a migration."""
    result = subprocess.run(
        [shutil.which("alembic") or "alembic", "check"],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
