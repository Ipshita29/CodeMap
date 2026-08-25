"""Genuinely shared utilities -- error types used across repository/analyzer/
ai/api, the GitHub URL validator used before a clone is attempted, and the
Markdown-to-PDF export renderer. Nothing here is heavy or domain-specific
enough to belong in one of the other modules; if it ever grows into
repository/analysis/AI logic, it belongs in that module instead, not here."""

import re
import unicodedata

from fpdf import FPDF
from fpdf.enums import Align, XPos, YPos
from pydantic import BaseModel, Field


# -- Exceptions --------------------------------------------------------------
# Raised throughout repository.py/analyzer.py/ai.py and translated to HTTP
# responses in api.py -- one shared vocabulary of failure modes instead of
# each module inventing its own.


class InvalidGitHubURLError(Exception):
    """Raised when a provided string is not a valid, clonable GitHub repository URL."""


class RepositoryCloneError(Exception):
    """Raised when cloning a repository fails."""


class NoRepositoryImportedError(Exception):
    """Raised when analysis is requested but no repository has been imported yet."""


class RepositoryAnalysisError(Exception):
    """Raised when a cloned repository cannot be analyzed."""


class AIServiceError(Exception):
    """Base class for AI service failures."""


class AIServiceNotConfiguredError(AIServiceError):
    """Raised when no OpenAI API key is configured."""


class AIRequestTimeoutError(AIServiceError):
    """Raised when a request to the AI provider times out."""


# -- Validation ----------------------------------------------------------

# Only allow https://github.com/<owner>/<repo>[.git] — this both rejects
# malformed input and closes off alternate git URL schemes (e.g. `ext::`,
# `file://`, embedded flags) that could otherwise be abused via GitPython.
GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\.git)?/?$"
)


def validate_github_url(url: str) -> str:
    """Validate a GitHub repository URL and return its repository name.

    Raises InvalidGitHubURLError if the URL is not a well-formed,
    clonable GitHub repository URL.
    """
    match = GITHUB_URL_PATTERN.match(url.strip())
    if not match:
        raise InvalidGitHubURLError(f"'{url}' is not a valid GitHub repository URL.")

    repo_name = match.group("repo")
    if repo_name in {".", ".."}:
        raise InvalidGitHubURLError(f"'{url}' is not a valid GitHub repository URL.")

    return repo_name


# =====================================================================
# PDF export -- renders an already-assembled Markdown report (built
# client-side from data the UI already has) into a static PDF. No
# repository access, no re-running analysis or AI -- pure rendering,
# which is why it lives here rather than in repository/analyzer/ai.py.
# =====================================================================

PAGE_MARGIN = 15
# multi_cell's defaults are new_x=RIGHT (cursor stays wherever the last
# wrapped line ended) and align=JUSTIFY. Without resetting to the left
# margin after every call, each paragraph starts from a shrinking
# remaining width -- eventually "not enough horizontal space to render a
# single character", or (with CHAR wrapmode) a pathological slowdown from
# re-wrapping against a near-zero width. LMARGIN/NEXT is the standard
# "stacked paragraphs" usage.
_CELL_KWARGS = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT, "align": Align.L}
_HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET_PATTERN = re.compile(r"^[-*]\s+(.*)$")
_HEADING_SIZES = {1: 15, 2: 13, 3: 11}
# Hard-wrap fallback for any whitespace-delimited token longer than this.
# At 10pt Helvetica, ~180mm of content width comfortably fits ~95-100
# characters -- 90 stays under that with margin, so this only ever kicks in
# for genuinely pathological single tokens, not ordinary long file paths.
_MAX_TOKEN_LENGTH = 90


def _ascii_safe(text: str) -> str:
    """FPDF's built-in core fonts are Latin-1 only. Rather than bundling a
    Unicode TTF (extra weight/complexity for what's meant to be a lightweight
    static report), normalize common smart punctuation to ASCII and drop
    anything else the core font can't encode."""
    replacements = {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "…": "...", "•": "-",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return unicodedata.normalize("NFKD", text).encode("latin-1", "ignore").decode("latin-1")


def _wrappable(text: str) -> str:
    """Defensive fallback only: with cell positioning fixed (see
    _CELL_KWARGS), normal file paths and prose wrap fine under fpdf2's
    default WORD mode. This just hard-chunks any single whitespace-delimited
    token pathological enough to exceed the page width outright (e.g. a
    long token with no natural break at all), so it can never reproduce
    the "not enough horizontal space" crash."""
    return " ".join(
        " ".join(token[i : i + _MAX_TOKEN_LENGTH] for i in range(0, len(token), _MAX_TOKEN_LENGTH))
        if len(token) > _MAX_TOKEN_LENGTH
        else token
        for token in text.split(" ")
    )


class _ReportPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", size=8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def render_markdown_to_pdf(title: str, markdown_text: str) -> bytes:
    pdf = _ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=PAGE_MARGIN)
    pdf.set_margins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 10, _wrappable(_ascii_safe(title)), **_CELL_KWARGS)
    pdf.ln(2)

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()

        if not line or line.strip() == "---":
            pdf.ln(3)
            continue

        heading_match = _HEADING_PATTERN.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            pdf.set_font("Helvetica", "B", _HEADING_SIZES[level])
            pdf.set_text_color(20, 20, 20)
            pdf.ln(3)
            pdf.multi_cell(0, 8, _wrappable(_ascii_safe(heading_match.group(2))), **_CELL_KWARGS)
            continue

        bullet_match = _BULLET_PATTERN.match(line)
        if bullet_match:
            pdf.set_font("Helvetica", size=10)
            pdf.set_text_color(40, 40, 40)
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(0, 6, f"- {_wrappable(_ascii_safe(bullet_match.group(1)))}", **_CELL_KWARGS)
            continue

        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 6, _wrappable(_ascii_safe(line)), **_CELL_KWARGS)

    return bytes(pdf.output())


class PdfExportRequest(BaseModel):
    title: str
    markdown: str = Field(max_length=300_000)
