from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path):
    return (ROOT / path).read_text()


def test_mutating_templates_include_csrf_meta_and_security_fetch_wrapper():
    for path in [
        "src/templates/inky.html",
        "src/templates/settings.html",
        "src/templates/plugin.html",
        "src/templates/playlist.html",
        "src/templates/apikeys.html"
    ]:
        template = read_repo_file(path)
        assert 'meta name="csrf-token"' in template
        assert "scripts/security.js" in template


def test_security_fetch_wrapper_adds_csrf_header_to_mutating_requests():
    script = read_repo_file("src/static/scripts/security.js")

    assert "protectedMethods" in script
    assert "'POST'" in script
    assert "'PUT'" in script
    assert "'DELETE'" in script
    assert "X-CSRF-Token" in script
    assert "target.origin !== window.location.origin" in script


def test_readme_documents_default_trusted_lan_warning_and_admin_token():
    readme = read_repo_file("README.md")

    assert "Web UI security" in readme
    assert "trusted local network only" in readme
    assert "INKYPI_ADMIN_TOKEN" in readme
    assert "INKYPI_SECRET_KEY" in readme
    assert "Authorization: Bearer" in readme


def test_inkypi_uses_strong_session_secret_fallback_and_cookie_flags():
    inkypi = read_repo_file("src/inkypi.py")

    assert "secrets.token_hex(32)" in inkypi
    assert "random.randint" not in inkypi
    assert 'SESSION_COOKIE_HTTPONLY"] = True' in inkypi
    assert 'SESSION_COOKIE_SAMESITE"] = "Lax"' in inkypi
