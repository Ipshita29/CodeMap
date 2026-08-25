"""ai.py -- everything AI-related: the LLM provider client, prompts,
repository context construction, the answer cache, and the orchestration
functions behind Ask CodeMap / the AI repository brief.

AI answers are grounded in repository.py's canonical snapshot and
analyzer.py's parsed code intelligence -- RepositoryContextBuilder never
re-scans the filesystem itself, and every prompt in this file instructs the
model to only claim what that context actually supports (see
GROUNDING_RULES). This module has no FastAPI/HTTP dependency; api.py is
responsible for translating the exceptions raised here into HTTP responses.

Dependency direction: ai.py depends on repository.py only. It deliberately
never imports analyzer.py -- the orchestration functions in section 6 take
the already-built `AnalysisResult` (repository.py) and code intelligence
dict (analyzer.py's get_or_build_code_intelligence) as parameters, fetched
by api.py before calling in. That keeps the dependency graph one-directional
(repository/analyzer -> ai, matching analyzer.py's own top-level `from ai
import ...` for its impact-explanation prompt) instead of a cycle.

Sections:
  1. LLM provider client (AIService)
  2. Prompts
  3. Repository context construction (RepositoryContextBuilder)
  4. Answer cache -- keyed on repository.repository_version(), the same
     canonical version identity the snapshot cache uses
  5. Pydantic request/response models
  6. Orchestration (what api.py's routes call)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, Field, field_validator

from config import settings
from repository import AnalysisResult, repository_version
from utils import AIRequestTimeoutError, AIServiceError, AIServiceNotConfiguredError

logger = logging.getLogger(__name__)


# =====================================================================
# 1. LLM provider client
# =====================================================================


class AIService:
    """Thin wrapper around the OpenAI SDK.

    Nothing about prompt content or context assembly lives here — this is
    purely "send these messages, get text back, translate provider errors
    into our own exception types." Keeping OpenAI calls out of the API
    routes means the routes stay testable without a live API key.

    `openai_base_url` lets this point at any OpenAI-compatible provider
    (Groq, Gemini, OpenRouter, a local Ollama server, ...) instead of
    OpenAI itself -- the SDK and this class don't change, only config does.
    """

    def __init__(self):
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if not settings.openai_api_key:
            raise AIServiceNotConfiguredError(
                "No AI API key is configured. Set OPENAI_API_KEY in the backend environment."
            )
        if self._client is None:
            self._client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or None,
                timeout=settings.openai_timeout_seconds,
            )
        return self._client

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        client = self._get_client()

        try:
            response = client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
        except RateLimitError as exc:
            logger.warning("AI provider rate limit/quota error: %s", exc)
            raise AIServiceError(
                "The AI provider rejected the request (rate limit or quota exceeded). "
                "Please check your API key's usage limits and try again."
            ) from exc
        except APITimeoutError as exc:
            raise AIRequestTimeoutError("The AI request timed out. Please try again.") from exc
        except APIError as exc:
            logger.warning("AI provider API error: %s", exc)
            raise AIServiceError("The AI service returned an error. Please try again.") from exc

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice and choice.message else None
        if not content:
            raise AIServiceError("The AI service returned an empty response.")
        return content.strip()


ai_service = AIService()


# =====================================================================
# 2. Prompts
# =====================================================================

GROUNDING_RULES = """You are CodeMap, an assistant that explains real software repositories using \
a structured analysis of their actual code (file scan, parsed functions/classes/imports/exports, \
detected API routes, and a relationship graph), plus excerpts of the real source code.

You must follow these rules at all times:
- Only make claims that are directly supported by the provided repository context.
- Never invent files, functions, classes, routes, or technologies that are not present in the context.
- If the context does not contain enough information to answer confidently, say so explicitly \
instead of guessing.
- Clearly distinguish between what the repository confirms and what you are reasonably inferring \
from partial evidence — flag inferences as such.
- When explaining how something is implemented, name the specific file(s) involved.
- Ground answers in this specific repository, not in generic knowledge of how such projects \
usually work. If the repository has concrete evidence for something, cite that evidence instead \
of falling back to a generic, textbook-style explanation.
- Simplify the *wording* of a fact, never the fact itself — an exact file, function, class, or \
route name is a detail worth keeping even in an otherwise simple sentence.
- Write conversationally, the way one developer explains a codebase to another sitting next to \
them — "in this repo, you'll find..." or "this is where..." rather than stiff, formal phrasing \
like "the repository explicitly demonstrates", "the implementation relies upon", or "the \
aforementioned mechanism".
- Never use markdown syntax of any kind — no #, ##, **, *, -, numbered lists, or backticks \
(neither single backticks around an identifier nor triple-backtick code fences). The response is \
rendered as plain text with no markdown parser, so every one of those characters shows up \
literally, backticks included — a line wrapped in ``` renders as three literal backtick \
characters, not a code block. Write file names, function/class names, CLI commands, and code \
identifiers as bare plain text, with nothing wrapped in backticks anywhere in the response — not \
even a single short one like a command name: write app/api/repository.py, add_url_rule, and flask \
routes exactly like that, never `app/api/repository.py`, `add_url_rule`, or `flask routes`. If you \
show a code excerpt, set it off with a blank line and indentation only, with no fence around it."""

BEGINNER_SUMMARY_PROMPT = f"""{GROUNDING_RULES}

Write a beginner-friendly summary of this repository for someone with little technical background.

Cover, briefly and in plain language:
- What the project does
- Who it's likely for
- The main features you can identify
- The main technologies used
- The basic architecture (e.g. frontend/backend/database, if present)
- How the major parts work together

Avoid unnecessary jargon. Do not list every file — describe the project as a whole."""

DEVELOPER_SUMMARY_PROMPT = f"""{GROUNDING_RULES}

Write a developer-focused summary of this repository.

Cover, wherever the repository provides evidence for it:
- Overall architecture
- Frontend (framework, structure)
- Backend (framework, structure)
- Database / data layer, if present
- Authentication, if present
- API layer / routes
- Important services and modules
- Major dependencies
- Important files (reference actual paths)
- The main execution/data flow, as a short step-by-step trace through actual files

If a category (e.g. database, authentication) has no evidence in the provided context, say it \
wasn't found rather than assuming it exists."""

REPOSITORY_CHAT_PROMPT = f"""{GROUNDING_RULES}

Answer the user's question about this repository using only the provided context. Write for \
someone looking at this codebase for the first time: simple and direct first, with the technical \
precision underneath it, not instead of it. Never trade away a repository-specific fact to keep \
things simple -- simplify how it's said, not what's said.

Build the answer out of whichever of these pieces actually help this particular question. Skip a \
piece entirely if it wouldn't add anything -- do not force every answer into the full shape:

- The direct answer, in 1-3 plain-English sentences, right at the start. Don't make the reader \
wait through background to find out the actual answer.
- The general concept, explained simply, before naming any specific class, function, decorator, \
or internal object. If a technical term is genuinely needed, introduce it right after the plain- \
language idea it names, e.g. "the internal list Flask uses to keep track of registered routes -- \
Flask calls this the URL map", not the term cold with no explanation.
- How that concept is actually built here, traced through the real files, functions, and classes \
in the context (e.g. "X calls Y in file Z"). This is where the technical precision belongs -- \
exact names, exact files, no hand-waving.
- The specific file path(s) most relevant to the question, if that's useful beyond what's already \
been named while tracing the implementation.

If the question is about a process or sequence of events, and walking through the steps in order \
would genuinely make it clearer than prose, write each step on its own line connected by a plain \
"→" arrow, then briefly explain each step -- but only when it helps this specific question, not \
as a routine device.

Reminder, because this is easy to slip back into out of habit: never write three backtick \
characters in a row anywhere in the response, and never wrap any word, filename, or code snippet \
in single backticks either -- not even once. This applies just as much to a multi-line code \
excerpt as it does to a single identifier.

If you include a code excerpt, keep it to the smallest useful snippet, and only when the actual \
code is clearer than describing it in words — set it off with a blank line before and after and \
indent it, with no ``` fence and no backticks around it (see the formatting rule above).

If the context does not contain the answer, say clearly that you could not find it in the \
analyzed repository rather than inventing one."""

IMPACT_EXPLANATION_PROMPT = f"""{GROUNDING_RULES}

You will be given a verified, structurally-computed change-impact report for one file: its direct \
dependents, indirect dependents, related API routes, related frontend callers, and a heuristic risk \
score. This data was computed by static analysis, not by you.

Explain, in plain prose:
- What could be affected if this file changes, and why (reference the actual files/routes given)
- Which files the developer should inspect first
- What they should test afterward, based on the affected routes/files

Rules:
- Only reference files, functions, and routes that appear in the supplied structural data. Do not \
invent or assume any file, route, or dependent that isn't listed.
- Do not claim the change will definitely break anything -- describe this as a structural risk \
estimate, not a guaranteed outcome.
- If the supplied data is sparse (e.g. no dependents at all), say that plainly rather than padding \
the answer."""

CHAT_MODE_INSTRUCTIONS: dict[str, str] = {
    "beginner": (
        "Keep the plain-English direct answer and the simple concept explanation doing most of "
        "the work. When you trace the implementation, name only the one or two files that matter "
        "most rather than the full call chain, and keep technical terms to the ones you actually "
        "need -- explain each one in the same sentence it first appears in."
    ),
    "developer": (
        "Keep the structure above -- start with the direct answer and the simple concept, don't "
        "skip straight to implementation details. Once you get to how it's built here, go deeper: "
        "exact file paths, function/class names, and the real call chain, not just the one or two "
        "most relevant files."
    ),
}


# =====================================================================
# 3. Repository context construction
# =====================================================================

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


def _format_repository_tree(nodes: list, prefix: str = "", depth: int = 0, max_depth: int = 2) -> list[str]:
    """Renders the canonical repository_tree's directories (same tree the
    Architecture Repository Map shows) as indented lines for the AI prompt --
    directories only, same as before, to stay within the folder-structure
    summary this section has always been rather than a full file listing."""
    if depth >= max_depth:
        return []
    lines: list[str] = []
    for node in nodes:
        if node.type != "directory":
            continue
        lines.append(f"{prefix}{node.name}/")
        lines.extend(_format_repository_tree(node.children or [], prefix + "  ", depth + 1, max_depth))
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
        tree_lines = _format_repository_tree(self.day2_result.repository_tree)
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


# =====================================================================
# 4. Answer cache
#
# Keyed on repository identity + repository *version* + mode + normalized
# question, so re-asking the same question against an unchanged repository
# never triggers a second AI call, but a repository re-import can never
# serve a stale answer generated against the old code.
#
# "Repository version" reuses repository.py's repository_version() -- the
# same commit-SHA-first identity the canonical snapshot cache keys on --
# so a repository re-import that lands back on the same commit still
# serves cached answers, while a real content change (a new commit) never
# lets a stale answer survive.
#
# No persistence layer, same as the rest of this app's in-memory state --
# lost on restart, rebuilt on demand. A repository path keeps only its
# current version's entries; asking a fresh version prunes the previous
# one instead of leaking memory across repeated re-imports.
# =====================================================================


def normalize_question(question: str) -> str:
    """Collapses differences that shouldn't count as a different question --
    case, surrounding/internal whitespace, and trailing punctuation. E.g.
    "How does Login work?" and "how does login work" normalize the same."""
    collapsed = re.sub(r"\s+", " ", question.strip().lower())
    return collapsed.rstrip("?.! ")


@dataclass
class AnswerCacheEntry:
    id: str
    question: str  # original wording, for display
    mode: str
    answer: str
    sources: list[str] = field(default_factory=list)
    asked_at: float = 0.0


_answer_cache: dict[str, AnswerCacheEntry] = {}
_answer_history: dict[str, list[str]] = {}  # repo-version key -> cache keys, oldest first
_latest_version_by_path: dict[str, str] = {}  # repo path -> its current repo-version key


def _repository_version_key(repository_path: Path) -> str:
    repository_path = Path(repository_path)
    return f"{repository_path}@{repository_version(repository_path)}"


def _cache_key(repo_version_key: str, mode: str, normalized_question: str) -> str:
    return f"{repo_version_key}::{mode}::{normalized_question}"


def _current_version(repository_path: Path) -> str:
    """Resolves the repository's current version key and prunes any cache
    entries left over from a previous version of the same path."""
    repository_path = Path(repository_path)
    repo_version_key = _repository_version_key(repository_path)

    path_str = str(repository_path)
    previous = _latest_version_by_path.get(path_str)
    if previous is not None and previous != repo_version_key:
        for stale_key in _answer_history.pop(previous, []):
            _answer_cache.pop(stale_key, None)
    _latest_version_by_path[path_str] = repo_version_key

    return repo_version_key


def lookup_answer(repository_path: Path, mode: str, question: str) -> AnswerCacheEntry | None:
    repo_version_key = _current_version(repository_path)
    key = _cache_key(repo_version_key, mode, normalize_question(question))
    return _answer_cache.get(key)


def store_answer(repository_path: Path, mode: str, question: str, answer: str, sources: list[str]) -> AnswerCacheEntry:
    repo_version_key = _current_version(repository_path)
    key = _cache_key(repo_version_key, mode, normalize_question(question))

    entry = _answer_cache.get(key)
    if entry is None:
        entry = AnswerCacheEntry(
            id=key, question=question.strip(), mode=mode, answer=answer, sources=sources, asked_at=time.time()
        )
        _answer_cache[key] = entry
        _answer_history.setdefault(repo_version_key, []).append(key)
    else:
        # A second generation for the same key shouldn't normally happen --
        # lookup_answer() would have short-circuited first -- but stay
        # authoritative rather than leave a mismatched entry if it does
        # (e.g. a race between two concurrent requests for a brand-new
        # question).
        entry.answer = answer
        entry.sources = sources
    return entry


def list_answer_history(repository_path: Path) -> list[AnswerCacheEntry]:
    """Newest first, scoped to the repository's current version only -- an
    older version's questions are never listed, so a stale answer can never
    be selected from history after the repository changes."""
    repo_version_key = _current_version(repository_path)
    keys = _answer_history.get(repo_version_key, [])
    return [_answer_cache[key] for key in reversed(keys) if key in _answer_cache]


def clear_answer_history(repository_path: Path) -> None:
    """Drops every cached answer for the repository's current version --
    an explicit user action (the history popover's "Clear history"), not
    something the cache does on its own."""
    repo_version_key = _current_version(repository_path)
    for key in _answer_history.pop(repo_version_key, []):
        _answer_cache.pop(key, None)


# =====================================================================
# 5. Pydantic request/response models
# =====================================================================

ChatMode = Literal["beginner", "developer"]


class ChatRequest(BaseModel):
    repository_id: str
    question: str = Field(..., min_length=1)
    mode: ChatMode = "beginner"

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question must not be empty.")
        return stripped


class ChatHistoryEntry(BaseModel):
    id: str
    question: str
    mode: ChatMode
    answer: str
    sources: list[str]
    asked_at: float


class ChatResponse(ChatHistoryEntry):
    # True when this came straight from the answer cache instead of a new
    # AI call -- same repository version, same mode, same (normalized)
    # question as one already asked.
    cached: bool


class ChatHistoryResponse(BaseModel):
    entries: list[ChatHistoryEntry]


class RepositorySummaryResponse(BaseModel):
    repository_name: str
    beginner_summary: str
    developer_summary: str
    sources: list[str]


# =====================================================================
# 6. Orchestration -- what api.py's routes call, after api.py has already
#    obtained the repository's canonical snapshot (repository.py) and code
#    intelligence (analyzer.py) and passes both in. Nothing below this
#    point ever fetches or builds repository intelligence itself -- that
#    keeps ai.py from needing to import analyzer.py at all (see the module
#    docstring). Domain exceptions (RepositoryAnalysisError,
#    AIServiceNotConfiguredError, AIRequestTimeoutError, AIServiceError)
#    propagate uncaught; api.py translates them into HTTP responses.
# =====================================================================


def build_context_builder(
    repository_path: Path, day2_result: AnalysisResult, intelligence: dict
) -> RepositoryContextBuilder:
    return RepositoryContextBuilder(repository_path, day2_result, intelligence)


def generate_repository_summary(
    repository_path: Path, day2_result: AnalysisResult, intelligence: dict
) -> RepositorySummaryResponse:
    builder = build_context_builder(repository_path, day2_result, intelligence)
    # A summary has no specific question to key retrieval off of, so pull a
    # broad structural context instead of a narrow keyword-scored file set.
    context = builder.build_context("project overview architecture main features")

    beginner_summary = ai_service.complete(BEGINNER_SUMMARY_PROMPT, context.system_context)
    developer_summary = ai_service.complete(DEVELOPER_SUMMARY_PROMPT, context.system_context)

    return RepositorySummaryResponse(
        repository_name=builder.day2_result.repository_name,
        beginner_summary=beginner_summary,
        developer_summary=developer_summary,
        sources=context.sources,
    )


def answer_question(
    repository_path: Path,
    question: str,
    mode: str,
    day2_result: AnalysisResult,
    intelligence: dict,
) -> ChatResponse:
    """Generates a fresh answer and caches it. Callers are expected to have
    already checked lookup_answer() themselves -- a cache hit costs nothing
    beyond a dict lookup, so api.py short-circuits on one before it goes to
    the trouble of fetching `day2_result`/`intelligence` at all, rather than
    that check living inside this function."""
    builder = build_context_builder(repository_path, day2_result, intelligence)
    context = builder.build_context(question)

    system_prompt = f"{REPOSITORY_CHAT_PROMPT}\n\n{CHAT_MODE_INSTRUCTIONS[mode]}"
    user_prompt = f"{context.system_context}\n\n## Question\n{question}"
    answer = ai_service.complete(system_prompt, user_prompt)

    entry = store_answer(repository_path, mode, question, answer, context.sources)
    return ChatResponse(**entry.__dict__, cached=False)


def get_chat_history(repository_path: Path) -> ChatHistoryResponse:
    """Every question asked (and its saved answer) for the repository's
    current version, newest first -- selecting one in the UI just re-renders
    already-fetched data, no request or AI call involved."""
    entries = list_answer_history(repository_path)
    return ChatHistoryResponse(entries=[ChatHistoryEntry(**entry.__dict__) for entry in entries])
