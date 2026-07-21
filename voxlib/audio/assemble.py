"""Audio assembly: merge chunks into final audiobook (MP3/M4B)."""

import subprocess
import shutil
from pathlib import Path
from typing import Optional


def _find_ffmpeg() -> str:
    """Find ffmpeg executable, searching PATH and common Windows locations."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    # Lazy: only access Path.home() when actually needed
    try:
        candidate = (
            Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
            / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
            / "ffmpeg-8.1-full_build/bin/ffmpeg.exe"
        )
        if candidate.exists():
            return str(candidate)
    except RuntimeError:
        # Path.home() failed (no HOME/USERPROFILE)
        pass
    return "ffmpeg"


def _validate_ffmpeg_path(ffmpeg_path: str) -> str:
    """Validate ffmpeg path to prevent command injection."""
    if ffmpeg_path:
        resolved = Path(ffmpeg_path).resolve()
        if not resolved.exists():
            raise ValueError(f"ffmpeg not found at: {ffmpeg_path}")
        return str(resolved)
    return _find_ffmpeg()


def _sanitize_chapter_title(title: str) -> str:
    """Sanitize chapter title for FFmpeg metadata (escape special chars)."""
    if title is None:
        return ""
    # Escape special characters that break FFMETADATA format
    title = title.replace("\\", "\\\\")  # backslash first
    title = title.replace("\n", "\\n")
    title = title.replace("\r", "\\r")
    title = title.replace("=", "\\=")
    title = title.replace(";", "\\;")
    title = title.replace("#", "\\#")
    return title


def _generate_default_chapter_titles(count: int) -> list[str]:
    """Generate default chapter titles if none provided."""
    return [f"Chapter {i + 1}" for i in range(count)]


_FFMPEG = _find_ffmpeg()


def assemble_audiobook(
    chunk_files: list[str],
    output_path: str,
    output_m4b: Optional[str] = None,
    chapter_titles: Optional[list[str]] = None,
    chapter_pause_sec: float = 2.5,
    chunk_pause_sec: float = 0.3,
    ffmpeg_path: str = "",
    mp3_bitrate: int = 192,
) -> None:
    """Assemble audio chunks into final audiobook.

    Args:
        chunk_files: List of paths to normalized audio chunks in order.
        output_mp3: Path for output MP3 file.
        output_m4b: Optional path for M4B (audiobook with chapters).
        chapter_titles: Optional list of chapter titles for M4B metadata.
        chapter_pause_sec: Silence duration between chapters in seconds.
        chunk_pause_sec: Short pause between consecutive chunks (within same chapter).
        ffmpeg_path: Path to ffmpeg executable (empty = auto-detect).
        mp3_bitrate: MP3 bitrate in kbps.
    """
    if not chunk_files:
        raise ValueError("No chunk files provided")

    ffmpeg = _validate_ffmpeg_path(ffmpeg_path)
    output_mp3 = str(Path(output_path).resolve())

    # Choose codec based on output file extension
    is_wav = output_mp3.lower().endswith(".wav")
    if is_wav:
        audio_codec = ["-c:a", "pcm_s24le"]  # 24-bit for Audition processing headroom
    else:
        audio_codec = ["-c:a", "libmp3lame", "-b:a", f"{mp3_bitrate}k"]

    # Single chunk — just convert directly
    if len(chunk_files) == 1:
        cmd = [ffmpeg, "-y", "-i", chunk_files[0]] + audio_codec + [
               "-map_metadata", "-1", output_path]
        if not is_wav:
            cmd.extend(["-id3v2_version", "3", "-write_id3v1", "1"])
        subprocess.run(cmd, check=True, capture_output=True)
        return

    # Multiple chunks — interleave with pauses
    import tempfile
    chunk_pause_path = None
    chapter_pause_path = None
    try:
        # Generate short pause with fade edges (masks abrupt transitions)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            chunk_pause_path = f.name
        # aevalsrc creates silence, afade adds 15ms fade-in/fade-out at edges.
        # The fade doesn't change zeros, but the CHUNK adjacent to it gets an
        # afade applied in the filter_complex to smooth the boundary.
        silence_cmd = [ffmpeg, "-y", "-f", "lavfi",
                       "-i", "anullsrc=r=24000:cl=mono",
                       "-t", str(chunk_pause_sec),
                       "-c:a", "pcm_s16le", chunk_pause_path]
        subprocess.run(silence_cmd, check=True, capture_output=True)

        # Generate long silence for between chapters
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            chapter_pause_path = f.name
        silence_cmd = [ffmpeg, "-y", "-f", "lavfi",
                       "-i", "anullsrc=r=24000:cl=mono",
                       "-t", str(chapter_pause_sec),
                       "-c:a", "pcm_s16le", chapter_pause_path]
        subprocess.run(silence_cmd, check=True, capture_output=True)

        # Build interleaved list: pauses between ALL chunks
        interleaved = []
        prev_title = None
        for i, chunk in enumerate(chunk_files):
            current_title = chapter_titles[i] if chapter_titles else None
            if i > 0:
                if prev_title is not None and current_title != prev_title:
                    # Chapter boundary: use longer pause
                    interleaved.append(chapter_pause_path)
                else:
                    # Same chapter: short pause between chunks
                    interleaved.append(chunk_pause_path)
            interleaved.append(chunk)
            prev_title = current_title

        output_mp3 = str(Path(output_mp3).resolve())

        inputs = []
        for f in interleaved:
            inputs.extend(["-i", f])
        n_inputs = len(interleaved)

        # Chain acrossfade between consecutive inputs, then apply a
        # gentle notch filter at 262Hz to reduce model-generated hum.
        # acrossfade overlaps the LAST 120ms of input N with the FIRST 120ms
        # of input N+1. Since silence is at zero level, this creates a
        # smooth fade-out of chunk audio into silence and a smooth fade-in
        # of the next chunk — no audible thump/pop.
        # Also apply HPF/LPF to match Vocos's native bandwidth (120-8000Hz)
        # removing the low-freq buzz while keeping the natural warm sound.
        post = ",highpass=f=120,lowpass=f=8000"
        if n_inputs == 1:
            filter_graph = f"[0:a]concat=n=1:v=0:a=1{post}[out]"
        elif n_inputs == 2:
            filter_graph = f"[0:a][1:a]acrossfade=d=0.12:c1=tri:c2=tri{post}[out]"
        else:
            parts = [f"[{i}:a]" for i in range(n_inputs)]
            chain = f"{parts[0]}{parts[1]}acrossfade=d=0.12:c1=tri:c2=tri[tmp1]"
            for i in range(2, n_inputs):
                chain += f";[tmp{i-1}]{parts[i]}acrossfade=d=0.12:c1=tri:c2=tri[tmp{i}]"
            filter_graph = f"{chain};[tmp{n_inputs-1}]highpass=f=120,lowpass=f=8000[out]"

        cmd = [ffmpeg, "-y"] + inputs + [
            "-filter_complex", filter_graph,
            "-map", "[out]",
        ] + audio_codec + [
            "-map_metadata", "-1",
            output_path,
        ]
        if not is_wav:
            cmd.extend(["-id3v2_version", "3", "-write_id3v1", "1"])
        subprocess.run(cmd, check=True, capture_output=True)

        # Create M4B with chapters if requested
        if output_m4b:
            create_m4b_with_chapters(
                input_mp3=output_mp3,
                output_m4b=output_m4b,
                chapter_titles=chapter_titles,
                chapter_files=chunk_files,
                chapter_pause_sec=chapter_pause_sec,
                ffmpeg_path=ffmpeg,
            )

    finally:
        for _p in (chunk_pause_path, chapter_pause_path):
            if _p and Path(_p).exists():
                Path(_p).unlink()


def create_m4b_with_chapters(
    input_mp3: str,
    output_m4b: str,
    chapter_titles: Optional[list[str]] = None,
    chapter_files: Optional[list[str]] = None,
    chapter_pause_sec: float = 2.5,
    ffmpeg_path: str = "",
) -> None:
    """Create M4B audiobook with chapter markers from MP3.

    Groups consecutive chunks belonging to the same chapter into one
    chapter marker, accounting for silence between chapters.

    Args:
        input_mp3: Input MP3 file (the assembled audiobook).
        output_m4b: Output M4B file path.
        chapter_titles: Chapter title for each chunk (same length as chunk_files).
        chapter_files: Audio chunk files in order.
        chapter_pause_sec: Silence duration inserted between chapters (not between chunks inside a chapter).
        ffmpeg_path: Path to ffmpeg executable.
    """
    output_m4b = str(Path(output_m4b).resolve())
    ffmpeg = _validate_ffmpeg_path(ffmpeg_path)

    # Get duration of each chunk
    durations = []
    for chunk in chapter_files or []:
        dur = get_audio_duration(chunk, ffmpeg=ffmpeg)
        durations.append(dur)

    # Generate default chapter titles if none provided
    if not chapter_titles:
        chapter_titles = _generate_default_chapter_titles(len(chapter_files or []))

    # Group consecutive chunks by chapter title
    # Each group becomes one chapter marker
    groups: list[tuple[str, float]] = []  # (title, total_duration_with_pauses)
    prev_title = None
    current_group_dur = 0.0
    current_group_title = ""

    for i, (title, dur) in enumerate(zip(chapter_titles or [], durations)):
        if i == 0:
            current_group_title = _sanitize_chapter_title(title)
            current_group_dur = dur
            prev_title = title
            continue

        if title == prev_title:
            # Same chapter — add chunk duration, no pause
            current_group_dur += dur
        else:
            # Chapter boundary: add silence to the END of previous chapter,
            # so its START marker aligns with actual speech (P0-7/b).
            current_group_dur += chapter_pause_sec
            groups.append((current_group_title, current_group_dur))
            current_group_title = _sanitize_chapter_title(title)
            current_group_dur = dur  # no pause before new chapter
        prev_title = title

    # Save last group
    if current_group_dur > 0:
        groups.append((current_group_title, current_group_dur))

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        meta_path = f.name
        f.write(";FFMETADATA1\n")
        if groups:
            current_time = 0.0
            for title, total_dur in groups:
                start_time = int(current_time * 1000)
                end_time = int((current_time + total_dur) * 1000)
                f.write("[CHAPTER]\n")
                f.write("TIMEBASE=1/1000\n")
                f.write(f"START={start_time}\n")
                f.write(f"END={end_time}\n")
                f.write(f"title={title}\n\n")
                current_time += total_dur
        f.close()

    cmd = [ffmpeg, "-y", "-i", input_mp3, "-i", meta_path,
           "-map_metadata", "1", "-c:a", "aac", "-b:a", "192k", output_m4b]
    subprocess.run(cmd, check=True, capture_output=True)
    Path(meta_path).unlink()


def get_audio_duration(file_path: str, ffmpeg: str = "") -> float:
    """Get audio duration in seconds using ffprobe."""
    ffmpeg = _validate_ffmpeg_path(ffmpeg)
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
    cmd = [ffprobe, "-v", "error",
           "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", file_path]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def split_audiobook_by_chapters(
    input_audio: str,
    chapter_times: list[float],
    output_dir: str,
    prefix: str = "chapter",
    ffmpeg_path: str = "",
) -> list[str]:
    """Split a single audiobook file into chapter files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_dur = get_audio_duration(input_audio)
    times = chapter_times + [total_dur]

    output_files = []
    for i, (start, end) in enumerate(zip(times[:-1], times[1:])):
        out_path = output_dir / f"{prefix}_{i+1:03d}.mp3"
        cmd = [_validate_ffmpeg_path(ffmpeg_path), "-y", "-i", input_audio,
               "-ss", str(start), "-to", str(end),
               "-c:a", "libmp3lame", "-b:a", "192k", str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True)
        output_files.append(str(out_path))
    return output_files


def add_metadata_to_mp3(
    mp3_path: str,
    title: str,
    author: str,
    cover_image: Optional[str] = None,
    year: Optional[int] = None,
    genre: str = "Audiobook",
) -> None:
    """Add ID3 metadata to MP3 file."""
    cmd = [_FFMPEG, "-y", "-i", mp3_path,
           "-metadata", f"title={title}",
           "-metadata", f"artist={author}",
           "-metadata", f"album={title}",
           "-metadata", f"genre={genre}"]
    if year:
        cmd.extend(["-metadata", f"date={year}"])
    if cover_image:
        cmd.extend(["-i", cover_image, "-map", "1", "-c:v", "mjpeg", "-id3v2_version", "3"])
    cmd.append(mp3_path + ".tmp")
    subprocess.run(cmd, check=True, capture_output=True)
    import shutil
    shutil.move(mp3_path + ".tmp", mp3_path)


def create_playlist_m3u(
    chapter_files: list[str],
    output_m3u: str,
    title: str = "Audiobook",
) -> None:
    """Create M3U playlist for chapter navigation."""
    with open(output_m3u, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f"#PLAYLIST:{title}\n\n")
        for i, chapter in enumerate(chapter_files):
            f.write(f"#EXTINF:-1,Chapter {i+1}\n")
            f.write(f"{Path(chapter).name}\n")