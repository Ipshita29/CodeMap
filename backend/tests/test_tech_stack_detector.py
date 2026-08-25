from pathlib import Path

from repository import TechStackDetector


def test_detects_frameworks_from_pep621_pyproject_dependencies(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "demo"\n'
        "dependencies = [\n"
        '    "fastapi>=0.100",\n'
        '    "pydantic>=2.0",\n'
        "]\n\n"
        "[project.optional-dependencies]\n"
        'dev = ["uvicorn[standard]"]\n'
    )

    frameworks = TechStackDetector(tmp_path, ["pyproject.toml"]).detect()

    assert frameworks == ["FastAPI", "Pydantic", "Uvicorn"]


def test_detects_frameworks_from_poetry_style_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        'django = "^5.0"\n'
    )

    frameworks = TechStackDetector(tmp_path, ["pyproject.toml"]).detect()

    assert frameworks == ["Django"]


def test_does_not_claim_a_framework_with_no_manifest_evidence(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\ndependencies = ["requests"]\n')

    frameworks = TechStackDetector(tmp_path, ["pyproject.toml"]).detect()

    assert frameworks == []
