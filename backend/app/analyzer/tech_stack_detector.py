import json
import re
import tomllib
from pathlib import Path

# Dependency name (as it appears in package.json) -> display name.
PACKAGE_JSON_FRAMEWORKS: dict[str, str] = {
    "react": "React",
    "react-dom": "React",
    "next": "Next.js",
    "express": "Express",
    "vite": "Vite",
    "socket.io": "Socket.IO",
    "socket.io-client": "Socket.IO",
    "axios": "Axios",
    "mongoose": "Mongoose",
    "vue": "Vue.js",
    "@angular/core": "Angular",
    "svelte": "Svelte",
    "@nestjs/core": "NestJS",
    "tailwindcss": "Tailwind CSS",
    "@tanstack/react-query": "React Query",
}

# Package name (as it appears in requirements.txt, lowercased) -> display name.
REQUIREMENTS_TXT_FRAMEWORKS: dict[str, str] = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "numpy": "NumPy",
    "pandas": "Pandas",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "gitpython": "GitPython",
    "uvicorn": "Uvicorn",
}

# Manifest filename -> technology it signals just by existing.
OTHER_MANIFESTS: dict[str, str] = {
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "composer.json": "PHP (Composer)",
    "pom.xml": "Java (Maven)",
    "pubspec.yaml": "Dart/Flutter",
}


class TechStackDetector:
    """Detects frameworks/technologies from manifest files.

    Takes the file list FileScanner already produced instead of walking the
    disk again — one traversal total, and it naturally supports monorepos
    (multiple package.json/requirements.txt at different depths) since it
    just filters by filename rather than assuming a fixed root layout.
    """

    def __init__(self, root: Path, scanned_paths: list[str]):
        self.root = root
        self.scanned_paths = scanned_paths

    def detect(self) -> list[str]:
        frameworks: set[str] = set()
        for relative_path in self.scanned_paths:
            filename = Path(relative_path).name
            if filename == "package.json":
                frameworks |= self._parse_package_json(relative_path)
            elif filename == "requirements.txt":
                frameworks |= self._parse_requirements_txt(relative_path)
            elif filename == "pyproject.toml":
                frameworks |= self._parse_pyproject_toml(relative_path)
            elif filename in OTHER_MANIFESTS:
                frameworks.add(OTHER_MANIFESTS[filename])
        return sorted(frameworks)

    def _parse_package_json(self, relative_path: str) -> set[str]:
        try:
            data = json.loads((self.root / relative_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()

        dependencies = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        return {
            display_name
            for package_name, display_name in PACKAGE_JSON_FRAMEWORKS.items()
            if package_name in dependencies
        }

    def _parse_requirements_txt(self, relative_path: str) -> set[str]:
        try:
            lines = (self.root / relative_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return set()

        return self._match_python_requirement_strings(lines)

    def _parse_pyproject_toml(self, relative_path: str) -> set[str]:
        """PEP 621 (`[project.dependencies]` / `[project.optional-dependencies]`)
        and Poetry (`[tool.poetry.dependencies]`) are both dependency
        manifests just as real as requirements.txt -- most modern Python
        projects declare dependencies here instead, so skipping this file
        would silently miss their actual tech stack evidence."""
        try:
            data = tomllib.loads((self.root / relative_path).read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return set()

        requirement_strings: list[str] = list(data.get("project", {}).get("dependencies", []))
        for extra_dependencies in data.get("project", {}).get("optional-dependencies", {}).values():
            requirement_strings.extend(extra_dependencies)

        poetry_dependencies = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        requirement_strings.extend(poetry_dependencies.keys())

        return self._match_python_requirement_strings(requirement_strings)

    @staticmethod
    def _match_python_requirement_strings(requirement_strings: list[str]) -> set[str]:
        detected: set[str] = set()
        for requirement in requirement_strings:
            package_name = re.split(r"[=<>!~\[; ]", requirement.strip().lower())[0]
            if package_name in REQUIREMENTS_TXT_FRAMEWORKS:
                detected.add(REQUIREMENTS_TXT_FRAMEWORKS[package_name])
        return detected
