"""Shared test fixtures.

The app imports ``yt_dlp`` at module load; it's a heavy dependency we don't
need for unit tests, so we install a lightweight stub before anything imports it.
"""
import os
import sys
import tempfile
import types

# Point DATA_DIR at a writable temp dir before any app module reads config,
# so import-time os.makedirs() doesn't try to create /data.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ytrss-test-"))

if "yt_dlp" not in sys.modules:
    stub = types.ModuleType("yt_dlp")

    class _DownloadError(Exception):
        pass

    utils = types.ModuleType("yt_dlp.utils")
    utils.DownloadError = _DownloadError
    stub.utils = utils

    class _YoutubeDL:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, *a, **k):
            return {}

    stub.YoutubeDL = _YoutubeDL
    sys.modules["yt_dlp"] = stub
    sys.modules["yt_dlp.utils"] = utils
