"""Tests for cookie-file validation (app.downloader.valid_cookie_file)."""
from app.downloader import _looks_like_auth_error, valid_cookie_file

NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"
DATA_LINE = ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tabc123\n"


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_empty_file_is_invalid(tmp_path):
    assert valid_cookie_file(_write(tmp_path, "c.txt", "")) is False


def test_whitespace_only_is_invalid(tmp_path):
    assert valid_cookie_file(_write(tmp_path, "c.txt", "\n\n   \n")) is False


def test_header_only_is_valid(tmp_path):
    assert valid_cookie_file(_write(tmp_path, "c.txt", NETSCAPE_HEADER)) is True


def test_alt_header_is_valid(tmp_path):
    assert valid_cookie_file(_write(tmp_path, "c.txt", "# HTTP Cookie File\n")) is True


def test_data_line_without_header_is_valid(tmp_path):
    assert valid_cookie_file(_write(tmp_path, "c.txt", DATA_LINE)) is True


def test_full_file_is_valid(tmp_path):
    assert valid_cookie_file(_write(tmp_path, "c.txt", NETSCAPE_HEADER + DATA_LINE)) is True


def test_junk_text_is_invalid(tmp_path):
    assert valid_cookie_file(_write(tmp_path, "c.txt", "this is not a cookie file\n")) is False


def test_comment_only_is_invalid(tmp_path):
    # comments that aren't the Netscape header, no data lines
    assert valid_cookie_file(_write(tmp_path, "c.txt", "# some comment\n# another\n")) is False


def test_missing_file_is_invalid(tmp_path):
    assert valid_cookie_file(str(tmp_path / "nope.txt")) is False


def test_empty_path_is_invalid():
    assert valid_cookie_file("") is False


def test_data_line_too_few_fields_is_invalid(tmp_path):
    # only 4 tab-separated fields -> not a real cookie record
    assert valid_cookie_file(_write(tmp_path, "c.txt", "a\tb\tc\td\n")) is False


def test_auth_error_detection():
    assert _looks_like_auth_error("ERROR: Sign in to confirm you're not a bot")
    assert _looks_like_auth_error("Please use --cookies for this video")
    assert _looks_like_auth_error("")  is False
    assert _looks_like_auth_error("HTTP Error 404: Not Found") is False
