from pathlib import Path


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "templates"


def test_plugin_icon_templates_use_cache_busting_versions():
    inky_template = (TEMPLATES_DIR / "inky.html").read_text()
    plugin_template = (TEMPLATES_DIR / "plugin.html").read_text()
    playlist_template = (TEMPLATES_DIR / "playlist.html").read_text()

    assert "filename='icon.png', v=plugin.icon_version|default('')" in inky_template
    assert "filename='icon.png', v=plugin.icon_version|default('')" in plugin_template
    assert "filename='icon.png', v=plugin_config.icon_version|default('')" in playlist_template


def test_plugin_lists_lazy_load_icon_and_thumbnail_images():
    inky_template = (TEMPLATES_DIR / "inky.html").read_text()
    plugin_template = (TEMPLATES_DIR / "plugin.html").read_text()
    playlist_template = (TEMPLATES_DIR / "playlist.html").read_text()

    assert 'loading="lazy"' in inky_template
    assert 'loading="lazy"' in plugin_template
    assert 'class="plugin-icon" loading="lazy" decoding="async"' in playlist_template
    assert 'loading="lazy"\n                                        decoding="async"' in playlist_template
