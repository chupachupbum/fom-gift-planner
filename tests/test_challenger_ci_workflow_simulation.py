"""
tests/test_challenger_ci_workflow_simulation.py

Empirical simulation and adversarial challenge harness for Milestone 4 CI/CD.
Directly executes the GitHub Actions workflow steps (.github/workflows/deploy-web.yml)
in clean isolated temporary workspaces and validates:
1. Pure Python wheel build (python -m build --wheel --outdir web/)
2. Bit-for-bit SHA-256 asset replication (data/*.json, sample_save.sav, fonts, icons)
3. Directory layout and path contracts expected by Pyodide and GitHub Pages
4. Idempotent re-execution resilience (dirty runs)
5. Static subpath hosting hygiene (no root-relative URL breaks on GitHub Pages)
"""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def simulated_workflow_clean():
    """
    Executes the exact workflow command sequence in a clean temporary checkout.
    Yields (repo_dir, web_dir).
    """
    with tempfile.TemporaryDirectory(prefix="test_gha_sim_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        repo_sim = tmp_dir / "fom-gift-planner"
        repo_sim.mkdir()

        # Step 1: Simulate actions/checkout@v4 (only git-tracked source, no build artifacts)
        shutil.copytree(REPO_ROOT / "fom_planner", repo_sim / "fom_planner")
        shutil.copytree(REPO_ROOT / "companion", repo_sim / "companion")
        shutil.copytree(REPO_ROOT / "data", repo_sim / "data")
        shutil.copytree(REPO_ROOT / "samples", repo_sim / "samples")
        shutil.copy2(REPO_ROOT / "pyproject.toml", repo_sim / "pyproject.toml")
        shutil.copy2(REPO_ROOT / "README.md", repo_sim / "README.md")

        web_sim = repo_sim / "web"
        web_sim.mkdir()
        shutil.copy2(REPO_ROOT / "web" / "index.html", web_sim / "index.html")
        shutil.copy2(REPO_ROOT / "web" / "style.css", web_sim / "style.css")
        shutil.copy2(REPO_ROOT / "web" / "app.js", web_sim / "app.js")
        shutil.copy2(REPO_ROOT / "web" / "planner.worker.js", web_sim / "planner.worker.js")
        shutil.copytree(REPO_ROOT / "web" / "py", web_sim / "py")

        # Step 2: Simulate actions/setup-python@v5 with python 3.12 venv
        venv_dir = tmp_dir / "venv"
        subprocess.run(f"python3 -m venv {venv_dir}", shell=True, check=True)
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = str(venv_dir)
        env["PATH"] = f"{venv_dir / 'bin'}:{env['PATH']}"

        # Step 3: Install build tool
        subprocess.run("pip install build", shell=True, cwd=repo_sim, env=env, check=True)

        # Step 4: Build pure Python wheel
        subprocess.run("python -m build --wheel --outdir web/", shell=True, cwd=repo_sim, env=env, check=True)

        # Step 5: Copy static data files
        subprocess.run("mkdir -p web/data && cp data/*.json web/data/", shell=True, cwd=repo_sim, env=env, check=True)

        # Step 6: Copy demo save
        subprocess.run("cp samples/sample_save.sav web/sample_save.sav", shell=True, cwd=repo_sim, env=env, check=True)

        # Step 7: Copy icons
        subprocess.run("mkdir -p web/icons && cp -r companion/static/icons/* web/icons/", shell=True, cwd=repo_sim, env=env, check=True)

        # Step 8: Copy fonts
        subprocess.run("mkdir -p web/fonts && cp -r companion/static/fonts/* web/fonts/", shell=True, cwd=repo_sim, env=env, check=True)

        # Step 9: Create .nojekyll
        subprocess.run("touch web/.nojekyll", shell=True, cwd=repo_sim, env=env, check=True)

        yield repo_sim, web_sim, env


def test_workflow_clean_execution_succeeds(simulated_workflow_clean):
    """Verify that all commands in deploy-web.yml succeed with exit code 0."""
    repo_sim, web_sim, _ = simulated_workflow_clean
    assert repo_sim.is_dir()
    assert web_sim.is_dir()


def test_workflow_wheel_artifact_integrity(simulated_workflow_clean):
    """Verify wheel build output name, contents, and package installability."""
    repo_sim, web_sim, env = simulated_workflow_clean

    wheel_files = list(web_sim.glob("*.whl"))
    assert len(wheel_files) == 1, f"Expected exactly 1 wheel file, found {len(wheel_files)}"
    built_wheel = wheel_files[0]
    expected_wheel_name = "fom_gift_planner-1.2.0-py3-none-any.whl"
    assert built_wheel.name == expected_wheel_name, f"Wheel name must be {expected_wheel_name}, got {built_wheel.name}"
    assert built_wheel.stat().st_size > 50000, "Wheel archive is suspiciously small"

    # Verify wheel internal structure
    with zipfile.ZipFile(built_wheel, "r") as zf:
        namelist = zf.namelist()
        assert "fom_planner/__init__.py" in namelist
        assert "fom_planner/parser.py" in namelist
        assert "fom_planner/optimizer.py" in namelist
        assert "fom_planner/crafting.py" in namelist
        assert "fom_planner/data_loader.py" in namelist
        assert "fom_planner/models.py" in namelist
        assert "fom_planner/constants.py" in namelist
        assert "fom_gift_planner-1.2.0.dist-info/METADATA" in namelist

    # Test wheel installation and import in the venv
    subprocess.run(f"pip install {built_wheel}", shell=True, cwd=repo_sim, env=env, check=True)
    test_import_cmd = (
        'python -c "import fom_planner; '
        'from fom_planner.parser import parse_save_file; '
        'from fom_planner.optimizer import plan_daily_gift_bag; '
        'from fom_planner.data_loader import load_item_locations; '
        'assert callable(parse_save_file); assert callable(plan_daily_gift_bag)"'
    )
    subprocess.run(test_import_cmd, shell=True, cwd=repo_sim, env=env, check=True)


def test_workflow_bit_for_bit_data_files(simulated_workflow_clean):
    """Verify all 6 game databases in data/ are copied bit-for-bit to web/data/."""
    repo_sim, web_sim, _ = simulated_workflow_clean

    expected_databases = [
        "alt_sources.json",
        "item_data.json",
        "item_locations.json",
        "item_seasons.json",
        "recipe_sources.json",
        "recipes.json",
    ]
    for db in expected_databases:
        src = repo_sim / "data" / db
        dst = web_sim / "data" / db
        assert src.exists(), f"Source data file missing: {src}"
        assert dst.exists(), f"Destination data file missing: {dst}"
        assert _sha256(src) == _sha256(dst), f"Bit-for-bit hash mismatch for {db}"


def test_workflow_bit_for_bit_demo_save(simulated_workflow_clean):
    """Verify samples/sample_save.sav is copied bit-for-bit to web/sample_save.sav."""
    repo_sim, web_sim, _ = simulated_workflow_clean

    src = repo_sim / "samples" / "sample_save.sav"
    dst = web_sim / "sample_save.sav"
    assert src.exists() and dst.exists()
    assert _sha256(src) == _sha256(dst), "Bit-for-bit hash mismatch for sample_save.sav"


def test_workflow_bit_for_bit_fonts(simulated_workflow_clean):
    """Verify companion/static/fonts/* is copied bit-for-bit to web/fonts/."""
    repo_sim, web_sim, _ = simulated_workflow_clean

    src_fonts = sorted((repo_sim / "companion" / "static" / "fonts").glob("*"))
    dst_fonts = sorted((web_sim / "fonts").glob("*"))
    assert len(dst_fonts) >= 1
    assert [f.name for f in src_fonts] == [f.name for f in dst_fonts]
    for sf, df in zip(src_fonts, dst_fonts):
        assert _sha256(sf) == _sha256(df), f"Bit-for-bit hash mismatch for font {sf.name}"


def test_workflow_bit_for_bit_all_icons(simulated_workflow_clean):
    """Verify all 752 icon files across all subdirectories match bit-for-bit."""
    repo_sim, web_sim, _ = simulated_workflow_clean

    src_base = repo_sim / "companion" / "static" / "icons"
    dst_base = web_sim / "icons"

    src_files = sorted([p for p in src_base.rglob("*") if p.is_file()])
    dst_files = sorted([p for p in dst_base.rglob("*") if p.is_file()])

    assert len(src_files) == 752, f"Expected 752 source icon files, found {len(src_files)}"
    assert len(dst_files) == 752, f"Expected 752 dest icon files, found {len(dst_files)}"

    for sf in src_files:
        rel = sf.relative_to(src_base)
        df = dst_base / rel
        assert df.exists(), f"Destination icon missing: {rel}"
        assert _sha256(sf) == _sha256(df), f"Bit-for-bit hash mismatch for icon {rel}"


def test_workflow_nojekyll_marker(simulated_workflow_clean):
    """Verify web/.nojekyll exists and is created in the deployment bundle."""
    _, web_sim, _ = simulated_workflow_clean
    nojekyll = web_sim / ".nojekyll"
    assert nojekyll.exists(), "web/.nojekyll must exist in deployment artifact"
    assert nojekyll.is_file()


def test_workflow_directory_layout_pyodide_contract(simulated_workflow_clean):
    """Verify directory layout precisely satisfies Pyodide worker contract."""
    _, web_sim, _ = simulated_workflow_clean

    worker_code = (web_sim / "planner.worker.js").read_text(encoding="utf-8")

    # 1. WHEEL_FILENAME alignment
    wheel_match = re.search(r'const\s+WHEEL_FILENAME\s*=\s*"([^"]+)"', worker_code)
    assert wheel_match is not None, "WHEEL_FILENAME not found in worker"
    worker_wheel_name = wheel_match.group(1)
    assert (web_sim / worker_wheel_name).exists(), f"Wheel {worker_wheel_name} missing from web/ root"

    # 2. DATA_FILES alignment
    data_files_match = re.findall(r'"([a-z_]+\.json)"', worker_code)
    assert len(data_files_match) >= 6, "Expected at least 6 data files defined in worker"
    for df in data_files_match:
        assert (web_sim / "data" / df).exists(), f"Data file {df} missing from web/data/"

    # 3. py/web_bridge.py alignment
    assert (web_sim / "py" / "web_bridge.py").exists(), "web/py/web_bridge.py missing"


def test_workflow_idempotence_dirty_rerun():
    """Verify that re-running the workflow commands over existing files does not corrupt layout or nest directories."""
    with tempfile.TemporaryDirectory(prefix="test_gha_dirty_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        repo_sim = tmp_dir / "fom-gift-planner"
        repo_sim.mkdir()

        # Copy sources
        for folder in ["fom_planner", "companion", "data", "samples"]:
            shutil.copytree(REPO_ROOT / folder, repo_sim / folder)
        shutil.copy2(REPO_ROOT / "pyproject.toml", repo_sim / "pyproject.toml")
        shutil.copy2(REPO_ROOT / "README.md", repo_sim / "README.md")

        web_sim = repo_sim / "web"
        web_sim.mkdir()
        for f in ["index.html", "style.css", "app.js", "planner.worker.js"]:
            shutil.copy2(REPO_ROOT / "web" / f, web_sim / f)
        shutil.copytree(REPO_ROOT / "web" / "py", web_sim / "py")

        # Setup Python venv
        venv_dir = tmp_dir / "venv"
        subprocess.run(f"python3 -m venv {venv_dir}", shell=True, check=True)
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = str(venv_dir)
        env["PATH"] = f"{venv_dir / 'bin'}:{env['PATH']}"
        subprocess.run("pip install build", shell=True, cwd=repo_sim, env=env, check=True)

        # Run 1:
        subprocess.run("python -m build --wheel --outdir web/", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("mkdir -p web/data && cp data/*.json web/data/", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("cp samples/sample_save.sav web/sample_save.sav", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("mkdir -p web/icons && cp -r companion/static/icons/* web/icons/", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("mkdir -p web/fonts && cp -r companion/static/fonts/* web/fonts/", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("touch web/.nojekyll", shell=True, cwd=repo_sim, env=env, check=True)

        # Run 2 (Dirty re-execution):
        subprocess.run("python -m build --wheel --outdir web/", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("mkdir -p web/data && cp data/*.json web/data/", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("cp samples/sample_save.sav web/sample_save.sav", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("mkdir -p web/icons && cp -r companion/static/icons/* web/icons/", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("mkdir -p web/fonts && cp -r companion/static/fonts/* web/fonts/", shell=True, cwd=repo_sim, env=env, check=True)
        subprocess.run("touch web/.nojekyll", shell=True, cwd=repo_sim, env=env, check=True)

        # Verify no directory nesting (e.g. icons/icons or items/items)
        assert not (web_sim / "icons" / "icons").exists(), "Found nested icons/icons!"
        assert not (web_sim / "icons" / "items" / "items").exists(), "Found nested items/items!"
        assert not (web_sim / "data" / "data").exists(), "Found nested data/data!"
        assert not (web_sim / "fonts" / "fonts").exists(), "Found nested fonts/fonts!"

        # Verify exactly 1 wheel file remains
        wheels = list(web_sim.glob("*.whl"))
        assert len(wheels) == 1, f"Expected 1 wheel after dirty rebuild, found {len(wheels)}"


def test_static_subpath_hosting_hygiene(simulated_workflow_clean):
    """
    Verify all asset links in web/ use relative paths suitable for GitHub Pages subpaths.
    (e.g., https://username.github.io/fom-gift-planner/)
    Root-relative URLs like '/icons/...' or '/data/...' break under subpaths.
    """
    _, web_sim, _ = simulated_workflow_clean

    html_text = (web_sim / "index.html").read_text(encoding="utf-8")
    js_text = (web_sim / "app.js").read_text(encoding="utf-8")
    css_text = (web_sim / "style.css").read_text(encoding="utf-8")

    # Check for unauthorized root-relative hrefs or srcs
    bad_root_patterns = [
        r'href="/(icons|data|fonts|style|app)',
        r'src="/(icons|data|fonts|app)',
        r'url\("/(icons|fonts)',
    ]
    for pat in bad_root_patterns:
        match = re.search(pat, html_text)
        assert match is None, f"Found root-relative URL in index.html: {match.group(0)}"
        match_css = re.search(pat, css_text)
        assert match_css is None, f"Found root-relative URL in style.css: {match_css.group(0)}"

    # Ensure zero /api/ calls
    assert "/api/" not in js_text
    assert "EventSource" not in js_text
