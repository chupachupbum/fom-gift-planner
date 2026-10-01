"""
tests/test_ci_cd_contract.py

Contract, syntax, and specification tests for GitHub Actions CI/CD deployment
workflow (.github/workflows/deploy-web.yml) and static web deployment markers.
Verifies conformity with PROJECT.md and ORIGINAL_REQUEST.md requirements.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-web.yml"
NOJEKYLL_PATH = REPO_ROOT / "web" / ".nojekyll"


@pytest.fixture(scope="module")
def workflow_content() -> str:
    """Fixture providing raw text content of deploy-web.yml."""
    assert WORKFLOW_PATH.exists(), f"Workflow file missing at {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_content: str) -> Dict[str, Any]:
    """Fixture providing parsed YAML dictionary of deploy-web.yml."""
    parsed = yaml.safe_load(workflow_content)
    assert isinstance(parsed, dict), "Parsed workflow YAML must be a dictionary"
    return parsed


@pytest.fixture(scope="module")
def deploy_job(workflow_yaml: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the primary deployment job from workflow YAML."""
    jobs = workflow_yaml.get("jobs", {})
    assert isinstance(jobs, dict), "Workflow 'jobs' must be a dictionary"
    assert len(jobs) > 0, "Workflow must define at least one job"

    # Find the job with environment github-pages or runs-on ubuntu-latest
    for job_name, job_data in jobs.items():
        if isinstance(job_data, dict):
            env = job_data.get("environment")
            if env == "github-pages" or (isinstance(env, dict) and env.get("name") == "github-pages"):
                return job_data
    # Fallback to the first job if not explicitly named github-pages
    first_job = next(iter(jobs.values()))
    assert isinstance(first_job, dict), "Job definition must be a dictionary"
    return first_job


@pytest.fixture(scope="module")
def job_steps(deploy_job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract list of steps from the deploy job."""
    steps = deploy_job.get("steps", [])
    assert isinstance(steps, list), "Job 'steps' must be a list"
    assert len(steps) > 0, "Job must have at least one step"
    return steps


# ==============================================================================
# 1. Workflow File & YAML Validity Tests
# ==============================================================================

def test_workflow_file_exists():
    """Verify that .github/workflows/deploy-web.yml exists and is a file."""
    assert WORKFLOW_PATH.exists(), f"File does not exist: {WORKFLOW_PATH}"
    assert WORKFLOW_PATH.is_file(), f"Path is not a regular file: {WORKFLOW_PATH}"


def test_workflow_file_is_non_empty(workflow_content: str):
    """Verify that deploy-web.yml has non-trivial content."""
    assert len(workflow_content.strip()) > 50, "deploy-web.yml is empty or too short"


def test_workflow_parses_as_valid_yaml(workflow_yaml: Dict[str, Any]):
    """Verify that deploy-web.yml parses cleanly without YAML errors."""
    assert "name" in workflow_yaml, "Workflow must define a top-level 'name'"
    assert ("on" in workflow_yaml or True in workflow_yaml), "Workflow must define 'on' triggers"
    assert "jobs" in workflow_yaml, "Workflow must define 'jobs'"


def test_workflow_no_tabs_or_corruptions(workflow_content: str):
    """Verify formatting hygiene: no raw tabs (valid YAML standard)."""
    assert "\t" not in workflow_content, "deploy-web.yml contains tabs; YAML standard requires spaces"


# ==============================================================================
# 2. Trigger Specifications
# ==============================================================================

def test_workflow_triggers_present(workflow_yaml: Dict[str, Any]):
    """Verify workflow contains push and workflow_dispatch triggers."""
    triggers = workflow_yaml.get("on")
    if triggers is None and True in workflow_yaml:
        triggers = workflow_yaml[True]
    assert triggers is not None, "Workflow missing 'on' triggers"

    if isinstance(triggers, list):
        # e.g., on: [push, workflow_dispatch]
        assert "push" in triggers, "'push' trigger missing from 'on' list"
        assert "workflow_dispatch" in triggers, "'workflow_dispatch' trigger missing from 'on' list"
    elif isinstance(triggers, dict):
        assert "push" in triggers, "'push' trigger missing from 'on' dict"
        assert "workflow_dispatch" in triggers, "'workflow_dispatch' trigger missing from 'on' dict"

        # Verify branch is 'main'
        push_cfg = triggers["push"]
        if isinstance(push_cfg, dict):
            branches = push_cfg.get("branches", [])
            assert "main" in branches, f"'push' trigger must target 'main' branch, got {branches}"


# ==============================================================================
# 3. Permissions Specifications
# ==============================================================================

def test_workflow_permissions(workflow_yaml: Dict[str, Any]):
    """Verify workflow grants required permissions for GitHub Pages deployment."""
    permissions = workflow_yaml.get("permissions")
    assert isinstance(permissions, dict), "Workflow must declare top-level 'permissions' dictionary"

    assert permissions.get("contents") == "read", "Expected 'contents: read' permission"
    assert permissions.get("pages") == "write", "Expected 'pages: write' permission"
    assert permissions.get("id-token") == "write", "Expected 'id-token: write' permission"


# ==============================================================================
# 4. Concurrency Specifications
# ==============================================================================

def test_workflow_concurrency(workflow_yaml: Dict[str, Any]):
    """Verify pages concurrency group and non-cancellation setting."""
    concurrency = workflow_yaml.get("concurrency")
    assert isinstance(concurrency, dict), "Workflow should define 'concurrency' settings"
    assert concurrency.get("group") == "pages", "Concurrency group must be 'pages'"
    assert concurrency.get("cancel-in-progress") is False, "Concurrency 'cancel-in-progress' must be false"


# ==============================================================================
# 5. Environment & Runner Specifications
# ==============================================================================

def test_job_environment_and_runner(deploy_job: Dict[str, Any]):
    """Verify job runs on ubuntu-latest and targets github-pages environment."""
    runs_on = deploy_job.get("runs-on")
    assert runs_on == "ubuntu-latest", f"Job must run on 'ubuntu-latest', found {runs_on}"

    environment = deploy_job.get("environment")
    assert environment is not None, "Job must specify an 'environment'"

    if isinstance(environment, dict):
        assert environment.get("name") == "github-pages", "Environment name must be 'github-pages'"
        assert "steps.deployment.outputs.page_url" in str(environment.get("url")), (
            "Environment url must reference deployment step output: ${{ steps.deployment.outputs.page_url }}"
        )
    else:
        assert environment == "github-pages", f"Environment must be 'github-pages', got {environment}"


# ==============================================================================
# 6. Step-by-Step Contract Verification
# ==============================================================================

def _find_step_by_uses(steps: List[Dict[str, Any]], action_prefix: str) -> Optional[Dict[str, Any]]:
    for step in steps:
        uses = step.get("uses", "")
        if uses.startswith(action_prefix):
            return step
    return None


def _find_step_by_run_content(steps: List[Dict[str, Any]], snippet: str) -> Optional[Dict[str, Any]]:
    for step in steps:
        run_cmd = step.get("run", "")
        if snippet in run_cmd:
            return step
    return None


def test_checkout_step(job_steps: List[Dict[str, Any]]):
    """Verify actions/checkout@v4 step is present."""
    step = _find_step_by_uses(job_steps, "actions/checkout@v4")
    assert step is not None, "Step using 'actions/checkout@v4' is required"


def test_setup_python_step(job_steps: List[Dict[str, Any]]):
    """Verify actions/setup-python@v5 step is configured for Python 3.12."""
    step = _find_step_by_uses(job_steps, "actions/setup-python@v5")
    assert step is not None, "Step using 'actions/setup-python@v5' is required"
    with_cfg = step.get("with", {})
    assert str(with_cfg.get("python-version")) == "3.12", "setup-python must specify python-version: '3.12'"


def test_install_build_tool_step(job_steps: List[Dict[str, Any]]):
    """Verify pip install build step is present."""
    step = _find_step_by_run_content(job_steps, "pip install build")
    assert step is not None, "Step installing 'build' tool (pip install build) is required"


def test_build_wheel_step(job_steps: List[Dict[str, Any]]):
    """Verify python -m build --wheel --outdir web/ step is present."""
    step = _find_step_by_run_content(job_steps, "python -m build --wheel --outdir web/")
    assert step is not None, "Step running 'python -m build --wheel --outdir web/' is required"


def test_copy_static_data_files_step(job_steps: List[Dict[str, Any]]):
    """Verify copy data files to web/data/ step is present."""
    # Look for copy command targeting web/data
    step = _find_step_by_run_content(job_steps, "web/data")
    assert step is not None, "Step copying data files to web/data/ is required"
    assert "data/" in step.get("run", ""), "Data copy step must reference data/ source"


def test_copy_demo_save_step(job_steps: List[Dict[str, Any]]):
    """Verify copy demo save to web/sample_save.sav step is present."""
    step = _find_step_by_run_content(job_steps, "samples/sample_save.sav")
    assert step is not None, "Step copying samples/sample_save.sav to web/sample_save.sav is required"
    assert "web/sample_save.sav" in step.get("run", ""), "Destination must be web/sample_save.sav"


def test_copy_icons_step(job_steps: List[Dict[str, Any]]):
    """Verify copy icons to web/icons/ step is present."""
    step = _find_step_by_run_content(job_steps, "companion/static/icons")
    assert step is not None, "Step copying companion/static/icons to web/icons/ is required"
    assert "web/icons" in step.get("run", ""), "Destination must be web/icons/"


def test_copy_fonts_step(job_steps: List[Dict[str, Any]]):
    """Verify copy fonts to web/fonts/ step is present."""
    step = _find_step_by_run_content(job_steps, "companion/static/fonts")
    assert step is not None, "Step copying companion/static/fonts to web/fonts/ is required"
    assert "web/fonts" in step.get("run", ""), "Destination must be web/fonts/"


def test_create_nojekyll_in_workflow_step(job_steps: List[Dict[str, Any]]):
    """Verify workflow step creates web/.nojekyll."""
    step = _find_step_by_run_content(job_steps, "web/.nojekyll")
    assert step is not None, "Step ensuring web/.nojekyll is present is required"


def test_configure_pages_step(job_steps: List[Dict[str, Any]]):
    """Verify actions/configure-pages@v5 step is present."""
    step = _find_step_by_uses(job_steps, "actions/configure-pages@v5")
    assert step is not None, "Step using 'actions/configure-pages@v5' is required"


def test_upload_pages_artifact_step(job_steps: List[Dict[str, Any]]):
    """Verify actions/upload-pages-artifact@v3 step is present with path: web."""
    step = _find_step_by_uses(job_steps, "actions/upload-pages-artifact@v3")
    assert step is not None, "Step using 'actions/upload-pages-artifact@v3' is required"
    with_cfg = step.get("with", {})
    path = with_cfg.get("path", "")
    assert path.rstrip("/") == "web", f"upload-pages-artifact path must be 'web', got '{path}'"


def test_deploy_pages_step(job_steps: List[Dict[str, Any]]):
    """Verify actions/deploy-pages@v4 step is present with id: deployment."""
    step = _find_step_by_uses(job_steps, "actions/deploy-pages@v4")
    assert step is not None, "Step using 'actions/deploy-pages@v4' is required"
    assert step.get("id") == "deployment", "deploy-pages step must have id: 'deployment'"


def test_step_sequence_order(job_steps: List[Dict[str, Any]]):
    """Verify that workflow steps are executed in correct logical order."""
    def get_step_idx(predicate):
        for i, s in enumerate(job_steps):
            if predicate(s):
                return i
        return -1

    idx_checkout = get_step_idx(lambda s: s.get("uses", "").startswith("actions/checkout"))
    idx_setup_python = get_step_idx(lambda s: s.get("uses", "").startswith("actions/setup-python"))
    idx_build_tool = get_step_idx(lambda s: "pip install build" in s.get("run", ""))
    idx_build_wheel = get_step_idx(lambda s: "python -m build --wheel" in s.get("run", ""))
    idx_copy_data = get_step_idx(lambda s: "web/data" in s.get("run", ""))
    idx_upload = get_step_idx(lambda s: s.get("uses", "").startswith("actions/upload-pages-artifact"))
    idx_deploy = get_step_idx(lambda s: s.get("uses", "").startswith("actions/deploy-pages"))

    assert 0 <= idx_checkout < idx_setup_python, "Checkout must occur before Python setup"
    assert idx_setup_python < idx_build_tool, "Python setup must occur before installing build tool"
    assert idx_build_tool < idx_build_wheel, "Installing build tool must occur before building wheel"
    assert idx_build_wheel < idx_upload, "Wheel build must occur before uploading Pages artifact"
    assert idx_copy_data < idx_upload, "Static assets copy must occur before uploading Pages artifact"
    assert idx_upload < idx_deploy, "Uploading artifact must occur before deploying to Pages"


# ==============================================================================
# 7. Static Asset & Marker File Invariants
# ==============================================================================

def test_web_nojekyll_file_exists():
    """Verify that web/.nojekyll exists in the repository."""
    assert NOJEKYLL_PATH.exists(), f"web/.nojekyll missing at {NOJEKYLL_PATH}"
    assert NOJEKYLL_PATH.is_file(), f"web/.nojekyll must be a regular file: {NOJEKYLL_PATH}"


# ==============================================================================
# 8. Source Paths & Asset Integrity Referenced by Workflow
# ==============================================================================

def test_workflow_referenced_source_assets_exist():
    """Verify that all source assets referenced by the CI workflow exist in repo."""
    data_dir = REPO_ROOT / "data"
    assert data_dir.is_dir(), f"data/ directory must exist at {data_dir}"
    data_jsons = list(data_dir.glob("*.json"))
    assert len(data_jsons) >= 6, f"Expected at least 6 data JSON files in data/, found {len(data_jsons)}"

    sample_save = REPO_ROOT / "samples" / "sample_save.sav"
    assert sample_save.is_file(), f"samples/sample_save.sav must exist at {sample_save}"
    assert sample_save.stat().st_size > 0, "sample_save.sav must not be empty"

    icons_dir = REPO_ROOT / "companion" / "static" / "icons"
    assert icons_dir.is_dir(), f"companion/static/icons must exist at {icons_dir}"
    assert (icons_dir / "items").is_dir(), "companion/static/icons/items must exist"
    assert (icons_dir / "npcs").is_dir(), "companion/static/icons/npcs must exist"

    fonts_dir = REPO_ROOT / "companion" / "static" / "fonts"
    assert fonts_dir.is_dir(), f"companion/static/fonts must exist at {fonts_dir}"
    fonts = list(fonts_dir.glob("*.ttf")) + list(fonts_dir.glob("*.woff*"))
    assert len(fonts) > 0, f"Expected font file in {fonts_dir}"


# ==============================================================================
# 9. Security & Cleanliness Invariants
# ==============================================================================

def test_workflow_security_no_unnecessary_write_permissions(workflow_yaml: Dict[str, Any]):
    """Verify principle of least privilege: only pages and id-token have write."""
    permissions = workflow_yaml.get("permissions", {})
    for scope, level in permissions.items():
        if level == "write":
            assert scope in {"pages", "id-token"}, f"Unexpected write permission granted for {scope}"


def test_workflow_no_hardcoded_secrets_or_tokens(workflow_content: str):
    """Verify workflow contains no hardcoded secrets or personal access tokens."""
    patterns = ["ghp_", "github_pat_", "Bearer ", "PRIVATE KEY"]
    for pattern in patterns:
        assert pattern not in workflow_content, f"Potential sensitive token/secret '{pattern}' found in workflow"

