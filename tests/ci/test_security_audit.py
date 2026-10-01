"""
tests/test_ci_cd_security_challenge.py

Empirical security audit and adversarial challenge test suite for Milestone 4:
.github/workflows/deploy-web.yml

Validates:
1. Least-privilege permissions (whitelisted permissions, absence of write escalation).
2. Secret & credential leak prevention (no hardcoded tokens, PATs, private keys).
3. Script injection vulnerability audit (no untrusted ${{ ... }} in bash scripts).
4. Supply chain & action pinning (only trusted actions/*, pinned major versions, no @main/@master).
5. Trigger & boundary restrictions (push to main only, concurrency pages non-cancelling).
6. Strict schema & linter validation (check-jsonschema GitHub Actions schema, yamllint, formatting).
7. Empirical build & asset assembly simulation (wheel build, file copy idempotence, asset integrity).
"""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Set
import zipfile
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-web.yml"
WEB_DIR = REPO_ROOT / "web"


@pytest.fixture(scope="module")
def raw_workflow_text() -> str:
    assert WORKFLOW_PATH.exists(), f"Workflow missing at {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_dict(raw_workflow_text: str) -> Dict[str, Any]:
    data = yaml.safe_load(raw_workflow_text)
    assert isinstance(data, dict), "Workflow YAML did not parse to a dictionary"
    return data


# ==============================================================================
# 1. Least-Privilege Security & Permission Hardening
# ==============================================================================

def test_permissions_explicit_and_least_privilege(workflow_dict: Dict[str, Any]):
    """
    Verify strict least-privilege permissions:
    Only contents: read, pages: write, id-token: write are allowed.
    All high-risk permissions must be absent or not write.
    """
    perms = workflow_dict.get("permissions")
    assert perms is not None, "Top-level 'permissions' block is required to prevent default write-all"
    assert isinstance(perms, dict), "permissions must be a dictionary"

    allowed_permissions = {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }

    assert perms == allowed_permissions, (
        f"Permissions must exactly match least-privilege requirements: {allowed_permissions}, got: {perms}"
    )

    # Explicitly check for forbidden write permissions
    forbidden_write_scopes = [
        "actions",
        "checks",
        "deployments",
        "discussions",
        "issues",
        "packages",
        "pull-requests",
        "repository-projects",
        "security-events",
        "statuses",
    ]
    for scope in forbidden_write_scopes:
        assert perms.get(scope) != "write", f"Forbidden write permission granted for {scope}"


def test_no_write_all_or_read_all_shorthand(raw_workflow_text: str):
    """Verify permissions: write-all or read-all are not used."""
    assert "write-all" not in raw_workflow_text, "Workflow grants 'write-all' permissions"
    assert "read-all" not in raw_workflow_text, "Workflow should specify granular permissions, not 'read-all'"


def test_job_level_permissions_do_not_escalate(workflow_dict: Dict[str, Any]):
    """Ensure no job overrides top-level permissions with elevated privileges."""
    jobs = workflow_dict.get("jobs", {})
    for job_name, job_cfg in jobs.items():
        if "permissions" in job_cfg:
            job_perms = job_cfg["permissions"]
            if isinstance(job_perms, dict):
                for k, v in job_perms.items():
                    if v == "write":
                        assert k in {"pages", "id-token"}, f"Job '{job_name}' grants write to {k}"


# ==============================================================================
# 2. Hardcoded Secrets & Token Leaks Prevention
# ==============================================================================

def test_no_hardcoded_credentials_or_tokens(raw_workflow_text: str):
    """
    Adversarial regex scan for API tokens, PATs, cloud keys, and private keys.
    """
    secret_patterns = [
        (r"ghp_[A-Za-z0-9_]{36,}", "GitHub Personal Access Token (classic)"),
        (r"github_pat_[A-Za-z0-9_]{82,}", "GitHub Fine-Grained Personal Access Token"),
        (r"gho_[A-Za-z0-9_]{36,}", "GitHub OAuth Access Token"),
        (r"ghs_[A-Za-z0-9_]{36,}", "GitHub Server-to-Server Token"),
        (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
        (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "Private cryptographic key"),
        (r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}", "Hardcoded Bearer authorization header"),
        (r"(?i)api[_-]?key\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]", "Hardcoded API key"),
        (r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9]*", "Slack API token"),
    ]

    for pattern, description in secret_patterns:
        match = re.search(pattern, raw_workflow_text)
        assert match is None, f"Security risk: {description} detected in workflow: {match.group(0) if match else ''}"


def test_no_secrets_context_exfiltration_in_run(raw_workflow_text: str):
    """Verify secrets context is not referenced or logged in run steps."""
    assert "secrets." not in raw_workflow_text, "Workflow should not reference repository secrets for static deployment"


# ==============================================================================
# 3. Script Injection Vulnerability Audit
# ==============================================================================

def test_zero_expression_injection_in_run_scripts(workflow_dict: Dict[str, Any]):
    """
    Verify that NO run: script contains `${{ ... }}` expression interpolation.
    Embedding GitHub expressions inside bash strings allows arbitrary code injection.
    """
    jobs = workflow_dict.get("jobs", {})
    for job_name, job_data in jobs.items():
        steps = job_data.get("steps", [])
        for idx, step in enumerate(steps):
            step_name = step.get("name", f"step_{idx}")
            run_cmd = step.get("run")
            if run_cmd:
                injections = re.findall(r"\$\{\{\s*([^\}]+)\s*\}\}", run_cmd)
                assert not injections, (
                    f"Script injection hazard in job '{job_name}', step '{step_name}': "
                    f"Found ${{ ... }} expression: {injections}"
                )


def test_no_external_network_exfiltration_calls_in_run(workflow_dict: Dict[str, Any]):
    """Ensure run commands do not download unverified binaries or curl untrusted URLs."""
    forbidden_commands = ["curl", "wget", "nc", "socat", "base64 -d"]
    jobs = workflow_dict.get("jobs", {})
    for job_name, job_data in jobs.items():
        steps = job_data.get("steps", [])
        for idx, step in enumerate(steps):
            run_cmd = step.get("run", "")
            for cmd in forbidden_commands:
                # Check for standalone command call
                pattern = rf"\b{re.escape(cmd)}\b"
                assert not re.search(pattern, run_cmd), (
                    f"Potentially risky command '{cmd}' found in job '{job_name}' step {idx}: '{run_cmd}'"
                )


# ==============================================================================
# 4. Supply Chain Security & Action Version Pinning
# ==============================================================================

def test_all_actions_from_official_github_org(workflow_dict: Dict[str, Any]):
    """
    Verify every action used belongs to the official 'actions/' GitHub organization.
    No unverified third-party marketplace actions allowed.
    """
    jobs = workflow_dict.get("jobs", {})
    for job_name, job_data in jobs.items():
        steps = job_data.get("steps", [])
        for idx, step in enumerate(steps):
            uses = step.get("uses")
            if uses:
                action_name = uses.split("@")[0]
                assert action_name.startswith("actions/"), (
                    f"Third-party action detected in job '{job_name}', step {idx}: {uses}. "
                    "Only official 'actions/*' actions are permitted."
                )


def test_action_versions_are_strictly_pinned_and_not_floating_branches(workflow_dict: Dict[str, Any]):
    """
    Verify that actions are pinned to major releases (e.g., @v4) and not floating branches like @main or @master.
    """
    jobs = workflow_dict.get("jobs", {})
    for job_name, job_data in jobs.items():
        steps = job_data.get("steps", [])
        for idx, step in enumerate(steps):
            uses = step.get("uses")
            if uses:
                assert "@" in uses, f"Action without version pin in step {idx}: {uses}"
                action_part, version_part = uses.split("@", 1)
                assert version_part not in {"main", "master", "latest", "head", "dev"}, (
                    f"Action '{action_part}' uses floating branch '@{version_part}' in step {idx}"
                )
                assert re.match(r"^v\d+(\.\d+)*$", version_part) or re.match(r"^[0-9a-f]{40}$", version_part), (
                    f"Action '{uses}' version tag format unexpected: '{version_part}'"
                )


# ==============================================================================
# 5. Trigger Restrictions & Concurrency Safety
# ==============================================================================

def test_trigger_restricted_to_main_branch(workflow_dict: Dict[str, Any]):
    """Verify triggers are strictly restricted to push on main and workflow_dispatch."""
    triggers = workflow_dict.get("on") or workflow_dict.get(True)
    assert triggers is not None, "Workflow triggers missing"

    assert "pull_request" not in triggers, "pull_request trigger must not deploy to GitHub Pages"
    assert "pull_request_target" not in triggers, "pull_request_target trigger is highly insecure and must not be used"
    assert "schedule" not in triggers, "Scheduled triggers not needed for static deployment"

    if isinstance(triggers, dict):
        push_cfg = triggers.get("push", {})
        branches = push_cfg.get("branches", [])
        assert branches == ["main"], f"Push trigger must only target ['main'], got: {branches}"


def test_concurrency_group_pages_cancel_in_progress_false(workflow_dict: Dict[str, Any]):
    """
    Verify concurrency settings: group: pages, cancel-in-progress: false.
    GitHub Pages deploys must not be cancelled mid-flight to avoid corrupted state.
    """
    concurrency = workflow_dict.get("concurrency", {})
    assert concurrency.get("group") == "pages", f"Concurrency group must be 'pages', got {concurrency.get('group')}"
    assert concurrency.get("cancel-in-progress") is False, "Concurrency cancel-in-progress must be false"


# ==============================================================================
# 6. Strict Schema Validation & Linters
# ==============================================================================

def test_schema_validation_via_check_jsonschema():
    """Run check-jsonschema against the official GitHub Actions workflow schema."""
    cmd = [
        "uvx",
        "check-jsonschema",
        "--builtin-schema",
        "github-workflows",
        str(WORKFLOW_PATH),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert res.returncode == 0, f"check-jsonschema validation failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


def test_yamllint_validation():
    """Run yamllint on deploy-web.yml."""
    cmd = ["uvx", "yamllint", "-d", "{rules: {document-start: disable}}", str(WORKFLOW_PATH)]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert res.returncode == 0, f"yamllint failed with errors:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


def test_line_endings_and_whitespace_cleanliness(raw_workflow_text: str):
    """Verify UNIX line endings and absence of trailing whitespace."""
    assert "\r\n" not in raw_workflow_text, "Workflow must use UNIX LF line endings, found CRLF"
    lines = raw_workflow_text.split("\n")
    trailing_ws_lines = [i + 1 for i, line in enumerate(lines) if line.endswith(" ") or line.endswith("\t")]
    assert not trailing_ws_lines, f"Trailing whitespace detected on lines: {trailing_ws_lines}"


# ==============================================================================
# 7. Empirical Build & Assembly Execution Simulation
# ==============================================================================

def test_empirical_wheel_build_command():
    """
    Empirically execute the exact build command from workflow step 4:
    python -m build --wheel --outdir <temp_dir>
    Verify wheel contents and package integrity.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir)
        cmd = ["uv", "run", "python", "-m", "build", "--wheel", "--outdir", str(outdir)]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert res.returncode == 0, f"Wheel build failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

        wheels = list(outdir.glob("*.whl"))
        assert len(wheels) == 1, f"Expected exactly 1 wheel file, found: {wheels}"
        wheel_path = wheels[0]
        assert wheel_path.name.startswith("fom_gift_planner-1.2.0-py3-none-any.whl"), (
            f"Unexpected wheel name: {wheel_path.name}"
        )

        # Inspect wheel contents
        with zipfile.ZipFile(wheel_path, "r") as zf:
            namelist = zf.namelist()
            # Must include fom_planner modules
            planner_files = [f for f in namelist if f.startswith("fom_planner/")]
            assert len(planner_files) >= 6, f"fom_planner files missing from wheel: {namelist}"
            # Must include companion modules
            companion_files = [f for f in namelist if f.startswith("companion/")]
            assert len(companion_files) >= 3, f"companion files missing from wheel: {namelist}"


def test_empirical_assembly_pipeline_simulation():
    """
    Simulate the complete asset assembly pipeline (steps 4 through 9):
    - Build wheel to web/
    - Copy data/*.json to web/data/
    - Copy samples/sample_save.sav to web/sample_save.sav
    - Copy companion/static/icons/* to web/icons/
    - Copy companion/static/fonts/* to web/fonts/
    - Create web/.nojekyll
    Verify all files in temporary mirror directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_web = Path(tmpdir) / "web"
        temp_web.mkdir(parents=True)

        # 1. Wheel build
        cmd_wheel = ["uv", "run", "python", "-m", "build", "--wheel", "--outdir", str(temp_web)]
        res_wheel = subprocess.run(cmd_wheel, capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert res_wheel.returncode == 0, "Wheel build failed in simulation"

        # 2. Copy static data files
        (temp_web / "data").mkdir(parents=True)
        for json_file in (REPO_ROOT / "data").glob("*.json"):
            shutil.copy2(json_file, temp_web / "data")
        assert len(list((temp_web / "data").glob("*.json"))) >= 6

        # 3. Copy demo save
        shutil.copy2(REPO_ROOT / "samples" / "sample_save.sav", temp_web / "sample_save.sav")
        assert (temp_web / "sample_save.sav").stat().st_size > 0

        # 4. Copy icons
        shutil.copytree(REPO_ROOT / "companion" / "static" / "icons", temp_web / "icons")
        assert (temp_web / "icons" / "items").is_dir()
        assert (temp_web / "icons" / "npcs").is_dir()
        assert len(list((temp_web / "icons" / "items").glob("*.png"))) >= 180

        # 5. Copy fonts
        shutil.copytree(REPO_ROOT / "companion" / "static" / "fonts", temp_web / "fonts")
        assert (temp_web / "fonts" / "fnt_nosutaru.ttf").is_file()

        # 6. Touch .nojekyll
        (temp_web / ".nojekyll").touch()
        assert (temp_web / ".nojekyll").is_file()


def test_deployed_web_directory_contains_complete_runtime():
    """
    Verify that the existing repo web/ directory is already packaged and complete,
    matching what the CI pipeline will assemble and deploy.
    """
    assert (WEB_DIR / "index.html").is_file()
    assert (WEB_DIR / "style.css").is_file()
    assert (WEB_DIR / "app.js").is_file()
    assert (WEB_DIR / "planner.worker.js").is_file()
    assert (WEB_DIR / "sample_save.sav").is_file()
    assert (WEB_DIR / ".nojekyll").is_file()
    assert (WEB_DIR / "py" / "web_bridge.py").is_file()
    assert (WEB_DIR / "data").is_dir()
    assert len(list((WEB_DIR / "data").glob("*.json"))) >= 6
    assert (WEB_DIR / "icons" / "items").is_dir()
    assert (WEB_DIR / "fonts" / "fnt_nosutaru.ttf").is_file()
    assert len(list(WEB_DIR.glob("*.whl"))) >= 1
