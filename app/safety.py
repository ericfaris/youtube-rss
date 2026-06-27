"""Shared input-safety helpers.

These guard values that originate outside our direct control (DB rows that
were populated from yt-dlp metadata, request parameters) before they are
interpolated into filesystem paths or URLs. The media filenames we generate
are always `<video_id>.<ext>` with a validated video_id, so these checks are
defense-in-depth: a single hardening point that fails closed if a bad value
ever reaches a path/URL.
"""
import re

# A safe single path segment: a basename only — no directory separators, no
# parent-dir refs, no leading dot (so no hidden files / `..`). The leading
# char may be `_` or `-` because YouTube video IDs (and thus our generated
# `<video_id>.mp3` / `<video_id>.jpg` names) can start with either.
_SAFE_MEDIA_NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")


def is_safe_media_name(name: str | None) -> bool:
    """Return True if ``name`` is safe to use as one path/URL segment.

    Rejects empty/over-long values, anything containing a path separator or a
    ``..`` sequence, and anything not matching the conservative basename
    pattern above.
    """
    if not name or len(name) > 128:
        return False
    if "/" in name or "\\" in name or ".." in name:
        return False
    return bool(_SAFE_MEDIA_NAME_RE.match(name))
