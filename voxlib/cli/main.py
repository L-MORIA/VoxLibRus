"""CLI entry point for VoxLibRus."""

import typer
from pathlib import Path

app = typer.Typer(help="VoxLibRus — Russian audiobook generation with voice cloning")


@app.command()
def run(
    book: Path = typer.Option(..., "--book", help="Path to book (PDF/EPUB/DOCX)"),
    reference: Path = typer.Option(..., "--reference", help="Path to author reference audio (WAV)"),
    output: str = typer.Option("audiobook", "--output", help="Output name (without extension)"),
    config: Path = typer.Option(None, "--config", help="Path to config.yaml"),
):
    """Full pipeline: extract → transcribe → clone → generate → assemble."""
    typer.echo(f"📖 Book: {book}")
    typer.echo(f"🎤 Reference: {reference}")
    typer.echo(f"🔊 Output: {output}")
    typer.echo("🚧 Pipeline not yet implemented — coming in v0.2.0")


@app.command()
def extract(
    book: Path = typer.Option(..., "--book", help="Path to book"),
    output: Path = typer.Option("chunks.json", "--output", "-o"),
):
    """Extract and chunk text from a book."""
    typer.echo(f"📖 Extracting: {book} → {output}")
    typer.echo("🚧 Not yet implemented")


@app.command()
def transcribe(
    audio: Path = typer.Option(..., "--audio", help="Path to reference audio"),
    output: Path = typer.Option("reference_text.txt", "--output", "-o"),
    backend: str = typer.Option("auto", "--backend", help="ASR backend: gigaam | whisper | auto"),
):
    """Transcribe reference audio using ASR."""
    typer.echo(f"🎤 Transcribing: {audio} → {output} (backend={backend})")
    typer.echo("🚧 Not yet implemented")


@app.command()
def clone(
    audio: Path = typer.Option(..., "--audio", help="Path to reference audio"),
    text: Path = typer.Option(..., "--text", help="Path to reference text"),
    name: str = typer.Option("default", "--name", help="Voice profile name"),
):
    """Clone voice from reference audio + text."""
    typer.echo(f"🎭 Cloning voice: {audio} + {text} → profile '{name}'")
    typer.echo("🚧 Not yet implemented")


@app.command()
def generate(
    chunks: Path = typer.Option(..., "--chunks", help="Path to chunks.json"),
    voice: str = typer.Option("default", "--voice", help="Voice profile name"),
):
    """Generate audio for all chunks using cloned voice."""
    typer.echo(f"📖 Generating {chunks} with voice '{voice}'")
    typer.echo("🚧 Not yet implemented")


@app.command()
def assemble(
    chapters_dir: Path = typer.Option(..., "--chapters", help="Directory with chapter WAVs"),
    output: str = typer.Option("audiobook", "--output", "-o"),
):
    """Assemble audiobook from generated chapters."""
    typer.echo(f"🔊 Assembling: {chapters_dir} → {output}")
    typer.echo("🚧 Not yet implemented")


if __name__ == "__main__":
    app()
