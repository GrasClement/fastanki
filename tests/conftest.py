import shutil, subprocess, tempfile
import pytest
from fastanki.syncer import start_sync_server

@pytest.fixture
def server():
    base = tempfile.mkdtemp()
    proc, ep = start_sync_server(base)
    try: yield ep
    finally:
        proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        shutil.rmtree(base, ignore_errors=True)
