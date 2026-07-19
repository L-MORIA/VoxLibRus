"""CLI entry point for VoxLibRus."""

# ruff: noqa: E402 — setup_gpu_compat() must run before voxlib imports

import json
import typer
from pathlib import Path
from typing import Optional

# GPU / audio compatibility setup (must run before any voxlib imports)
from voxlib.utils.setup import setup_gpu_compat
setup_gpu_compat()

from voxlib.config import Config
from voxlib.pipeline import run_audiobook
from voxlib.text.extractor import extract as extract_text
from voxlib.text.chunker import chunk_text
from voxlib.voice.cloner import VoiceCloner
from voxlib.asr.gigaam import GigaAMBackend
from voxlib.asr.whisper import WhisperBackend

app = typer.Typer(help="VoxLibRus — Russian audiobook generation with voice cloning")


def _load_config(config_path: Optional[Path]) -> Config:
    """Load configuration from file or defaults."""
    if config_path and config_path.exists():
        return Config.from_yaml(config_path)
    return Config.from_yaml()


def _parse_chapter_range(range_str: str) -> list[int]:
    """Parse chapter range string like '1-5,7,10-12' into list of chapter numbers (1-indexed)."""
    chapters = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = map(int, part.split("-"))
            chapters.update(range(start, end + 1))
        else:
            chapters.add(int(part))
    return sorted(chapters)


def _filter_chapters(chapters: dict, chapter_range: Optional[list[int]]) -> dict:
    """Filter chapters by 1-indexed chapter numbers."""
    if chapter_range is None:
        return chapters
    return {title: text for i, (title, text) in enumerate(chapters.items(), 1) if i in chapter_range}


def _parse_skip_stages(skip_str: str) -> set[str]:
    """Parse skip stages string like 'extract,clean,accents' into set."""
    if not skip_str:
        return set()
    return {s.strip() for s in skip_str.split(",") if s.strip()}


def _parse_chapter_range(range_str: str) -> list[int]:
    """Parse chapter range string like '1-5,7,10-12' into list of chapter numbers (1-indexed)."""
    chapters = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = map(int, part.split("-"))
            chapters.update(range(start, end + 1))
        else:
            chapters.add(int(part))
    return sorted(chapters)


def _filter_chapters(chapters: dict, chapter_range: Optional[list[int]]) -> dict:
    """Filter chapters by 1-indexed chapter numbers."""
    if chapter_range is None:
        return chapters
    return {title: text for i, (title, text) in enumerate(chapters.items(), 1) if i in chapter_range}


def _parse_skip_stages(skip_str: str) -> set[str]:
    """Parse skip stages string like 'extract,clean,accents' into set."""
    if not skip_str:
        return set()
    return {s.strip() for s in skip_str.split(",") if s.strip()}


@app.command()
def run(
    book: Path = typer.Option(..., "--book", help="Path to book (PDF/EPUB/DOCX)"),
    reference: Path = typer.Option(..., "--reference", help="Path to author reference audio (WAV)"),
    output: str = typer.Option("audiobook", "--output", help="Output name (without extension)"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
    force_restart: bool = typer.Option(False, "--force", help="Ignore existing pipeline state"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without executing"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose/debug logging"),
    workers: int = typer.Option(0, "--workers", help="Number of parallel workers (0 = sequential)"),
    skip_stages: str = typer.Option("", "--skip-stages", help="Comma-separated stages to skip: extract,clean,accents,clone,generate,normalize,assemble"),
    resume: bool = typer.Option(False, "--resume", help="Resume from last saved state"),
    chapters: str = typer.Option("", "--chapters", help="Chapter range like '1-5,7,10-12'"),
):
    """Full pipeline: extract → transcribe → clone → generate → assemble."""
    config_obj = _load_config(config)

    # Setup verbose logging
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Parse chapter range
    chapter_list = _parse_chapter_range(chapters) if chapters else None

    # Parse skip stages
    skip_stages_set = _parse_skip_stages(skip_stages)
    valid_stages = {"extract", "clean", "accents", "chunk", "clone", "generate", "normalize", "assemble"}
    invalid = skip_stages_set - valid_stages
    if invalid:
        typer.echo(f"❌ Invalid stages: {', '.join(invalid)}. Valid: {', '.join(sorted(valid_stages))}", err=True)
        raise typer.Exit(1)

    # Dry run mode
    if dry_run:
        typer.echo("🔍 DRY RUN MODE - showing what would be done:")
        typer.echo(f"  📖 Book: {book}")
        typer.echo(f"  🎤 Reference: {reference}")
        typer.echo(f"  🔊 Output: {output}")
        typer.echo(f"  ⚙️  Config: {config or 'default'}")
        typer.echo(f"  🎭 Voice: {output}")
        typer.echo(f"  📚 Chapters: {chapters or 'all'}")
        typer.echo(f"  ⏭️  Skip stages: {skip_stages or 'none'}")
        typer.echo(f"  🔄 Resume: {resume}")
        typer.echo(f"  👥 Workers: {workers if workers > 0 else 'sequential'}")
        typer.echo(f"  🚫 Force restart: {force_restart}")
        raise typer.Exit(0)

    typer.echo(f"📖 Book: {book}")
    typer.echo(f"🎤 Reference: {reference}")
    typer.echo(f"🔊 Output: {output}")
    typer.echo(f"⚙️  Config: {config or 'default'}")
    if verbose:
        typer.echo(f"  Chapters: {chapters or 'all'}")
        typer.echo(f"  Skip: {skip_stages or 'none'}")
        typer.echo(f"  Resume: {resume}")
        typer.echo(f"  Workers: {workers if workers > 0 else 'sequential'}")

    result = run_audiobook(
        book_path=str(book),
        voice_ref_audio=str(reference),
        voice_ref_text=None,  # will be transcribed
        voice_name=output,
        force_restart=force_restart,
        config_path=str(config) if config else None,
    )

    typer.echo("\n✅ Done!")
    typer.echo(f"📁 MP3: {result.get('mp3', 'N/A')}")
    typer.echo(f"📁 M4B: {result.get('m4b', 'N/A')}")
    typer.echo(f"📄 State: {result.get('state_file', 'N/A')}")


@app.command()
def extract(
    book: Path = typer.Option(..., "--book", help="Path to book"),
    output: Path = typer.Option("chunks.json", "--output", "-o", help="Output JSON file"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
    chapters: str = typer.Option("", "--chapters", help="Chapter range like '1-5,7,10-12'"),
):
    """Extract and chunk text from a book (PDF/EPUB/DOCX)."""
    config_obj = _load_config(config)
    typer.echo(f"📖 Extracting: {book} → {output}")

    chapters = extract_text(str(book))

    # Filter chapters if range specified
    chapter_list = _parse_chapter_range(chapters) if chapters else None
    if chapter_list:
        chapters = _filter_chapters(chapters, chapter_list)
        typer.echo(f"Filtered to chapters: {chapter_list}")

    typer.echo(f"Found {len(chapters)} chapters")

    # Clean text
    from voxlib.text.cleaner import clean_text
    from voxlib.text.accents import fix_accents
    cleaned = {}
    for title, text in chapters.items():
        cleaned[title] = fix_accents(clean_text(text))

    # Chunk text
    chunks = chunk_text(cleaned)
    typer.echo(f"Created {len(chunks)} chunks")

    # Save
    output_data = {
        "chapters": cleaned,
        "chunks": chunks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"✅ Saved to {output}")


@app.command()
def transcribe(
    audio: Path = typer.Option(..., "--audio", help="Path to reference audio"),
    output: Path = typer.Option("reference_text.txt", "--output", "-o", help="Output text file"),
    backend: str = typer.Option("auto", "--backend", help="ASR backend: gigaam | whisper | auto"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
):
    """Transcribe reference audio using ASR."""
    config_obj = _load_config(config)
    typer.echo(f"🎤 Transcribing: {audio} → {output} (backend={backend})")

    # Select backend
    if backend == "gigaam" or (backend == "auto" and config_obj.asr.primary == "gigaam"):
        asr_backend = GigaAMBackend(config_obj.asr.gigaam)
    elif backend == "whisper" or (backend == "auto" and config_obj.asr.primary == "whisper"):
        asr_backend = WhisperBackend(config_obj.asr.whisper)
    else:
        raise ValueError(f"Unknown backend: {backend}")

    result = asr_backend.transcribe(str(audio))
    typer.echo(f"Transcribed: {result.text[:100]}...")
    typer.echo(f"Duration: {result.duration_seconds:.1f}s")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.text, encoding="utf-8")
    typer.echo(f"✅ Saved to {output}")


@app.command()
def clone(
    audio: Path = typer.Option(..., "--audio", help="Path to reference audio"),
    text: Path = typer.Option(..., "--text", help="Path to reference text"),
    name: str = typer.Option("default", "--name", help="Voice profile name"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
):
    """Clone voice from reference audio + text."""
    config_obj = _load_config(config)
    typer.echo(f"🎭 Cloning voice: {audio} + {text} → profile '{name}'")

    ref_text = text.read_text(encoding="utf-8")

    cloner = VoiceCloner(config_obj)
    voice = cloner.clone_voice(
        ref_audio_path=str(audio),
        ref_text=ref_text,
        name=name,
    )

    typer.echo(f"✅ Voice cloned: {voice.name}")
    typer.echo(f"   Backend: {voice.backend}")
    typer.echo(f"   Ref audio: {voice.ref_audio}")
    typer.echo(f"   Ref text: {voice.ref_text[:50]}...")


@app.command()
def generate(
    chunks: Path = typer.Option(..., "--chunks", help="Path to chunks.json"),
    voice: str = typer.Option("default", "--voice", help="Voice profile name"),
    output: Path = typer.Option("output", "--output", "-o", help="Output directory"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
):
    """Generate audio for all chunks using cloned voice."""
    _load_config(config)
    typer.echo(f"📖 Generating {chunks} with voice '{voice}' → {output}")

    chunks_data = json.loads(chunks.read_text(encoding="utf-8"))
    chunks_data.get("chunks", [])

    # For now, we need a voice profile - load from saved profiles or create new
    typer.echo("🚧 Batch generation from chunks.json not fully wired yet")
    typer.echo("   Use 'voxlib run' for full pipeline")


@app.command()
def assemble(
    chapters_dir: Path = typer.Option(..., "--chapters", help="Directory with chapter WAVs"),
    output: str = typer.Option("audiobook", "--output", "-o", help="Output base name"),
    format: str = typer.Option("mp3", "--format", help="Output format: mp3 | m4b | both"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
):
    """Assemble audiobook from generated chapter WAVs."""
    config_obj = _load_config(config)
    typer.echo(f"🔊 Assembling: {chapters_dir} → {output}.{format}")

    from voxlib.audio.assemble import assemble_audiobook

    # Find chapter files
    chapter_files = sorted(chapters_dir.glob("*.wav"))
    if not chapter_files:
        typer.echo("❌ No WAV files found in chapters directory")
        raise typer.Exit(1)

    typer.echo(f"Found {len(chapter_files)} chapters")

    # Always compute intermediate MP3 (needed for M4B conversion too)
    output_mp3 = f"{output}.mp3"
    output_m4b = None
    if format in ("m4b", "both"):
        output_m4b = f"{output}.m4b"

    assemble_audiobook(
        chunk_files=[str(f) for f in chapter_files],
        output_mp3=output_mp3,
        output_m4b=output_m4b,
        chapter_titles=[f.stem for f in chapter_files],
        chapter_pause_sec=config_obj.audio.chapter_pause_sec,
    )

    typer.echo("✅ Assembly complete")

    # Cleanup: remove intermediate MP3 if user requested M4B only
    if format == "m4b" and Path(output_mp3).exists():
        Path(output_mp3).unlink()


@app.command()
def list_voices(
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
):
    """List available voice profiles."""
    config_obj = _load_config(config)
    cloner = VoiceCloner(config_obj)
    profiles_dir = Path(config_obj.voice.profiles_dir).expanduser()

    if not profiles_dir.exists():
        typer.echo("No voice profiles found")
        return

    typer.echo("Available voice profiles:")
    for profile_file in sorted(profiles_dir.glob("*.json")):
        import json
        with open(profile_file) as f:
            data = json.load(f)
        typer.echo(f"  • {data.get('name', profile_file.stem)} ({data.get('backend', 'unknown')})")


@app.command()
def delete_voice(
    name: str = typer.Option(..., "--name", help="Voice profile name to delete"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation"),
):
    """Delete a voice profile."""
    config_obj = _load_config(config)
    cloner = VoiceCloner(config_obj)

    # VoiceCloner manages profiles - need to implement delete
    # For now, just remove the JSON and WAV files
    profiles_dir = Path(config_obj.voice.profiles_dir).expanduser()
    json_path = profiles_dir / f"{name}.json"
    wav_path = profiles_dir / f"{name}_ref.wav"

    if not json_path.exists():
        typer.echo(f"❌ Voice profile '{name}' not found")
        raise typer.Exit(1)

    if not force:
        confirm = typer.confirm(f"Delete voice profile '{name}'?")
        if not confirm:
            typer.echo("Cancelled")
            raise typer.Exit(0)

    json_path.unlink(missing_ok=True)
    wav_path.unlink(missing_ok=True)
    typer.echo(f"✅ Deleted voice profile '{name}'")


if __name__ == "__main__":
    app()