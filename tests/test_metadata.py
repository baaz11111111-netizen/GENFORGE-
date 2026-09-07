import pytest

from services.media_probe import probe_media


def test_probe_rejects_missing_media():
    with pytest.raises(FileNotFoundError):
        probe_media("does-not-exist.mp4")
