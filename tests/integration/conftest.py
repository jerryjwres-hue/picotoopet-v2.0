import secrets
import socket
import threading
import time

import pytest
import uvicorn

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


@pytest.fixture
def live_core(tmp_path):
    token = secrets.token_hex(24)
    paths = RuntimePaths.from_root(tmp_path / "core")
    app = create_app(AppSettings(paths=paths, api_token=token))
    server = uvicorn.Server(uvicorn.Config(app, ws="none", log_level="warning"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            until = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < until:
                time.sleep(0.01)
            assert server.started
            yield f"http://127.0.0.1:{port}", {"Authorization": f"Bearer {token}"}
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive()
