"""Shared, framework-agnostic lookup tables used across the analyzer package."""

# Directories that add noise (dependencies, build output, VCS internals) and
# should never be walked into. Checked by directory *name*, at any depth.
IGNORED_DIRS: set[str] = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".next",
    "venv",
    "__pycache__",
    ".idea",
    ".vscode",
    "coverage",
}

# Extensions we don't attempt to read as text (line counts and import
# extraction are meaningless for these; size is still recorded).
BINARY_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".mov", ".avi",
    ".exe", ".dll", ".so", ".dylib", ".class", ".jar", ".wasm",
    ".pyc", ".pyo",
}

# Extension -> human-readable language name, used for both the per-file
# `language` field and the repository-wide language breakdown. Extensions
# absent from this map are reported as "Other" and excluded from language
# counts (keeps the breakdown meaningful instead of dumping every stray
# extension into it).
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".json": "JSON",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".xml": "XML",
    ".toml": "TOML",
}
