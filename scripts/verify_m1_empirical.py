"""
Milestone 1 Empirical Challenger Verification Script

Validates:
1. Font HTTP serving via FastAPI TestClient (status 200, Content-Type, Content-Length, exact bytes).
2. @font-face URL relative path resolution against /static/style.css.
3. CSS syntax integrity (brace, bracket, paren balancing, string and comment closure) in style.css.
4. Design tokens and font-face property verification.
"""

import os
import re
import struct
import sys
import urllib.parse
from pathlib import Path

from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from companion.server import app

client = TestClient(app)


def test_font_http_serving():
    print("[1/4] Testing Font HTTP Serving...")
    font_disk_path = PROJECT_ROOT / "companion" / "static" / "fonts" / "fnt_nosutaru.ttf"
    assert font_disk_path.exists(), f"Font file missing at {font_disk_path}"
    disk_size = font_disk_path.stat().st_size
    assert disk_size == 2952228, f"Unexpected disk font size: {disk_size}"

    res = client.get("/static/fonts/fnt_nosutaru.ttf")
    assert res.status_code == 200, f"Expected 200 OK, got {res.status_code}"
    
    ct = res.headers.get("content-type", "")
    assert "font/ttf" in ct or "application/x-font-ttf" in ct, f"Unexpected Content-Type: {ct}"
    
    cl = res.headers.get("content-length")
    assert cl == str(disk_size), f"Content-Length mismatch: {cl} vs {disk_size}"
    assert len(res.content) == disk_size, f"Body length mismatch: {len(res.content)} vs {disk_size}"
    assert res.content == font_disk_path.read_bytes(), "Response body bytes do not match disk file exactly!"

    # Test HTTP Range request (Partial Content)
    res_range = client.get("/static/fonts/fnt_nosutaru.ttf", headers={"Range": "bytes=0-31"})
    assert res_range.status_code == 206, f"Expected 206 Partial Content, got {res_range.status_code}"
    assert len(res_range.content) == 32, f"Expected 32 bytes for range, got {len(res_range.content)}"

    # Binary TrueType table structure verification
    data = res.content
    sfnt_version = data[:4]
    assert sfnt_version in (b"\x00\x01\x00\x00", b"true", b"OTTO"), f"Invalid font header: {sfnt_version}"
    num_tables, = struct.unpack(">H", data[4:6])
    assert num_tables >= 10, f"Suspiciously few font tables: {num_tables}"

    print(f"  -> HTTP 200 OK, Content-Type={ct}, Content-Length={cl}")
    print(f"  -> Exact byte match verified ({disk_size} bytes).")
    print(f"  -> HTTP 206 Partial Content verified (Range: bytes=0-31 -> 32 bytes).")
    print(f"  -> TrueType binary format verified ({num_tables} tables).")


def test_font_face_relative_url_resolution():
    print("[2/4] Testing @font-face Relative URL Resolution...")
    css_path = PROJECT_ROOT / "companion" / "static" / "style.css"
    css_content = css_path.read_text(encoding="utf-8")

    font_face_matches = re.findall(r"@font-face\s*\{([^}]+)\}", css_content)
    assert len(font_face_matches) > 0, "No @font-face block found in style.css!"

    css_url = "http://localhost:8000/static/style.css"

    for idx, block in enumerate(font_face_matches):
        urls = re.findall(r"url\s*\(\s*['\"]?([^'\")]+)['\"]?\s*\)", block)
        assert urls, f"@font-face block {idx+1} has no url(...) declarations!"
        for rel_url in urls:
            resolved = urllib.parse.urljoin(css_url, rel_url)
            parsed_path = urllib.parse.urlparse(resolved).path
            print(f"  -> Declaration: url('{rel_url}')")
            print(f"  -> Resolved against {css_url} -> {resolved} (Path: {parsed_path})")

            # Fetch via TestClient
            res = client.get(parsed_path)
            assert res.status_code == 200, f"Failed to fetch resolved font URL {parsed_path}: status {res.status_code}"
            assert len(res.content) == 2952228, f"Unexpected body length for resolved path {parsed_path}"

            # Verify with query string simulation (e.g. cache busting /static/style.css?v=2)
            resolved_with_query = urllib.parse.urljoin("http://localhost:8000/static/style.css?v=2", rel_url)
            assert urllib.parse.urlparse(resolved_with_query).path == parsed_path

    print("  -> @font-face relative path resolution verified with standard and query URLs.")


def test_css_syntax_and_braces():
    print("[3/4] Testing CSS Syntax & Brace Integrity in style.css...")
    css_path = PROJECT_ROOT / "companion" / "static" / "style.css"
    content = css_path.read_text(encoding="utf-8")

    stack = []
    errors = []

    i = 0
    line = 1
    col = 1
    n = len(content)

    in_comment = False
    comment_start = None

    in_string = False
    string_char = None
    string_start = None

    while i < n:
        c = content[i]

        if in_comment:
            if c == "*" and i + 1 < n and content[i + 1] == "/":
                in_comment = False
                i += 2
                col += 2
                continue
            elif c == "\n":
                line += 1
                col = 1
                i += 1
                continue
            else:
                col += 1
                i += 1
                continue

        if in_string:
            if c == "\\":
                i += 2
                col += 2
                continue
            elif c == string_char:
                in_string = False
                string_char = None
                col += 1
                i += 1
                continue
            elif c == "\n":
                errors.append(f"Unterminated string starting at line {string_start[0]}, col {string_start[1]}")
                in_string = False
                string_char = None
                line += 1
                col = 1
                i += 1
                continue
            else:
                col += 1
                i += 1
                continue

        if c == "/" and i + 1 < n and content[i + 1] == "*":
            in_comment = True
            comment_start = (line, col)
            i += 2
            col += 2
            continue

        if c in ('"', "'"):
            in_string = True
            string_char = c
            string_start = (line, col)
            i += 1
            col += 1
            continue

        if c in "{[(":
            stack.append((c, line, col))
        elif c in "}])":
            if not stack:
                errors.append(f"Unmatched closing {c} at line {line}, col {col}")
            else:
                open_c, o_line, o_col = stack.pop()
                matching = {"}": "{", "]": "[", ")": "("}
                if open_c != matching[c]:
                    errors.append(
                        f"Mismatched closing {c} at line {line}, col {col} "
                        f"(expected close for {open_c} from line {o_line}, col {o_col})"
                    )

        if c == "\n":
            line += 1
            col = 1
        else:
            col += 1
        i += 1

    if in_comment:
        errors.append(f"Unterminated comment starting at line {comment_start[0]}, col {comment_start[1]}")
    if in_string:
        errors.append(f"Unterminated string starting at line {string_start[0]}, col {string_start[1]}")
    while stack:
        open_c, o_line, o_col = stack.pop()
        errors.append(f"Unclosed {open_c} from line {o_line}, col {o_col}")

    assert len(errors) == 0, f"Found {len(errors)} CSS syntax errors:\n" + "\n".join(errors)
    print(f"  -> Scanned {line} lines ({len(content)} chars): 0 errors.")
    print("  -> Braces {}, Brackets [], Parentheses (), Quotes, and Comments are 100% balanced.")


def test_design_token_system():
    print("[4/4] Validating Design Token System & Invariants...")
    css_path = PROJECT_ROOT / "companion" / "static" / "style.css"
    content = css_path.read_text(encoding="utf-8")

    expected_tokens = [
        "--bg-page",
        "--surface-plaque",
        "--surface-plaque-hover",
        "--surface-card",
        "--surface-card-inset",
        "--surface-panel",
        "--border-outline",
        "--border-outline-soft",
        "--border-outline-dark",
        "--ink",
        "--ink-muted",
        "--ink-light",
        "--ink-heading",
        "--accent-amber",
        "--accent-gold",
        "--accent-go",
        "--accent-danger",
        "--accent-info",
        "--season-spring",
        "--season-summer",
        "--season-fall",
        "--season-winter",
        "--pref-love",
        "--pref-like",
        "--radius-plaque",
        "--radius-keycap",
        "--radius-cell",
        "--radius-pill",
        "--shadow-plaque",
        "--shadow-keycap",
        "--shadow-keycap-hover",
        "--font-pixel",
        "--font-body",
    ]

    for tok in expected_tokens:
        assert tok in content, f"Missing token {tok} in style.css"

    # Invariants
    assert "-webkit-font-smoothing: none" in content
    assert "text-rendering: geometricPrecision" in content

    # Test endpoint for HTML
    res_html = client.get("/")
    assert res_html.status_code == 200
    assert "fonts.googleapis.com" in res_html.text
    assert "Nunito" in res_html.text
    print("  -> All design tokens, rendering flags, and HTML font tags verified.")


if __name__ == "__main__":
    test_font_http_serving()
    test_font_face_relative_url_resolution()
    test_css_syntax_and_braces()
    test_design_token_system()
    print("\nALL EMPIRICAL CHALLENGER TESTS PASSED SUCCESSFULLY!")
