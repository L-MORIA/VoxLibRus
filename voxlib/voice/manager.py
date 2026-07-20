"""Voice profile management with hash-based deduplication for VoxLibRus."""

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from voxlib.tts.base import VoiceProfile

logger = logging.getLogger(__name__)


@dataclass
class VoiceProfileMeta:
    """Metadata for a cached voice profile."""
    name: str
    backend: str
    ref_audio_hash: str
    ref_text_hash: str
    combined_hash: str
    created_at: str
    backend_version: str
    original_audio: str
    original_text: str
    file_size: int
    duration_sec: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "backend": self.backend,
            "ref_audio_hash": self.ref_audio_hash,
            "ref_text_hash": self.ref_text_hash,
            "combined_hash": self.combined_hash,
            "created_at": self.created_at,
            "backend_version": self.backend_version,
            "original_audio": self.original_audio,
            "original_text": self.original_text,
            "file_size": self.file_size,
            "duration_sec": self.duration_sec,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VoiceProfileMeta":
        return cls(**data)


class VoiceProfileManager:
    """Manages voice profile caching with hash-based deduplication."""

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = Path.home() / ".voxlib" / "voices"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir / "index.json"
        self._index: dict[str, VoiceProfileMeta] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Load voice profile index from disk."""
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._index = {k: VoiceProfileMeta.from_dict(v) for k, v in data.items()}
            except Exception as exc:
                logger.warning("Failed to load voice profile index %s: %s", self.index_path, exc)
                self._index = {}
        else:
            self._index = {}

    def _save_index(self) -> None:
        """Save voice profile index to disk."""
        data = {k: v.to_dict() for k, v in self._index.items()}
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _compute_hash(data: bytes) -> str:
        """Compute SHA256 hash of data."""
        return hashlib.sha256(data).hexdigest()[:16]  # Use first 16 chars for readability

    @staticmethod
    def _hash_file(path: str) -> str:
        """Compute hash of file contents."""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()[:16]

    def _compute_combined_hash(self, audio_path: str, text: str) -> str:
        """Compute combined hash of audio file + reference text."""
        audio_hash = self._hash_file(audio_path)
        text_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]
        combined = hashlib.sha256(f"{audio_hash}{text_hash}".encode()).hexdigest()[:16]
        return combined

    def get_cached_profile(self, audio_path: str, ref_text: str) -> Optional[VoiceProfile]:
        """Retrieve cached voice profile if exists and matches."""
        combined_hash = self._compute_combined_hash(audio_path, ref_text)
        if combined_hash in self._index:
            meta = self._index[combined_hash]
            profile_path = self.cache_dir / f"{combined_hash}.json"
            wav_path = self.cache_dir / f"{combined_hash}.wav"
            
            if profile_path.exists() and wav_path.exists():
                try:
                    with open(profile_path, "r", encoding="utf-8") as f:
                        json.load(f)  # validate JSON format
                    # Verify hashes still match
                    if meta.combined_hash == combined_hash:
                        return VoiceProfile(
                            name=meta.name,
                            backend=meta.backend,
                            ref_audio=str(wav_path),
                            ref_text=meta.original_text,
                            embedding_path="",
                            meta=meta.to_dict(),
                        )
                except Exception as exc:
                    logger.debug("Cache profile %s unreadable: %s", combined_hash, exc)
        return None

    def save_profile(
        self,
        profile: VoiceProfile,
        original_audio: str,
        original_text: str,
    ) -> str:
        """Save voice profile to cache. Returns combined hash.

        The cache key (combined_hash) is computed from the **original** audio
        path + reference text, matching what `get_cached_profile` looks up.
        Previously this used `profile.ref_audio` (the *processed* file), whose
        bytes differ on every ffmpeg run → cache miss was nearly guaranteed.
        """
        import soundfile as sf

        # Compute combined hash from the ORIGINAL inputs (C3 fix), so cache
        # lookups (which hash the same original inputs) actually hit.
        combined_hash = self._compute_combined_hash(original_audio, original_text)

        # Copy reference audio to cache
        cache_wav = self.cache_dir / f"{combined_hash}.wav"
        if not cache_wav.exists():
            shutil.copy2(profile.ref_audio, cache_wav)

        # Get audio info
        info = sf.info(str(cache_wav))
        duration = info.frames / info.samplerate

        # Create metadata
        meta = VoiceProfileMeta(
            name=profile.name,
            backend=profile.backend,
            ref_audio_hash=self._hash_file(profile.ref_audio),
            ref_text_hash=hashlib.sha256(profile.ref_text.strip().encode("utf-8")).hexdigest()[:16],
            combined_hash=combined_hash,
            created_at=datetime.utcnow().isoformat() + "Z",
            backend_version="1.0",
            original_audio=profile.ref_audio,
            original_text=profile.ref_text,
            file_size=os.path.getsize(str(cache_wav)),
            duration_sec=duration,
        )

        # Save metadata
        meta_path = self.cache_dir / f"{combined_hash}.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta.to_dict(), f, ensure_ascii=False, indent=2)

        # Update index
        self._index[combined_hash] = meta
        self._save_index()

        return combined_hash

    def get_profile(self, combined_hash: str) -> Optional[VoiceProfile]:
        """Load voice profile from cache."""
        if combined_hash not in self._index:
            return None
        meta = self._index[combined_hash]
        profile_path = self.cache_dir / f"{combined_hash}.json"
        wav_path = self.cache_dir / f"{combined_hash}.wav"
        if not profile_path.exists() or not wav_path.exists():
            return None
        with open(profile_path, "r", encoding="utf-8") as f:
            json.load(f)  # validate JSON
        return VoiceProfile(
            name=meta.name,
            backend=meta.backend,
            ref_audio=str(wav_path),
            ref_text=meta.original_text,
            embedding_path="",
            meta=meta.to_dict(),
        )

    def list_profiles(self) -> list[VoiceProfileMeta]:
        """List all cached voice profiles."""
        return list(self._index.values())

    def delete_profile(self, combined_hash: str) -> bool:
        """Delete a voice profile from cache."""
        if combined_hash not in self._index:
            return False

        (self.cache_dir / f"{combined_hash}.json").unlink(missing_ok=True)
        (self.cache_dir / f"{combined_hash}.wav").unlink(missing_ok=True)
        del self._index[combined_hash]
        self._save_index()
        return True

    def clear_cache(self) -> int:
        """Clear all cached profiles. Returns count of deleted profiles."""
        count = len(self._index)
        for combined_hash in list(self._index.keys()):
            self.delete_profile(combined_hash)
        return count

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        total_size = sum(
            (self.cache_dir / f"{h}.wav").stat().st_size
            for h in self._index
            if (self.cache_dir / f"{h}.wav").exists()
        )
        return {
            "profile_count": len(self._index),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir),
        }


# Global instance
_voice_manager: Optional[VoiceProfileManager] = None


def get_voice_manager(cache_dir: Optional[Path] = None) -> VoiceProfileManager:
    """Get global voice profile manager instance."""
    global _voice_manager
    if _voice_manager is None:
        _voice_manager = VoiceProfileManager(cache_dir)
    return _voice_manager