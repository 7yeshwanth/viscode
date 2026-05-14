"""
VisCode Configuration Management

Loads settings from environment variables with validation.
Uses .env file for local development.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from backend directory
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


class Config:
    """Application configuration loaded from environment variables."""

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "")  # Custom endpoint (Azure, proxy, etc.)
    OPENAI_MODEL_PASS1: str = os.getenv("OPENAI_MODEL_PASS1", "gpt-4.1-mini")
    OPENAI_MODEL_PASS2: str = os.getenv("OPENAI_MODEL_PASS2", "gpt-4.1")
    OPENAI_MODEL_PASS3: str = os.getenv("OPENAI_MODEL_PASS3", "gpt-4.1")

    # Concurrency
    MAX_CONCURRENT_CALLS: int = int(os.getenv("MAX_CONCURRENT_CALLS", "5"))

    # File limits
    MAX_FILE_LINES: int = int(os.getenv("MAX_FILE_LINES", "5000"))

    # Cache
    CACHE_DIR: str = os.getenv("CACHE_DIR", ".viscode_cache")

    # Security: allowed base paths (comma-separated)
    ALLOWED_PATHS: list[str] = [
        p.strip() for p in os.getenv("ALLOWED_PATHS", "/Users,/home,/Volumes").split(",")
    ]

    # Blocked paths — never allow reading these
    BLOCKED_PATHS: list[str] = ["/etc", "/var", "/usr", "/bin", "/sbin", "/sys", "/proc"]
    BLOCKED_PATTERNS: list[str] = [".env", ".git/config", "id_rsa", ".ssh", ".aws/credentials"]

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Supported languages: extension → language name
    LANGUAGE_MAP: dict[str, str] = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".c": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".vue": "vue",
        ".svelte": "svelte",
        ".dart": "dart",
        ".r": "r",
        ".R": "r",
        ".lua": "lua",
        ".sh": "shell",
        ".bash": "shell",
        ".zsh": "shell",
    }

    # Default ignore patterns for directory scanning
    DEFAULT_IGNORE_DIRS: set[str] = {
        ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
        "dist", "build", ".next", ".nuxt", "target", "bin", "obj",
        ".idea", ".vscode", ".DS_Store", ".cache", ".tox", ".mypy_cache",
        ".pytest_cache", "coverage", ".nyc_output", ".turbo", ".parcel-cache",
        "vendor", "Pods", ".gradle", ".terraform",
    }

    DEFAULT_IGNORE_FILES: set[str] = {
        "package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml",
        "Cargo.lock", "go.sum", "Gemfile.lock", "composer.lock",
        ".DS_Store", "Thumbs.db",
    }

    DEFAULT_IGNORE_EXTENSIONS: set[str] = {
        ".pyc", ".pyo", ".class", ".o", ".so", ".dylib", ".dll", ".exe",
        ".jar", ".war", ".ear", ".zip", ".tar", ".gz", ".bz2", ".7z",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
        ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".woff", ".woff2", ".ttf", ".eot",
        ".min.js", ".min.css", ".map",
        ".db", ".sqlite", ".sqlite3",
    }

    # Generated code patterns (filename patterns to skip AI analysis)
    GENERATED_CODE_PATTERNS: list[str] = [
        "*_pb2.py", "*_pb2_grpc.py",  # Protobuf
        "*.generated.*",               # Generic generated
        "*.g.dart",                     # Dart generated
        "*.freezed.dart",              # Dart freezed
        "*.gen.go",                    # Go generated
        "migrations/*.py",            # Django/Alembic migrations
    ]

    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration and return list of warnings."""
        warnings = []
        if not cls.OPENAI_API_KEY or cls.OPENAI_API_KEY == "sk-your-key-here":
            warnings.append("OPENAI_API_KEY is not set. AI analysis will not work.")
        if cls.MAX_CONCURRENT_CALLS < 1 or cls.MAX_CONCURRENT_CALLS > 20:
            warnings.append(f"MAX_CONCURRENT_CALLS={cls.MAX_CONCURRENT_CALLS} is out of range [1, 20]. Using 5.")
            cls.MAX_CONCURRENT_CALLS = 5
        return warnings

    @classmethod
    def get_cache_path(cls) -> Path:
        """Get the resolved cache directory path."""
        cache = Path(cls.CACHE_DIR)
        if not cache.is_absolute():
            cache = Path(__file__).parent / cache
        cache.mkdir(parents=True, exist_ok=True)
        return cache


# Singleton config instance
config = Config()
