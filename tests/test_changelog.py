"""Tests for the changelog data and the /api/changelog endpoint."""
import json

from app import __version__, changelog, main


def _base_version(v: str) -> str:
    # VERSION may carry a "+<sha>" suffix in local git checkouts.
    return v.split("+", 1)[0]


def test_changelog_entries_well_formed():
    assert changelog.CHANGELOG, "changelog must not be empty"
    seen = set()
    for entry in changelog.CHANGELOG:
        assert entry["version"] and entry["version"] not in seen, "versions unique + present"
        seen.add(entry["version"])
        assert entry["date"]
        assert entry["changes"] and all(isinstance(c, str) and c for c in entry["changes"])


def test_changelog_is_newest_first():
    def key(v):
        return [int(p) for p in v.split(".")]
    versions = [key(e["version"]) for e in changelog.CHANGELOG]
    assert versions == sorted(versions, reverse=True)


def test_current_version_has_changelog_entry():
    """The shipping version must be documented so the 'running' build shows notes."""
    versions = {e["version"] for e in changelog.CHANGELOG}
    assert _base_version(__version__) in versions


def test_api_changelog_payload():
    resp = main.api_changelog()
    data = json.loads(bytes(resp.body))
    assert data["version"] == main.VERSION
    assert data["started_at"] == main.STARTED_AT
    assert data["entries"] == changelog.CHANGELOG
