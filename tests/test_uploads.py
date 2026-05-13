import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils import app_utils
from utils.app_utils import (
    MAX_UPLOAD_BYTES,
    UploadValidationError,
    cleanup_replaced_saved_uploads,
    delete_saved_uploads_for_settings,
    handle_request_files,
)


class DummyUpload:
    def __init__(self, filename, content, content_length=None):
        self.filename = filename
        self.stream = io.BytesIO(content)
        self.content_length = content_length

    def save(self, destination):
        self.stream.seek(0)
        Path(destination).write_bytes(self.stream.read())


class DummyRequestFiles:
    def __init__(self, files):
        self._files = files

    def keys(self):
        return [key for key, _ in self._files]

    def items(self, multi=False):
        if not multi:
            return dict(self._files).items()
        return iter(self._files)


def patch_upload_dir(monkeypatch, tmp_path):
    src_dir = tmp_path / "src"
    monkeypatch.setattr(app_utils, "resolve_path", lambda path: str(src_dir / path))
    return src_dir / "static" / "images" / "saved"


def test_handle_request_files_uses_unique_names_for_duplicate_upload_names(monkeypatch, tmp_path):
    upload_dir = patch_upload_dir(monkeypatch, tmp_path)
    request_files = DummyRequestFiles([
        ("backgroundImageFile[]", DummyUpload("same.PNG", b"first")),
        ("backgroundImageFile[]", DummyUpload("same.PNG", b"second")),
    ])

    result = handle_request_files(request_files)

    paths = result["backgroundImageFile[]"]
    assert len(paths) == 2
    assert paths[0] != paths[1]
    assert all(Path(path).parent == upload_dir for path in paths)
    assert all(Path(path).suffix == ".png" for path in paths)
    assert Path(paths[0]).read_bytes() == b"first"
    assert Path(paths[1]).read_bytes() == b"second"


def test_handle_request_files_rejects_disallowed_extension(monkeypatch, tmp_path):
    upload_dir = patch_upload_dir(monkeypatch, tmp_path)
    request_files = DummyRequestFiles([
        ("backgroundImageFile", DummyUpload("payload.exe", b"bad")),
    ])

    with pytest.raises(UploadValidationError, match="Unsupported file extension"):
        handle_request_files(request_files)

    assert not upload_dir.exists()


def test_handle_request_files_rejects_oversized_upload(monkeypatch, tmp_path):
    upload_dir = patch_upload_dir(monkeypatch, tmp_path)
    request_files = DummyRequestFiles([
        ("backgroundImageFile", DummyUpload("large.png", b"", content_length=MAX_UPLOAD_BYTES + 1)),
    ])

    with pytest.raises(UploadValidationError) as excinfo:
        handle_request_files(request_files)

    assert excinfo.value.status_code == 413
    assert not upload_dir.exists()


def test_cleanup_replaced_saved_uploads_removes_only_unreferenced_saved_files(monkeypatch, tmp_path):
    upload_dir = patch_upload_dir(monkeypatch, tmp_path)
    upload_dir.mkdir(parents=True)
    stale_file = upload_dir / "stale.png"
    kept_file = upload_dir / "kept.png"
    outside_file = tmp_path / "outside.png"
    stale_file.write_bytes(b"stale")
    kept_file.write_bytes(b"kept")
    outside_file.write_bytes(b"outside")

    deleted = cleanup_replaced_saved_uploads(
        {
            "backgroundImageFile": str(stale_file),
            "gallery": [str(kept_file)],
            "outside": str(outside_file),
        },
        {"gallery": [str(kept_file)]}
    )

    assert deleted == [str(stale_file)]
    assert not stale_file.exists()
    assert kept_file.exists()
    assert outside_file.exists()


def test_delete_saved_uploads_for_settings_removes_nested_saved_files(monkeypatch, tmp_path):
    upload_dir = patch_upload_dir(monkeypatch, tmp_path)
    upload_dir.mkdir(parents=True)
    first_file = upload_dir / "first.png"
    second_file = upload_dir / "second.png"
    first_file.write_bytes(b"first")
    second_file.write_bytes(b"second")

    deleted = delete_saved_uploads_for_settings({
        "backgroundImageFile": str(first_file),
        "nested": {"gallery": [str(second_file)]},
    })

    assert sorted(deleted) == sorted([str(first_file), str(second_file)])
    assert not first_file.exists()
    assert not second_file.exists()
