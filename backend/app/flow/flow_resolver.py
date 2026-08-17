"""Best-effort, regex-based detectors that feed the flow analyzer.

Mirrors `app/analyzer/import_extractor.py`'s approach: not AST-based, not
claimed to be exhaustive, just good enough to seed real (verifiable)
frontend -> backend edges. Every match records the source line so callers
can attribute it to a specific function via that function's known
start/end line range from Day 3 symbols.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue"}

# axios.get("/x"), axios.post('/x'), axios.request({ url: "/x", method: "post" })
_AXIOS_METHOD_PATTERN = re.compile(
    r"axios\s*\.\s*(get|post|put|patch|delete)\s*\(\s*['\"`]([^'\"`]+)['\"`]", re.IGNORECASE
)

# fetch("/x") or fetch("/x", { method: "POST", ... })
_FETCH_PATTERN = re.compile(
    r"fetch\s*\(\s*['\"`]([^'\"`]+)['\"`]\s*(?:,\s*\{([^}]*)\})?", re.IGNORECASE | re.DOTALL
)
_FETCH_METHOD_IN_OPTIONS = re.compile(r"method\s*:\s*['\"`](\w+)['\"`]", re.IGNORECASE)


@dataclass(frozen=True)
class DetectedApiCall:
    method: str
    path: str
    line: int


def extract_api_calls(content: str, extension: str) -> list[DetectedApiCall]:
    """Finds axios/fetch calls with a string-literal URL. Calls with a
    dynamic/templated URL (`` `/users/${id}` `` or a variable) are skipped
    rather than guessed at."""
    if extension not in JS_EXTENSIONS:
        return []

    calls: list[DetectedApiCall] = []
    for match in _AXIOS_METHOD_PATTERN.finditer(content):
        method, path = match.group(1).upper(), match.group(2)
        if "${" in path:
            continue
        line = content.count("\n", 0, match.start()) + 1
        calls.append(DetectedApiCall(method=method, path=path, line=line))

    for match in _FETCH_PATTERN.finditer(content):
        path, options = match.group(1), match.group(2) or ""
        if "${" in path:
            continue
        method_match = _FETCH_METHOD_IN_OPTIONS.search(options)
        method = method_match.group(1).upper() if method_match else "GET"
        line = content.count("\n", 0, match.start()) + 1
        calls.append(DetectedApiCall(method=method, path=path, line=line))

    return calls


def normalize_route_path(path: str) -> str:
    """Strips a leading API mount prefix so `/api/login` and `/login` can be
    compared. Deliberately narrow (`/api`, `/api/v1`) -- not a general
    router-mount resolver, since Day 3 doesn't track `app.use()` prefixes."""
    stripped = path
    for prefix in ("/api/v1", "/api/v2", "/api"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):] or "/"
            break
    return stripped.rstrip("/") or "/"


def match_route(method: str, path: str, routes: list[dict]) -> tuple[dict | None, str]:
    """Matches a detected frontend API call to a Day 3 RouteEntry.

    Returns (route, confidence). Never guesses past what the path/method
    text actually supports -- an unmatched call comes back as (None, "unknown")
    rather than a fabricated best-effort target.
    """
    candidates = [r for r in routes if r["method"].upper() == method.upper()]

    for route in candidates:
        if route["path"] == path:
            return route, "high"

    normalized_call = normalize_route_path(path)
    for route in candidates:
        if normalize_route_path(route["path"]) == normalized_call:
            return route, "medium"

    return None, "unknown"


def resolve_handler_name(handler: str) -> str:
    """`router.post("/login", authController.login)` parses `handler` as
    "authController.login" -- the symbol we actually want is "login"."""
    if handler == "<inline>":
        return handler
    return handler.rsplit(".", 1)[-1]


def score_file_for_query(path: str, symbols: list[dict], routes: list[dict], query: str) -> int:
    """Simple keyword relevance score for resolving a free-text query like
    'authentication' to a starting file -- substring matching only, no
    embeddings/semantic search (explicitly out of scope for Day 6)."""
    term = query.lower()
    score = 0
    if term in path.lower():
        score += 3
    for symbol in symbols:
        if symbol["file"] == path and term in symbol["name"].lower():
            score += 2
    for route in routes:
        if route["file"] == path and term in route["path"].lower():
            score += 2
    return score
