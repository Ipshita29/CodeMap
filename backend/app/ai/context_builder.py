import re
from dataclasses import dataclass
from pathlib import Path

from app.analyzer.repository_analyzer import AnalysisResult
from app.config.settings import settings

# Generic words that carry no retrieval signal on their own -- filtering
# these out is what turns "How does authentication work?" into the single
# useful keyword "authentication" instead of matching every file.
STOPWORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "how", "what", "where", "when", "why",
    "who", "which", "does", "do", "did", "can", "could", "would", "should",
    "will", "shall", "to", "of", "in", "on", "at", "for", "and", "or", "but",
    "with", "about", "explain", "tell", "describe", "project", "repository",
    "repo", "work", "works", "working", "implemented", "implementation",
    "me", "my", "your", "you",
}

FILE_MATCH_SCORE = 3
SYMBOL_MATCH_SCORE = 3
ROUTE_MATCH_SCORE = 4
IMPORT_MATCH_SCORE = 2
RELATIONSHIP_EXPANSION_SCORE = 2


def _extract_keywords(question: str) -> list[str]:
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question.lower())
    return [word for word in words if word not in STOPWORDS and len(word) > 2]


def _fuzzy_match(keyword: str, candidate: str) -> bool:
    """Loose match used for structured retrieval: exact substring in either
    direction, or a shared 4-character prefix (so "authentication" matches
    "authController.js" via the shared "auth" stem). Deterministic string
    matching only -- no embeddings, per the Day 4 "no vector DB yet" brief.
    """
    candidate = candidate.lower()
    if keyword in candidate:
        return True
    if len(candidate) >= 3 and candidate in keyword:
        return True
    if len(keyword) >= 4 and keyword[:4] in candidate:
        return True
    return False


def _format_folder_tree(tree: dict, prefix: str = "", depth: int = 0, max_depth: int = 2) -> list[str]:
    if depth >= max_depth:
        return []
    lines: list[str] = []
    for name, children in tree.items():
        lines.append(f"{prefix}{name}/")
        lines.extend(_format_folder_tree(children, prefix + "  ", depth + 1, max_depth))
    return lines


@dataclass
class BuiltContext:
    system_context: str
    sources: list[str]


class RepositoryContextBuilder:
    """Builds LLM context from Day 2/3 analysis instead of raw file dumps.

    Retrieval is entirely structured (filename/path, symbol names, route
    paths, import sources, relationship-graph expansion) — no embeddings or
    vector search yet. The goal for Day 4 is proving this is good enough
    before reaching for a vector database.
    """

    def __init__(self, repository_path: Path, day2_result: AnalysisResult, intelligence: dict):
        self.repository_path = repository_path
        self.day2_result = day2_result
        self.intelligence = intelligence

    def build_context(self, question: str) -> BuiltContext:
        keywords = _extract_keywords(question)
        relevant_files = self.find_relevant_files(question)

        sections = [self.build_repository_overview(), self.build_code_intelligence_overview()]
        used_chars = sum(len(section) for section in sections)
        budget = settings.ai_max_context_chars

        sources: list[str] = []
        if relevant_files:
            sections.append("## Relevant source code")
            for file_path in relevant_files:
                source = self._read_source_section(file_path, keywords)
                if source is None:
                    continue
                block = f"### {file_path}\n```\n{source}\n```"
                if used_chars + len(block) > budget:
                    break
                sections.append(block)
                sources.append(file_path)
                used_chars += len(block)

        return BuiltContext(system_context="\n\n".join(sections), sources=sources)

    # -- repository-level context -------------------------------------------

    def build_repository_overview(self) -> str:
        languages = ", ".join(
            f"{language} ({count} files)" for language, count in list(self.day2_result.languages.items())[:8]
        )
        frameworks = ", ".join(self.day2_result.frameworks) or "none detected"
        tree_lines = _format_folder_tree(self.day2_result.folder_tree)
        tree_text = "\n".join(tree_lines[:40]) or "(flat, no subfolders)"

        return (
            "## Repository metadata\n"
            f"Name: {self.day2_result.repository_name}\n"
            f"Total files: {self.day2_result.total_files}\n"
            f"Total folders: {self.day2_result.total_folders}\n"
            f"Languages: {languages or 'none detected'}\n"
            f"Frameworks/technologies detected: {frameworks}\n"
            f"Folder structure (top levels):\n{tree_text}"
        )

    def build_code_intelligence_overview(self) -> str:
        functions = [symbol for symbol in self.intelligence["symbols"] if symbol["kind"] == "function"]
        classes = [symbol for symbol in self.intelligence["symbols"] if symbol["kind"] == "class"]
        routes = self.intelligence["routes"]

        class_lines = "\n".join(f"- {cls['name']} ({cls['file']})" for cls in classes[:30]) or "(none detected)"
        route_lines = (
            "\n".join(f"- {r['method']} {r['path']} -> {r['handler']} ({r['file']})" for r in routes[:40])
            or "(none detected)"
        )

        return (
            "## Code intelligence summary\n"
            f"Functions found: {len(functions)}\n"
            f"Classes found: {len(classes)}\n"
            f"Imports found: {len(self.intelligence['imports'])}\n\n"
            f"API routes detected:\n{route_lines}\n\n"
            f"Classes detected:\n{class_lines}"
        )

    # -- structured retrieval -------------------------------------------

    def find_relevant_files(self, question: str) -> list[str]:
        keywords = _extract_keywords(question)
        if not keywords:
            return []

        scores: dict[str, int] = {}

        for file_entry in self.intelligence["files"]:
            path = file_entry["path"]
            for keyword in keywords:
                if _fuzzy_match(keyword, path):
                    scores[path] = scores.get(path, 0) + FILE_MATCH_SCORE

        for symbol in self.intelligence["symbols"]:
            for keyword in keywords:
                if _fuzzy_match(keyword, symbol["name"]):
                    scores[symbol["file"]] = scores.get(symbol["file"], 0) + SYMBOL_MATCH_SCORE

        for route in self.intelligence["routes"]:
            for keyword in keywords:
                if _fuzzy_match(keyword, route["path"]) or _fuzzy_match(keyword, route["handler"]):
                    scores[route["file"]] = scores.get(route["file"], 0) + ROUTE_MATCH_SCORE

        for imp in self.intelligence["imports"]:
            for keyword in keywords:
                if _fuzzy_match(keyword, imp["source"]):
                    scores[imp["file"]] = scores.get(imp["file"], 0) + IMPORT_MATCH_SCORE

        if not scores:
            return []

        seed_files = [path for path, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)]
        seed_files = seed_files[: settings.ai_max_context_files]

        expanded = self._expand_with_relationships(seed_files, scores)
        ranked = sorted(expanded.items(), key=lambda item: item[1], reverse=True)
        return [path for path, _ in ranked[: settings.ai_max_context_files]]

    def _expand_with_relationships(self, seed_files: list[str], scores: dict[str, int]) -> dict[str, int]:
        """Pulls in files directly connected to the seed set via import
        relationships -- e.g. a question about "authentication" scoring
        authController.js directly, then pulling in User.js because
        authController.js imports it, even though "User" never matched a
        keyword on its own."""
        expanded = dict(scores)
        seed_set = set(seed_files)

        for relationship in self.intelligence["relationships"]:
            if relationship["type"] != "imports":
                continue
            source_file, target_file = relationship["source"], relationship["target"]
            if not target_file:
                continue
            if source_file in seed_set:
                expanded[target_file] = expanded.get(target_file, 0) + RELATIONSHIP_EXPANSION_SCORE
            if target_file in seed_set:
                expanded[source_file] = expanded.get(source_file, 0) + RELATIONSHIP_EXPANSION_SCORE

        return expanded

    def _read_source_section(self, file_path: str, keywords: list[str]) -> str | None:
        try:
            content = (self.repository_path / file_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        max_chars = settings.ai_max_chars_per_file
        if len(content) <= max_chars:
            return content

        symbols_in_file = [symbol for symbol in self.intelligence["symbols"] if symbol["file"] == file_path]
        matching_symbols = [
            symbol for symbol in symbols_in_file if any(_fuzzy_match(keyword, symbol["name"]) for keyword in keywords)
        ]

        if matching_symbols:
            lines = content.splitlines()
            sections: list[str] = []
            used_chars = 0
            for symbol in matching_symbols[:3]:
                start = max(symbol["start_line"] - 1, 0)
                end = min(symbol["end_line"], len(lines))
                excerpt = "\n".join(lines[start:end])
                if used_chars + len(excerpt) > max_chars:
                    break
                sections.append(f"# {symbol['name']} (lines {symbol['start_line']}-{symbol['end_line']})\n{excerpt}")
                used_chars += len(excerpt)
            if sections:
                return "\n\n".join(sections)

        return content[:max_chars] + "\n... (truncated)"
