"""Deterministic, heuristic repository health analysis.

Every check here is explicit and explainable -- no AI is involved in
producing a finding or a score. This is intentionally a *structural*
signal (file sizes, test-file presence, README presence, import-graph
shape), not a code-quality or security scanner, and the wording of every
finding is written to avoid overclaiming (e.g. "no test files were
detected" rather than "this codebase is untested" or "poorly tested").
"""

from __future__ import annotations

import json
import posixpath
from pathlib import Path

from app.graph.relationship_index import RelationshipIndex, external_package_name
from app.health.health_models import HealthCategories, HealthFinding, HealthResponse

# -- Structure -----------------------------------------------------------

LARGE_FILE_MEDIUM_LINES = 500
LARGE_FILE_HIGH_LINES = 1000
LARGE_FOLDER_FILE_COUNT = 40
DEEP_NESTING_DEPTH = 6
MAX_STRUCTURE_FINDINGS = 15

SECRET_FILE_BASENAMES = {
    ".env", ".env.local", ".env.development", ".env.production", ".env.test",
    "credentials.json", "secrets.json", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}
SECRET_FILE_SUFFIXES = (".pem", ".key", ".pfx", ".p12")

# Auto-generated lockfiles: real line counts, but "split this file's
# responsibilities" is meaningless advice for a machine-written manifest.
LOCKFILE_BASENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "composer.lock", "go.sum",
}

# -- Dependencies ----------------------------------------------------------

# Common tooling that's configured, not imported -- flagging these as
# "unused" would be a false positive on virtually every JS/TS repo.
BUILD_ONLY_PACKAGES = {
    "vite", "eslint", "prettier", "tailwindcss", "postcss", "autoprefixer",
    "typescript", "vitest", "jest", "nodemon", "concurrently", "cross-env",
    "@vitejs/plugin-react", "@types/node", "@types/react", "@types/react-dom",
    "husky", "lint-staged", "rimraf",
}
OVERLAPPING_PACKAGE_GROUPS = [
    {"moment", "dayjs", "date-fns", "luxon"},
    {"axios", "node-fetch", "got", "superagent"},
    {"lodash", "underscore", "ramda"},
    {"redux", "mobx", "zustand", "recoil"},
    {"jest", "mocha", "ava", "vitest"},
]
MAX_UNUSED_DEP_FINDINGS = 8
MAX_PACKAGE_JSON_FILES = 5

# -- Complexity ------------------------------------------------------------

LARGE_FUNCTION_MEDIUM_LINES = 80
LARGE_FUNCTION_HIGH_LINES = 150
LARGE_CLASS_MEDIUM_LINES = 300
LARGE_CLASS_HIGH_LINES = 600
MAX_COMPLEXITY_FINDINGS = 15

# -- Architecture ------------------------------------------------------------

MAX_CYCLES_REPORTED = 5
COUPLING_MIN_THRESHOLD = 15
COUPLING_RATIO_OF_REPO = 0.3
MAX_COUPLING_FINDINGS = 5

# -- Testing -----------------------------------------------------------------

TEST_PATH_SEGMENTS = ("tests/", "__tests__/", "test/")
TEST_FILENAME_SUFFIXES = (".test.js", ".test.jsx", ".test.ts", ".test.tsx", ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx")
LOW_TEST_RATIO = 0.05
LOW_TEST_RATIO_MIN_SOURCE_FILES = 20

README_NAMES = {"readme.md", "readme", "readme.rst", "readme.txt"}
README_EMPTY_CHARS = 50
README_THIN_CHARS = 300


def _is_test_file(path: str) -> bool:
    lower = path.lower()
    if any(segment in lower for segment in TEST_PATH_SEGMENTS):
        return True
    name = posixpath.basename(lower)
    if any(name.endswith(suffix) for suffix in TEST_FILENAME_SUFFIXES):
        return True
    return name.startswith("test_") and name.endswith(".py") or (name.endswith("_test.py"))


def _is_secret_file(path: str) -> bool:
    name = posixpath.basename(path)
    if name.lower() in SECRET_FILE_BASENAMES:
        return True
    return name.lower().endswith(SECRET_FILE_SUFFIXES)


def _find_import_cycles(adjacency: dict[str, list[str]], max_cycles: int) -> list[list[str]]:
    """Standard white/gray/black DFS cycle detection over the imports-only
    file graph. Stops early once `max_cycles` are found -- a health check
    needs examples, not an exhaustive enumeration."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    cycles: list[list[str]] = []
    path: list[str] = []

    def dfs(node: str) -> None:
        if len(cycles) >= max_cycles:
            return
        color[node] = GRAY
        path.append(node)
        for neighbor in adjacency.get(node, []):
            if len(cycles) >= max_cycles:
                break
            state = color.get(neighbor, WHITE)
            if state == WHITE:
                dfs(neighbor)
            elif state == GRAY:
                start = path.index(neighbor)
                cycles.append([*path[start:], neighbor])
        path.pop()
        color[node] = BLACK

    for node in list(adjacency.keys()):
        if len(cycles) >= max_cycles:
            break
        if color.get(node, WHITE) == WHITE:
            dfs(node)

    return cycles


class HealthAnalyzer:
    def __init__(self, repository_path: Path, day2_result, intelligence: dict, index: RelationshipIndex):
        self.repository_path = repository_path
        self.day2_result = day2_result
        self.intelligence = intelligence
        self.index = index

    def analyze(self) -> HealthResponse:
        findings: list[HealthFinding] = []

        structure_score, structure_findings = self._check_structure()
        dependency_score, dependency_findings = self._check_dependencies()
        complexity_score, complexity_findings = self._check_complexity()
        architecture_score, architecture_findings = self._check_architecture()
        documentation_score, documentation_findings = self._check_documentation()
        testing_score, testing_findings = self._check_testing()

        findings.extend(structure_findings)
        findings.extend(dependency_findings)
        findings.extend(complexity_findings)
        findings.extend(architecture_findings)
        findings.extend(documentation_findings)
        findings.extend(testing_findings)

        categories = HealthCategories(
            structure=structure_score,
            dependencies=dependency_score,
            complexity=complexity_score,
            architecture=architecture_score,
            documentation=documentation_score,
            testing=testing_score,
        )
        # Overall score is an unweighted average of the six category scores --
        # simple and easy to reason about, not a tuned/opaque formula.
        overall = round(sum(categories.model_dump().values()) / 6)

        severity_rank = {"high": 0, "medium": 1, "low": 2}
        findings.sort(key=lambda f: severity_rank[f.severity])

        return HealthResponse(score=overall, categories=categories, findings=findings)

    # -- Structure -----------------------------------------------------------

    def _check_structure(self) -> tuple[int, list[HealthFinding]]:
        score = 100
        findings: list[HealthFinding] = []

        for entry in self.day2_result.files:
            lines = entry["lines"]
            # "Other"-language files are data/config/lockfiles, not source
            # code -- flagging a CSV or lockfile as needing to be "split"
            # isn't meaningful engineering advice. Nesting depth still
            # applies to any file, source or not.
            is_scoreable_source = entry["language"] != "Other" and posixpath.basename(entry["path"]) not in LOCKFILE_BASENAMES

            if is_scoreable_source and lines >= LARGE_FILE_HIGH_LINES:
                score -= 6
                findings.append(
                    HealthFinding(
                        severity="high",
                        category="structure",
                        path=entry["path"],
                        reason=f"{entry['path']} is {lines} lines long.",
                        recommendation="Consider splitting this file's responsibilities into smaller modules.",
                    )
                )
            elif is_scoreable_source and lines >= LARGE_FILE_MEDIUM_LINES:
                score -= 3
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="structure",
                        path=entry["path"],
                        reason=f"{entry['path']} is {lines} lines long.",
                        recommendation="Consider splitting this file if it covers more than one responsibility.",
                    )
                )

            if entry["path"].count("/") > DEEP_NESTING_DEPTH:
                score -= 2
                findings.append(
                    HealthFinding(
                        severity="low",
                        category="structure",
                        path=entry["path"],
                        reason=f"{entry['path']} is nested {entry['path'].count('/')} folders deep.",
                        recommendation="Deeply nested folder structures can be harder to navigate; consider flattening if not intentional.",
                    )
                )

        folder_counts: dict[str, int] = {}
        for entry in self.day2_result.files:
            folder = posixpath.dirname(entry["path"]) or "."
            folder_counts[folder] = folder_counts.get(folder, 0) + 1
        for folder, count in folder_counts.items():
            if count > LARGE_FOLDER_FILE_COUNT:
                score -= 5
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="structure",
                        path=folder,
                        reason=f"{folder} contains {count} files directly.",
                        recommendation="Consider organizing this folder into subfolders by feature or responsibility.",
                    )
                )

        secret_files = [entry["path"] for entry in self.day2_result.files if _is_secret_file(entry["path"])]
        for path in secret_files:
            findings.append(
                HealthFinding(
                    severity="low",
                    category="structure",
                    path=path,
                    reason="Environment configuration or credential-shaped file detected. Its contents were not read or analyzed.",
                    recommendation="Ensure this file is excluded from version control and never shared or exported.",
                )
            )

        return max(score, 0), findings[:MAX_STRUCTURE_FINDINGS]

    # -- Dependencies ----------------------------------------------------------

    def _check_dependencies(self) -> tuple[int, list[HealthFinding]]:
        score = 100
        findings: list[HealthFinding] = []

        files_by_path = {f["path"]: f for f in self.intelligence["files"]}
        used_packages: set[str] = set()
        for imp in self.intelligence["imports"]:
            if not imp["is_external"]:
                continue
            language = files_by_path.get(imp["file"], {}).get("language", "")
            used_packages.add(external_package_name(imp["source"], language))

        package_json_paths = [f["path"] for f in self.day2_result.files if posixpath.basename(f["path"]) == "package.json"]
        all_declared: dict[str, str] = {}  # package name -> the package.json path it was declared in

        for rel_path in package_json_paths[:MAX_PACKAGE_JSON_FILES]:
            try:
                data = json.loads((self.repository_path / rel_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            declared = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for package_name in declared:
                all_declared.setdefault(package_name, rel_path)
                if package_name in BUILD_ONLY_PACKAGES or package_name in used_packages:
                    continue
                score -= 5
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="dependencies",
                        path=rel_path,
                        reason=f"'{package_name}' is declared in {rel_path} but no import of it was found in the analyzed source.",
                        recommendation=f"Verify whether '{package_name}' is still needed; if not, remove it.",
                    )
                )

        declared_names = set(all_declared.keys())
        for group in OVERLAPPING_PACKAGE_GROUPS:
            overlap = group & declared_names
            if len(overlap) > 1:
                score -= 8
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="dependencies",
                        path=None,
                        reason=f"Multiple overlapping packages are declared for the same purpose: {', '.join(sorted(overlap))}.",
                        recommendation="Consider standardizing on a single package to reduce bundle size and maintenance overhead.",
                    )
                )

        return max(score, 0), findings[:MAX_UNUSED_DEP_FINDINGS]

    # -- Complexity ------------------------------------------------------------

    def _check_complexity(self) -> tuple[int, list[HealthFinding]]:
        score = 100
        findings: list[HealthFinding] = []

        for symbol in self.intelligence["symbols"]:
            length = symbol["end_line"] - symbol["start_line"] + 1
            if symbol["kind"] == "function":
                if length >= LARGE_FUNCTION_HIGH_LINES:
                    score -= 4
                    findings.append(
                        HealthFinding(
                            severity="high",
                            category="complexity",
                            path=symbol["file"],
                            reason=f"Function `{symbol['name']}` in {symbol['file']} is {length} lines long.",
                            recommendation="Consider breaking this function into smaller, single-purpose functions.",
                        )
                    )
                elif length >= LARGE_FUNCTION_MEDIUM_LINES:
                    score -= 2
                    findings.append(
                        HealthFinding(
                            severity="medium",
                            category="complexity",
                            path=symbol["file"],
                            reason=f"Function `{symbol['name']}` in {symbol['file']} is {length} lines long.",
                            recommendation="Consider whether this function can be simplified or split.",
                        )
                    )
            elif symbol["kind"] == "class":
                if length >= LARGE_CLASS_HIGH_LINES:
                    score -= 5
                    findings.append(
                        HealthFinding(
                            severity="high",
                            category="complexity",
                            path=symbol["file"],
                            reason=f"Class `{symbol['name']}` in {symbol['file']} is {length} lines long.",
                            recommendation="Consider splitting this class's responsibilities into smaller classes/modules.",
                        )
                    )
                elif length >= LARGE_CLASS_MEDIUM_LINES:
                    score -= 3
                    findings.append(
                        HealthFinding(
                            severity="medium",
                            category="complexity",
                            path=symbol["file"],
                            reason=f"Class `{symbol['name']}` in {symbol['file']} is {length} lines long.",
                            recommendation="Consider whether this class covers more than one responsibility.",
                        )
                    )

        return max(score, 0), findings[:MAX_COMPLEXITY_FINDINGS]

    # -- Architecture ------------------------------------------------------------

    def _check_architecture(self) -> tuple[int, list[HealthFinding]]:
        score = 100
        findings: list[HealthFinding] = []

        adjacency: dict[str, list[str]] = {}
        for (source, target, edge_type) in self.index.file_edges:
            if edge_type == "imports":
                adjacency.setdefault(source, []).append(target)

        cycles = _find_import_cycles(adjacency, MAX_CYCLES_REPORTED)
        for cycle in cycles:
            score -= 15
            findings.append(
                HealthFinding(
                    severity="high",
                    category="architecture",
                    path=cycle[0],
                    reason=f"Circular import detected: {' -> '.join(cycle)}.",
                    recommendation="Consider restructuring these modules to break the cycle, e.g. extracting shared code to a separate module.",
                )
            )

        total_files = len(self.index.file_paths)
        threshold = max(COUPLING_MIN_THRESHOLD, int(total_files * COUPLING_RATIO_OF_REPO))
        coupling_findings = 0
        for path in self.index.file_paths:
            if coupling_findings >= MAX_COUPLING_FINDINGS:
                break
            fan_in = len(self.index.reverse(path))
            fan_out = len(self.index.forward(path))
            if fan_in > threshold or fan_out > threshold:
                score -= 5
                coupling_findings += 1
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="architecture",
                        path=path,
                        reason=f"{path} is connected to {fan_in} file(s) that depend on it and {fan_out} file(s) it depends on -- unusually high for this repository's size.",
                        recommendation="High coupling can make changes riskier; consider whether responsibilities can be separated.",
                    )
                )

        return max(score, 0), findings

    # -- Documentation ------------------------------------------------------------

    def _check_documentation(self) -> tuple[int, list[HealthFinding]]:
        readme_path = next(
            (f["path"] for f in self.day2_result.files if "/" not in f["path"] and f["path"].lower() in README_NAMES),
            None,
        )

        if not readme_path:
            return 60, [
                HealthFinding(
                    severity="high",
                    category="documentation",
                    path=None,
                    reason="No README file was found at the repository root.",
                    recommendation="Add a README describing what the project does, how to run it, and its architecture.",
                )
            ]

        try:
            content = (self.repository_path / readme_path).read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            content = ""

        if len(content) < README_EMPTY_CHARS:
            return 70, [
                HealthFinding(
                    severity="medium",
                    category="documentation",
                    path=readme_path,
                    reason=f"{readme_path} exists but appears to be empty or a placeholder ({len(content)} characters).",
                    recommendation="Expand the README with a project description, setup instructions, and usage examples.",
                )
            ]

        if len(content) < README_THIN_CHARS:
            return 85, [
                HealthFinding(
                    severity="low",
                    category="documentation",
                    path=readme_path,
                    reason=f"{readme_path} is quite short ({len(content)} characters).",
                    recommendation="Consider expanding setup, usage, and architecture notes.",
                )
            ]

        return 100, []

    # -- Testing -----------------------------------------------------------------

    def _check_testing(self) -> tuple[int, list[HealthFinding]]:
        test_files = [f["path"] for f in self.day2_result.files if _is_test_file(f["path"])]
        total_source_files = sum(self.day2_result.languages.values())

        if not test_files:
            return 50, [
                HealthFinding(
                    severity="high",
                    category="testing",
                    path=None,
                    reason="No test files were detected in this repository.",
                    recommendation="Consider adding tests for the most important application logic.",
                )
            ]

        if total_source_files >= LOW_TEST_RATIO_MIN_SOURCE_FILES:
            ratio = len(test_files) / total_source_files
            if ratio < LOW_TEST_RATIO:
                return 85, [
                    HealthFinding(
                        severity="medium",
                        category="testing",
                        path=None,
                        reason=(
                            f"Only {len(test_files)} test file(s) were detected out of {total_source_files} "
                            "source files -- a low file-count ratio for a repository this size."
                        ),
                        recommendation="Consider adding tests for additional modules, especially core business logic.",
                    )
                ]

        return 100, []
