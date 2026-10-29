"""Batch-compress common images, PDFs and videos without changing originals."""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image, ImageOps

SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
SUPPORTED_VIDEOS = {".mp4", ".mov", ".webm", ".mkv"}
SUPPORTED_EXTENSIONS = SUPPORTED_IMAGES | SUPPORTED_VIDEOS | {".pdf"}
DEFAULT_INPUT = Path("input")
DEFAULT_OUTPUT = Path("output")
DEFAULT_QUALITY = 75
MAX_PIXELS = 100_000_000
LOG_FILE = "compressor.log"


@dataclass
class FileResult:
    source: str
    output: str
    original_bytes: int
    compressed_bytes: int
    status: str
    error: str = ""

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.compressed_bytes

    @property
    def saved_percent(self) -> float:
        if self.original_bytes <= 0 or self.compressed_bytes < 0:
            return 0.0
        return 100 * self.saved_bytes / self.original_bytes


def configure_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(output_dir / LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def make_output_path(source: Path, input_root: Path, output_root: Path, extension: str) -> Path:
    relative = source.relative_to(input_root)
    return output_root / relative.parent / f"{source.stem}_compressed.{extension}"


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def compress_image(source: Path, destination: Path, quality: int, output_format: str) -> None:
    with Image.open(source) as original:
        original.load()
        if original.width * original.height > MAX_PIXELS:
            raise ValueError(f"Image exceeds {MAX_PIXELS:,} pixel safety limit")

        image = ImageOps.exif_transpose(original)
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        icc_profile = original.info.get("icc_profile")
        if output_format == "webp":
            image = image.convert("RGBA" if has_alpha else "RGB")
            options = {"format": "WEBP", "quality": quality, "method": 4}
        elif output_format == "jpg":
            if has_alpha:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            options = {"format": "JPEG", "quality": quality, "optimize": True, "progressive": True}
        else:
            image = image.convert("RGBA" if has_alpha else "RGB")
            options = {"format": "PNG", "optimize": True, "compress_level": 9}
        if icc_profile and output_format != "png":
            options["icc_profile"] = icc_profile
        image.save(destination, **options)


def compress_pdf(source: Path, destination: Path) -> None:
    with fitz.open(source) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDF; password required")
        if document.is_repaired:
            logging.warning("PDF required repair during opening: %s", source)
        document.save(
            str(destination),
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
            use_objstms=1,
        )


def compress_video(source: Path, destination: Path, quality: int, output_format: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("FFmpeg is required for video files. Install FFmpeg and add it to PATH.")

    crf = max(10, min(45, round(51 - quality * 0.4)))
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
               "-map", "0:v:0", "-map", "0:a?"]
    if output_format == "mp4":
        command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart"])
    else:
        command.extend(["-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "4",
                        "-crf", str(crf), "-b:v", "0", "-c:a", "libopus", "-b:a", "96k"])
    command.append(str(destination))
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        detail = completed.stderr.strip().splitlines()
        message = detail[-1] if detail else "unknown FFmpeg error"
        raise RuntimeError(f"Video conversion failed: {message[:400]}")


def scan_files(input_root: Path, output_root: Path) -> list[Path]:
    files = []
    for path in input_root.rglob("*"):
        if not path.is_file() or is_inside(path, output_root):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if path.stem.lower().endswith("_compressed"):
            continue
        files.append(path)
    return sorted(files, key=lambda p: str(p).lower())


def process_file(
    source: Path,
    input_root: Path,
    output_root: Path,
    quality: int,
    image_format: str,
    video_format: str,
) -> FileResult:
    original_size = source.stat().st_size
    extension = source.suffix.lower()
    if extension in SUPPORTED_IMAGES:
        output_extension = image_format
    elif extension in SUPPORTED_VIDEOS:
        output_extension = video_format
    else:
        output_extension = "pdf"
    destination = make_output_path(source, input_root, output_root, output_extension)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = ensure_unique_path(destination)

    try:
        if extension in SUPPORTED_IMAGES:
            compress_image(source, destination, quality, image_format)
        elif extension in SUPPORTED_VIDEOS:
            compress_video(source, destination, quality, video_format)
        else:
            compress_pdf(source, destination)
        return FileResult(str(source), str(destination), original_size, destination.stat().st_size, "OK")
    except Exception as exc:
        try:
            if destination.exists():
                destination.unlink()
        except OSError:
            logging.exception("Could not remove partial output: %s", destination)
        logging.exception("Failed to process %s", source)
        return FileResult(str(source), "-", original_size, 0, "FAILED", f"{type(exc).__name__}: {exc}")


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def print_report(results: list[FileResult]) -> None:
    headers = ["File", "Original", "Output", "Saved", "Saved %", "Status"]
    rows = []
    for result in results:
        name = Path(result.source).name
        if len(name) > 28:
            name = name[:25] + "..."
        if result.status == "OK":
            rows.append([name, format_size(result.original_bytes), format_size(result.compressed_bytes),
                         format_size(result.saved_bytes), f"{result.saved_percent:.1f}%", "OK"])
        else:
            rows.append([name, format_size(result.original_bytes), "—", "—", "—", "FAILED"])

    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
              for i in range(len(headers))]

    def line(char: str = "-") -> str:
        return "+" + "+".join(char * (width + 2) for width in widths) + "+"

    def print_row(values: list[str]) -> None:
        print("| " + " | ".join(value.ljust(widths[i]) for i, value in enumerate(values)) + " |")

    print("\nCOMPRESSION REPORT")
    print(line())
    print_row(headers)
    print(line("="))
    for row in rows:
        print_row(row)
    print(line())

    successful = [r for r in results if r.status == "OK"]
    failed = [r for r in results if r.status != "OK"]
    original_total = sum(r.original_bytes for r in successful)
    output_total = sum(r.compressed_bytes for r in successful)
    saved = original_total - output_total
    percent = 100 * saved / original_total if original_total else 0.0

    print(f"Files discovered : {len(results)}")
    print(f"Successful       : {len(successful)}")
    print(f"Failed           : {len(failed)}")
    print(f"Original total   : {format_size(original_total)}")
    print(f"Compressed total : {format_size(output_total)}")
    print(f"Space saved      : {format_size(saved)}")
    print(f"Overall saved    : {percent:.2f}%")
    if failed:
        print("\nFailed files:")
        for result in failed:
            print(f"  - {result.source}: {result.error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-compress images, PDFs and videos without changing originals.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input directory (default: ./input)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory (default: ./output)")
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY,
                        help="Image/video quality from 10 to 95 (default: 75)")
    parser.add_argument("--image-format", choices=("webp", "jpg", "png"), default="webp",
                        help="Image output format (default: webp; GIFs are reduced to their first frame)")
    parser.add_argument("--video-format", choices=("mp4", "webm"), default="mp4",
                        help="Video output format (default: mp4; requires FFmpeg on PATH)")
    args = parser.parse_args()

    if not 10 <= args.quality <= 95:
        parser.error("--quality must be between 10 and 95")

    input_root = args.input.expanduser().resolve()
    output_root = args.output.expanduser().resolve()
    if input_root == output_root:
        parser.error("Input and output directories must be different")
    if not input_root.exists():
        input_root.mkdir(parents=True, exist_ok=True)
        print(f"Created input folder: {input_root}")
        print("Add supported images, PDFs or videos there, then run the script again.")
        return 0
    if not input_root.is_dir():
        parser.error(f"Input path is not a directory: {input_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    configure_logging(output_root)
    print(f"Input folder : {input_root}")
    print(f"Output folder: {output_root}")
    print(f"Image/video quality: {args.quality}%")
    print(f"Image output   : {args.image_format}")
    print(f"Video output   : {args.video_format}")

    files = scan_files(input_root, output_root)
    if not files:
        print("No supported images, PDFs or videos found.")
        return 0

    print(f"Found {len(files)} supported file(s).\n")
    results = []
    for index, source in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] Processing: {source.name}")
        result = process_file(source, input_root, output_root, args.quality, args.image_format, args.video_format)
        results.append(result)
        if result.status == "OK":
            print(f"    {format_size(result.original_bytes)} -> {format_size(result.compressed_bytes)} ({result.saved_percent:.1f}% saved)")
        else:
            print(f"    FAILED: {result.error}")

    print_report(results)
    print(f"\nDetailed log: {output_root / LOG_FILE}")
    return 1 if any(r.status != "OK" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
