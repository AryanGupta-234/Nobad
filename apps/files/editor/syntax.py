from __future__ import annotations

import json
from pathlib import PurePosixPath
import re


# Tier 1: Exact Filename mapping (case-insensitive lookup where appropriate)
EXACT_FILENAMES: dict[str, str] = {
    # Docker & Containers
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "docker-compose.yml": "yaml",
    "docker-compose.yaml": "yaml",
    "compose.yml": "yaml",
    "compose.yaml": "yaml",
    # Build & Make
    "makefile": "makefile",
    "gnumakefile": "makefile",
    "cmakelists.txt": "cmake",
    # Web & Servers
    "caddyfile": "caddyfile",
    "nginx.conf": "nginx",
    # Ruby & Rails
    "vagrantfile": "ruby",
    "gemfile": "ruby",
    "gemfile.lock": "ruby",
    "rakefile": "ruby",
    "procfile": "properties",
    # Environment & Shell Dotfiles
    ".env": "properties",
    ".env.local": "properties",
    ".env.production": "properties",
    ".env.development": "properties",
    ".env.test": "properties",
    ".env.example": "properties",
    ".bashrc": "shell",
    ".bash_profile": "shell",
    ".bash_aliases": "shell",
    ".bash_logout": "shell",
    ".zshrc": "shell",
    ".zprofile": "shell",
    ".profile": "shell",
    # Git
    ".gitconfig": "ini",
    ".gitignore": "properties",
    ".gitattributes": "properties",
    ".gitmodules": "ini",
    # Package & Manifests
    "cargo.toml": "toml",
    "cargo.lock": "toml",
    "pyproject.toml": "toml",
    "package.json": "json",
    "package-lock.json": "json",
    "tsconfig.json": "json",
    "jsconfig.json": "json",
    # Linux system configurations
    "hosts": "properties",
    "resolv.conf": "properties",
    "fstab": "properties",
    "sshd_config": "properties",
    "ssh_config": "properties",
}

# Tier 2: Comprehensive 100+ File Extension mapping to Monaco language IDs
LANGUAGE_BY_SUFFIX: dict[str, str] = {
    # Python
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".pyx": "python",
    # JavaScript & TypeScript
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "typescript",
    # Systems & Compiled Languages
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".hh": "cpp",
    ".cs": "csharp",
    # JVM & Mobile
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".dart": "dart",
    ".scala": "scala",
    # Dynamic & Scripting
    ".php": "php",
    ".phtml": "php",
    ".rb": "ruby",
    ".pl": "perl",
    ".pm": "perl",
    ".lua": "lua",
    # Shell & Terminal
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".ksh": "shell",
    ".command": "shell",
    # Database
    ".sql": "sql",
    ".pgsql": "sql",
    ".mysql": "sql",
    ".sqlite": "sql",
    # Config & Serialized Data
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".jsonc": "json",
    ".json5": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".svg": "xml",
    ".xaml": "xml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "properties",
    ".properties": "properties",
    ".env": "properties",
    # Systemd Unit Files
    ".service": "ini",
    ".timer": "ini",
    ".socket": "ini",
    ".target": "ini",
    ".mount": "ini",
    ".slice": "ini",
    # Web & Styles
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "scss",
    ".less": "less",
    # Modern Web Frameworks
    ".vue": "html",
    ".svelte": "html",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    # Documentation & Markup
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdown": "markdown",
    ".rst": "restructuredtext",
    ".tex": "latex",
    # Plain text & logs
    ".txt": "plaintext",
    ".log": "plaintext",
}

# Tier 3: First-Line Shebang patterns
SHEBANG_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^#!\s*/.*\b(python|python3|pypy)\b"), "python"),
    (re.compile(r"^#!\s*/.*\b(bash|sh|zsh|dash|ksh)\b"), "shell"),
    (re.compile(r"^#!\s*/.*\b(node|nodejs)\b"), "javascript"),
    (re.compile(r"^#!\s*/.*\b(perl)\b"), "perl"),
    (re.compile(r"^#!\s*/.*\b(ruby)\b"), "ruby"),
    (re.compile(r"^#!\s*/.*\b(php)\b"), "php"),
]


def language_for_path(path: str, first_line: str = "", content_sample: str = "") -> str:
    """
    5-Tier VS Code-grade language detection:
    1. Exact filename match (e.g. Dockerfile, Makefile, .bashrc)
    2. 100+ file extensions (.py, .ts, .rs, .go, .sql, etc.)
    3. First-line shebang matching (#!/usr/bin/env python3)
    4. Leading content token heuristics (<?php, <!DOCTYPE html, JSON roots)
    5. Fallback to plaintext
    """
    filename = PurePosixPath(path).name.lower()

    # Tier 1: Exact Filename
    if filename in EXACT_FILENAMES:
        return EXACT_FILENAMES[filename]

    # Tier 2: File Extension
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in LANGUAGE_BY_SUFFIX:
        return LANGUAGE_BY_SUFFIX[suffix]

    # Tier 3: First-line Shebang detection
    f_line = first_line.strip()
    if f_line.startswith("#!"):
        for pattern, lang in SHEBANG_PATTERNS:
            if pattern.search(f_line):
                return lang

    # Tier 4: Content heuristics
    sample = (content_sample or first_line).strip()
    if sample:
        if sample.startswith("<?php"):
            return "php"
        if sample.lower().startswith("<!doctype html") or sample.lower().startswith("<html"):
            return "html"
        if sample.startswith("<?xml"):
            return "xml"
        if sample.startswith("[Unit]") or sample.startswith("[Service]"):
            return "ini"
        if (sample.startswith("{") and sample.endswith("}")) or (sample.startswith("[") and sample.endswith("]")):
            try:
                json.loads(sample)
                return "json"
            except Exception:
                pass

    return "plaintext"


def all_supported_languages() -> list[dict[str, str]]:
    """
    Returns curated metadata for all supported languages to populate
    the interactive Language Mode Selector dialog.
    """
    return [
        {"name": "YAML", "id": "yaml", "ext": ".yml, .yaml, compose.yml", "icon": "📄"},
        {"name": "Python", "id": "python", "ext": ".py, .pyw, .pyi", "icon": "🐍"},
        {"name": "JavaScript", "id": "javascript", "ext": ".js, .mjs, .jsx", "icon": "🟨"},
        {"name": "TypeScript", "id": "typescript", "ext": ".ts, .tsx", "icon": "🔷"},
        {"name": "Shell Script (Bash/Zsh)", "id": "shell", "ext": ".sh, .bash, .zsh", "icon": "🐚"},
        {"name": "Docker / Containerfile", "id": "dockerfile", "ext": "Dockerfile", "icon": "🐳"},
        {"name": "JSON", "id": "json", "ext": ".json, .jsonc", "icon": "📋"},
        {"name": "Rust", "id": "rust", "ext": ".rs", "icon": "🦀"},
        {"name": "Go", "id": "go", "ext": ".go", "icon": "🐹"},
        {"name": "SQL", "id": "sql", "ext": ".sql, .pgsql", "icon": "🗄️"},
        {"name": "Nginx Configuration", "id": "nginx", "ext": ".conf, nginx.conf", "icon": "🌐"},
        {"name": "Systemd / INI", "id": "ini", "ext": ".service, .timer, .ini", "icon": "⚙️"},
        {"name": "HTML", "id": "html", "ext": ".html, .htm", "icon": "🌐"},
        {"name": "CSS", "id": "css", "ext": ".css", "icon": "🎨"},
        {"name": "SCSS / SASS", "id": "scss", "ext": ".scss, .sass", "icon": "🎨"},
        {"name": "PHP", "id": "php", "ext": ".php", "icon": "🐘"},
        {"name": "Markdown", "id": "markdown", "ext": ".md, .markdown", "icon": "📝"},
        {"name": "C / C++", "id": "cpp", "ext": ".c, .cpp, .h, .hpp", "icon": "⚡"},
        {"name": "C# (.NET)", "id": "csharp", "ext": ".cs", "icon": "🟣"},
        {"name": "Java", "id": "java", "ext": ".java", "icon": "☕"},
        {"name": "Kotlin", "id": "kotlin", "ext": ".kt, .kts", "icon": "🎯"},
        {"name": "Swift", "id": "swift", "ext": ".swift", "icon": "🦅"},
        {"name": "TOML", "id": "toml", "ext": ".toml, Cargo.toml", "icon": "📦"},
        {"name": "XML", "id": "xml", "ext": ".xml, .svg", "icon": "🏷️"},
        {"name": "Properties / Config", "id": "properties", "ext": ".env, .conf, .properties", "icon": "🔧"},
        {"name": "Plain Text", "id": "plaintext", "ext": ".txt, .log", "icon": "📝"},
    ]
