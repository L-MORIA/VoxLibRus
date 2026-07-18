"""CLI entry point for VoxLibRus."""

import json
import typer
from pathlib import Path
from typing import Optional

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


@app.command()
def run(
    book: Path = typer.Option(..., "--book", help="Path to book (PDF/EPUB/DOCX)"),
    reference: Path = typer.Option(..., "--reference", help="Path to author reference audio (WAV)"),
    output: str = typer.Option("audiobook", "--output", help="Output name (without extension)"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config.yaml"),
    force_restart: bool = typer.Option(False, "--force", help="Ignore existing pipeline state"),
):
    """Full pipeline: extract → transcribe → clone → generate → assemble."""
    _load_config(config)
    typer.echo(f"📖 Book: {book}")
    typer.echo(f"🎤 Reference: {reference}")
    typer.echo(f"🔊 Output: {output}")
    typer.echo(f"⚙️  Config: {config or 'default'}")

    result = run_audiobook(
        book_path=str(book),
        voice_ref_audio=str(reference),
        voice_ref_text=None,  # will be transcribed
        voice_name=output,
        force_restart=force_restart,
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
):
    """Extract and chunk text from a book (PDF/EPUB/DOCX)."""
    _load_config(config)
    typer.echo(f"📖 Extracting: {book} → {output}")

    chapters = extract_text(str(book))
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
    if backend == "gigaam" or (backend == "auto" and "gigaam" in str(config_obj.asr.gigaam.model_id).lower()):
        asr_backend = GigaAMBackend(config_obj.asr.gigaam)
    elif backend == "whisper" or backend == "auto":
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

    output_mp3 = None
    output_m4b = None

    if format in ("mp3", "both"):
        output_mp3 = f"{output}.mp3"
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


if __name__ == "__main__":
    app()