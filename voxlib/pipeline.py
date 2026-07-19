"""Main pipeline orchestrator for VoxLibRus.

End-to-end audiobook generation:
extract → clean → accents → chunk → ASR → clone → generate → normalize → assemble
"""

import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from voxlib.config import Config
from voxlib.text.extractor import extract
from voxlib.text.cleaner import clean_text
from voxlib.text.accents import fix_accents
from voxlib.text.chunker import chunk_text
from voxlib.voice.cloner import VoiceCloner
from voxlib.tts.base import VoiceProfile
from voxlib.audio.normalize import loudness_normalize
from voxlib.audio.assemble import assemble_audiobook


@dataclass
class PipelineState:
    """Tracks progress through the pipeline for resume capability."""
    book_path: str
    book_name: str
    output_dir: str
    temp_dir: str
    voice_name: str
    voice_ref_audio: str = ""
    voice_ref_text: Optional[str] = None

    # Progress tracking
    stages_completed: list[str] = field(default_factory=list)
    chunks_total: int = 0
    chunks_generated: list[int] = field(default_factory=list)
    chunks_failed: list[dict] = field(default_factory=list)

    # Metadata
    voice_profile: Optional[dict] = None
    tts_backend: str = "f5tts"
    asr_backend: str = "gigaam"
    final_mp3: Optional[str] = None
    final_m4b: Optional[str] = None

    # Book integrity for safe resume
    book_hash: str = ""

    # Dynamic fields (filled during pipeline stages)
    chapters: Optional[dict] = None
    cleaned_chapters: Optional[dict] = None
    accented_chapters: Optional[dict] = None
    chunks: Optional[list] = None
    normalized_chunks: Optional[list] = None

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, data: str) -> "PipelineState":
        return cls(**json.loads(data))

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "PipelineState":
        return cls.from_json(path.read_text(encoding="utf-8"))


class Pipeline:
    """Main pipeline orchestrator for audiobook generation."""

    def __init__(
        self,
        config: Optional[Config] = None,
        config_path: Optional[str] = None,
        resume_from: Optional[str] = None,
    ):
        if config is not None:
            self.config = config
        elif config_path:
            self.config = Config.from_yaml(config_path)
        else:
            self.config = Config.from_yaml()

        # Initialize components
        self.voice_cloner = VoiceCloner(self.config)

        # State
        self.state: Optional[PipelineState] = None

        # Resume if requested
        if resume_from:
            self._resume(resume_from)

    def _resume(self, resume_path: str):
        """Load state from previous run."""
        path = Path(resume_path)
        if not path.exists():
            raise FileNotFoundError(f"Resume state not found: {resume_path}")

        self.state = PipelineState.load(path)
        
        # Verify book hasn't changed
        current_hash = self._compute_book_hash(Path(self.state.book_path))
        if current_hash != self.state.book_hash:
            raise ValueError(
                f"Book file has changed since last run (hash mismatch). "
                f"Expected: {self.state.book_hash[:16]}..., got: {current_hash[:16]}... "
                f"Use --force to restart from scratch."
            )
        
        print(f"Resumed from state: {path}")
        print(f"Completed stages: {self.state.stages_completed}")

    def _compute_book_hash(self, book_path: Path) -> str:
        """Compute SHA256 hash of book file for resume safety."""
        hasher = hashlib.sha256()
        with open(book_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _create_state(self, book_path: str, voice_name: str) -> PipelineState:
        """Create initial pipeline state."""
        book_path = Path(book_path)
        output_dir = Path(self.config.project.output_dir) / book_path.stem
        temp_dir = Path(self.config.project.temp_dir) / book_path.stem

        # Compute book hash for resume safety
        book_hash = self._compute_book_hash(book_path)

        return PipelineState(
            book_path=str(book_path),
            book_name=book_path.stem,
            output_dir=str(output_dir),
            temp_dir=str(temp_dir),
            voice_name=voice_name,
            book_hash=book_hash,
        )

    def _save_state(self):
        """Persist state to disk."""
        if self.state:
            state_path = Path(self.state.temp_dir) / "pipeline_state.json"
            self.state.save(state_path)

    def run(
        self,
        book_path: str,
        voice_ref_audio: str,
        voice_ref_text: Optional[str] = None,
        voice_name: Optional[str] = None,
        force_restart: bool = False,
    ) -> dict:
        """Run the full audiobook generation pipeline.

        Args:
            book_path: Path to input book (PDF/EPUB/DOCX).
            voice_ref_audio: Path to reference audio (5-30 seconds of author reading).
            voice_ref_text: Optional accurate transcription of reference audio.
            voice_name: Name for the voice profile (default: book name).
            force_restart: If True, ignore any existing state and start fresh.

        Returns:
            Dict with paths to generated audiobook files.
        """
        book_path = Path(book_path)
        if not book_path.exists():
            raise FileNotFoundError(f"Book not found: {book_path}")

        voice_name = voice_name or book_path.stem

        # Initialize or resume state
        if not force_restart and self.state is not None:
            state = self.state
        else:
            state = self._create_state(book_path, voice_name)

        self.state = state
        state.voice_ref_audio = voice_ref_audio
        state.voice_ref_text = voice_ref_text
        self._save_state()

        try:
            # Stage 1: Extract text from book
            if "extract" not in state.stages_completed:
                print("\n=== Stage 1: Extracting text ===")
                chapters = extract(book_path)
                state.chapters = chapters
                state.stages_completed.append("extract")
                self._save_state()
                print(f"Extracted {len(chapters)} chapters")

            # Stage 2: Clean text
            if "clean" not in state.stages_completed:
                print("\n=== Stage 2: Cleaning text ===")
                cleaned_chapters = {}
                for title, text in state.chapters.items():
                    cleaned_chapters[title] = clean_text(text)
                state.cleaned_chapters = cleaned_chapters
                state.stages_completed.append("clean")
                self._save_state()
                print("Text cleaning complete")

            # Stage 3: Add stress marks (accents)
            if "accents" not in state.stages_completed:
                print("\n=== Stage 3: Adding stress marks ===")
                accented_chapters = {}
                for title, text in state.cleaned_chapters.items():
                    accented_chapters[title] = fix_accents(text)
                state.accented_chapters = accented_chapters
                state.stages_completed.append("accents")
                self._save_state()
                print("Stress marks added")

            # Stage 4: Chunk text
            if "chunk" not in state.stages_completed:
                print("\n=== Stage 4: Chunking text ===")
                chunks = chunk_text(state.accented_chapters)
                state.chunks = chunks
                state.chunks_total = len(chunks)
                state.stages_completed.append("chunk")
                self._save_state()
                print(f"Created {len(chunks)} chunks")

            # Stage 5: Voice cloning
            if "clone" not in state.stages_completed:
                print("\n=== Stage 5: Voice cloning ===")
                voice_profile = self.voice_cloner.clone_voice(
                    ref_audio_path=state.voice_ref_audio,
                    ref_text=state.voice_ref_text,
                    name=state.voice_name,
                )
                # Serialize prompt_items for JSON storage if Qwen3 backend
                meta = voice_profile.meta.copy()
                if voice_profile.backend == "qwen3" and "prompt_items" in meta:
                    # Get Qwen3 backend to use its serializer
                    tts_backend = self.voice_cloner._get_tts_backend()
                    if hasattr(tts_backend, '_serialize_prompt_items'):
                        meta["prompt_items"] = tts_backend._serialize_prompt_items(meta["prompt_items"])
                
                state.voice_profile = {
                    "name": voice_profile.name,
                    "backend": voice_profile.backend,
                    "ref_audio": voice_profile.ref_audio,
                    "ref_text": voice_profile.ref_text,
                    "meta": meta,
                }
                state.stages_completed.append("clone")
                self._save_state()
                print(f"Voice cloned: {voice_profile.name}")

            # Stage 6: Generate audio chunks
            if "generate" not in state.stages_completed:
                print("\n=== Stage 6: Generating audio chunks ===")
                voice = VoiceProfile(**state.voice_profile)
                chapter_dir = Path(state.temp_dir) / "chapters"
                chapter_dir.mkdir(parents=True, exist_ok=True)

                generated_paths = self.voice_cloner.generate_batch(
                    texts=[c["text"] for c in state.chunks],
                    voice=voice,
                    output_dir=str(chapter_dir),
                )
                state.chunks_generated = [str(p) for p in generated_paths]
                state.stages_completed.append("generate")
                self._save_state()
                print(f"Generated {len(generated_paths)} audio chunks")

            # Stage 7: Normalize loudness
            if "normalize" not in state.stages_completed:
                print("\n=== Stage 7: Normalizing loudness ===")
                norm_dir = Path(state.temp_dir) / "normalized"
                norm_dir.mkdir(parents=True, exist_ok=True)

                normalized_paths = []
                for i, path in enumerate(state.chunks_generated):
                    out_path = norm_dir / Path(path).name
                    loudness_normalize(path, str(out_path), target_lufs=-16.0)
                    normalized_paths.append(str(out_path))

                state.normalized_chunks = normalized_paths
                state.stages_completed.append("normalize")
                self._save_state()
                print("Loudness normalization complete")

            # Stage 8: Assemble final audiobook
            if "assemble" not in state.stages_completed:
                print("\n=== Stage 8: Assembling audiobook ===")
                output_dir = Path(state.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)

                mp3_path = output_dir / f"{state.book_name}.mp3"
                m4b_path = output_dir / f"{state.book_name}.m4b"

                assemble_audiobook(
                    chunk_files=state.normalized_chunks,
                    output_mp3=str(mp3_path),
                    output_m4b=str(m4b_path) if self.config.audio.output.format in ("m4b", "both") else None,
                    chapter_titles=[c["chapter"] for c in state.chunks],
                    chapter_pause_sec=self.config.audio.chapter_pause_sec,
                )

                state.final_mp3 = str(mp3_path)
                if m4b_path.exists():
                    state.final_m4b = str(m4b_path)
                state.stages_completed.append("assemble")
                self._save_state()
                print(f"Audiobook assembled: {mp3_path}")

            # Final state
            state.stages_completed.append("complete")
            self._save_state()

            return {
                "mp3": state.final_mp3,
                "m4b": state.final_m4b,
                "state_file": str(Path(state.temp_dir) / "pipeline_state.json"),
            }

        except Exception:
            # Save state on error for potential resume
            self._save_state()
            raise

    def run_stage(self, stage: str, **kwargs) -> None:
        """Run a single pipeline stage (for testing/debugging)."""
        # TODO: implement individual stage runner
        raise NotImplementedError("Individual stage runner not yet implemented")


def run_audiobook(
    book_path: str,
    voice_ref_audio: str,
    voice_ref_text: Optional[str] = None,
    voice_name: Optional[str] = None,
    config_path: Optional[str] = None,
    force_restart: bool = False,
) -> dict:
    """Convenience function to run full pipeline.

    Args:
        book_path: Path to book file (PDF/EPUB/DOCX).
        voice_ref_audio: Path to reference audio (author reading 5-30 sec).
        voice_ref_text: Optional transcription of reference audio.
        voice_name: Name for voice profile.
        config_path: Optional path to config.yaml.
        force_restart: Ignore existing state.

    Returns:
        Dict with output file paths.
    """
    pipeline = Pipeline(config_path=config_path)
    return pipeline.run(
        book_path=book_path,
        voice_ref_audio=voice_ref_audio,
        voice_ref_text=voice_ref_text,
        voice_name=voice_name,
        force_restart=force_restart,
    )