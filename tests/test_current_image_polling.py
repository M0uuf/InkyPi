from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_template(name):
    return (REPO_ROOT / "src" / "templates" / name).read_text()


def test_main_page_current_image_polling_is_visibility_aware():
    template = read_template("inky.html")

    assert "default(15)" in template
    assert "document.hidden" in template
    assert "visibilitychange" in template
    assert "clearInterval(refreshIntervalId)" in template
    assert "If-Modified-Since" in template


def test_main_page_listens_for_manual_refresh_signal():
    template = read_template("inky.html")

    assert "inkypi-current-image-refresh-requested-at" in template
    assert "window.addEventListener('storage'" in template
    assert "window.addEventListener('pageshow'" in template
    assert "requestCurrentImageRefresh()" in template


def test_manual_refresh_pages_signal_current_image_refresh():
    plugin_template = read_template("plugin.html")
    playlist_template = read_template("playlist.html")

    assert "signalCurrentImageRefresh()" in plugin_template
    assert "signalCurrentImageRefresh()" in playlist_template
    assert "localStorage.setItem(currentImageRefreshSignalKey" in plugin_template
    assert "localStorage.setItem(currentImageRefreshSignalKey" in playlist_template
