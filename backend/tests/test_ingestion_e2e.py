import os
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_E2E_TESTS") != "1",
    reason="set RUN_E2E_TESTS=1 and start docker-compose.integration.yml to run e2e ingestion tests",
)


def test_e2e_ingestion_smoke_script():
    result = subprocess.run(
        [".venv/bin/python", "scripts/e2e_ingestion_smoke.py"],
        cwd=os.getcwd(),
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
