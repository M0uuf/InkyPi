import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils import http_client


def test_close_http_session_resets_created_session():
    session = http_client.get_http_session()

    http_client.close_http_session()

    assert http_client._HTTP_SESSION is None
    assert session is not http_client.get_http_session()
    http_client.close_http_session()


def test_close_http_session_is_harmless_without_session():
    http_client.close_http_session()
    http_client.close_http_session()

    assert http_client._HTTP_SESSION is None
