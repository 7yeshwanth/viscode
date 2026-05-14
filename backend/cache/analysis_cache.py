"""
VisCode Cache Service

File-hash based caching using JSON files on disk.
Cache key = SHA256(file_content) + model_version.
Prevents re-analyzing unchanged files.
"""

import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone

from config import config
from models.analysis import FileAnalysis

logger = logging.getLogger("viscode.cache")


class AnalysisCache:
    """Disk-based cache for file analysis results."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or config.get_cache_path()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    def _make_key(self, content_hash: str, model: str) -> str:
        """Create a cache key from file hash + model version."""
        raw = f"{content_hash}:{model}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _key_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        return self.cache_dir / f"{key}.json"

    def get(self, content_hash: str, model: str = "") -> FileAnalysis | None:
        """
        Look up a cached analysis result.

        Args:
            content_hash: SHA-256 hash of the file content.
            model: AI model version used for analysis.

        Returns:
            FileAnalysis if cached, None if not found.
        """
        if not content_hash:
            self._misses += 1
            return None

        model = model or config.OPENAI_MODEL_PASS1
        key = self._make_key(content_hash, model)
        path = self._key_path(key)

        if not path.exists():
            self._misses += 1
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            analysis = FileAnalysis(**data["analysis"])
            self._hits += 1
            logger.debug(f"Cache HIT: {key} ({analysis.file_path})")
            return analysis
        except Exception as e:
            logger.warning(f"Cache read error for {key}: {e}")
            self._misses += 1
            return None

    def put(self, content_hash: str, analysis: FileAnalysis, model: str = "") -> None:
        """
        Store an analysis result in cache.

        Args:
            content_hash: SHA-256 hash of the file content.
            analysis: The analysis result to cache.
            model: AI model version used.
        """
        if not content_hash:
            return

        model = model or config.OPENAI_MODEL_PASS1
        key = self._make_key(content_hash, model)
        path = self._key_path(key)

        try:
            data = {
                "content_hash": content_hash,
                "model": model,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "file_path": analysis.file_path,
                "analysis": analysis.model_dump(),
            }
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            logger.debug(f"Cache PUT: {key} ({analysis.file_path})")
        except Exception as e:
            logger.warning(f"Cache write error for {key}: {e}")

    def has(self, content_hash: str, model: str = "") -> bool:
        """Check if a cache entry exists without loading it."""
        if not content_hash:
            return False
        model = model or config.OPENAI_MODEL_PASS1
        key = self._make_key(content_hash, model)
        return self._key_path(key).exists()

    def clear(self) -> int:
        """Clear all cache entries. Returns number of entries removed."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        self._hits = 0
        self._misses = 0
        logger.info(f"Cache cleared: {count} entries removed")
        return count

    def stats(self) -> dict:
        """Return cache statistics."""
        entries = len(list(self.cache_dir.glob("*.json")))
        total_size = sum(f.stat().st_size for f in self.cache_dir.glob("*.json"))
        return {
            "entries": entries,
            "size_bytes": total_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / max(1, self._hits + self._misses),
        }
