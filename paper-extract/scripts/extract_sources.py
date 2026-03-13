from __future__ import annotations

import argparse
import gzip
import json
import shlex
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
import re
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import OrderedDict
from dataclasses import dataclass

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_TEX_URL = "https://arxiv.org/e-print/{arxiv_id}"
DEFAULT_MINERU_BIN = Path("/Users/yuzy/.venv/bin/mineru")
DEFAULT_OPENREVIEW_PYTHON = Path("/Users/yuzy/.venv/bin/python3")
TITLE_UNAVAILABLE = "title-unavailable"
ARXIV_ID_PATTERN = re.compile(
    r"(?:(?:https?://)?arxiv\.org/(?:abs|pdf)/|arXiv:)?"
    r"(?P<id>\d{4}\.\d{4,5})"
    r"(?:v\d+)?"
    r"(?:\.pdf)?",
    re.IGNORECASE,
)
OPENREVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class ExtractionError(RuntimeError):
    """Raised when a single extraction task cannot be completed."""


@dataclass(frozen=True)
class ExtractionTask:
    route: str
    raw_input: str
    normalized_input: str


@dataclass
class ExtractionResult:
    route: str
    raw_input: str
    status: str
    output_path: str | None = None
    message: str = ""
    command: str | None = None
    job_path: str | None = None
    log_path: str | None = None
    pid: int | None = None


def normalize_cli_path(value: str) -> Path:
    """Normalize a CLI path without resolving symlinks."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return Path.cwd() / path


def normalize_arxiv_id(value: str) -> str:
    """Normalize a modern arXiv ID or URL to the canonical ID without version."""
    match = ARXIV_ID_PATTERN.search(value.strip())
    if not match:
        raise ValueError(f"Unsupported arXiv input: {value}")
    return match.group("id")


def normalize_openreview_forum_id(value: str) -> str:
    """Normalize a bare OpenReview forum ID or a forum URL."""
    text = value.strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.netloc in {"openreview.net", "www.openreview.net"}:
        forum_id = urllib.parse.parse_qs(parsed.query).get("id", [None])[0]
        if forum_id and OPENREVIEW_ID_PATTERN.fullmatch(forum_id):
            return forum_id
        raise ValueError(f"Unsupported OpenReview input: {value}")
    if OPENREVIEW_ID_PATTERN.fullmatch(text):
        return text
    raise ValueError(f"Unsupported OpenReview input: {value}")


def build_execution_plan(
    arxiv_inputs: list[str] | None,
    openreview_inputs: list[str] | None,
    pdf_inputs: list[str] | None,
) -> tuple[list[ExtractionTask], list[ExtractionResult]]:
    """Deduplicate inputs and return arXiv, OpenReview, then MinerU tasks."""
    tasks: list[ExtractionTask] = []
    failures: list[ExtractionResult] = []

    seen_arxiv: set[str] = set()
    for raw_input in arxiv_inputs or []:
        try:
            normalized = normalize_arxiv_id(raw_input)
        except ValueError as exc:
            failures.append(
                ExtractionResult(
                    route="arxiv",
                    raw_input=raw_input,
                    status="fail",
                    message=str(exc),
                )
            )
            continue
        if normalized in seen_arxiv:
            continue
        seen_arxiv.add(normalized)
        tasks.append(
            ExtractionTask(
                route="arxiv",
                raw_input=raw_input,
                normalized_input=normalized,
            )
        )

    seen_openreview: set[str] = set()
    for raw_input in openreview_inputs or []:
        try:
            normalized = normalize_openreview_forum_id(raw_input)
        except ValueError as exc:
            failures.append(
                ExtractionResult(
                    route="openreview",
                    raw_input=raw_input,
                    status="fail",
                    message=str(exc),
                )
            )
            continue
        if normalized in seen_openreview:
            continue
        seen_openreview.add(normalized)
        tasks.append(
            ExtractionTask(
                route="openreview",
                raw_input=raw_input,
                normalized_input=normalized,
            )
        )

    seen_pdf: set[str] = set()
    for raw_input in pdf_inputs or []:
        normalized = str(Path(raw_input).expanduser().resolve(strict=False))
        if normalized in seen_pdf:
            continue
        seen_pdf.add(normalized)
        tasks.append(
            ExtractionTask(
                route="mineru",
                raw_input=raw_input,
                normalized_input=normalized,
            )
        )

    return tasks, failures


def fetch_arxiv_title(arxiv_id: str) -> str | None:
    """Fetch the canonical arXiv title for a given ID."""
    params = urllib.parse.urlencode({"id_list": arxiv_id})
    request = urllib.request.Request(
        f"{ARXIV_API}?{params}",
        headers={"User-Agent": "paper-extract/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            xml_data = response.read().decode("utf-8")
    except Exception:
        return None

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return None

    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", namespace)
    if entry is None:
        return None

    title_element = entry.find("atom:title", namespace)
    if title_element is None or not title_element.text:
        return None

    return " ".join(title_element.text.split())


def download_arxiv_source(arxiv_id: str, output_root: Path) -> tuple[Path, bool]:
    """Download and extract a source package into output_root/arxiv_id."""
    destination = output_root / arxiv_id
    if destination.exists():
        return destination, True

    output_root.mkdir(parents=True, exist_ok=True)
    tmp_path = output_root / f"{arxiv_id}.download"
    inner_tmp_path = output_root / f"{arxiv_id}.inner"

    try:
        request = urllib.request.Request(
            ARXIV_TEX_URL.format(arxiv_id=arxiv_id),
            headers={"User-Agent": "paper-extract/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
        tmp_path.write_bytes(data)

        destination.mkdir(parents=True, exist_ok=True)
        if zipfile.is_zipfile(tmp_path):
            with zipfile.ZipFile(tmp_path, "r") as archive:
                archive.extractall(destination)
        elif tarfile.is_tarfile(tmp_path):
            with tarfile.open(tmp_path, "r:*") as archive:
                archive.extractall(destination)
        else:
            try:
                with gzip.open(tmp_path, "rb") as gzip_file:
                    content = gzip_file.read()
            except gzip.BadGzipFile:
                content = tmp_path.read_bytes()

            inner_tmp_path.write_bytes(content)
            if tarfile.is_tarfile(inner_tmp_path):
                with tarfile.open(inner_tmp_path, "r:*") as archive:
                    archive.extractall(destination)
            else:
                (destination / "main.tex").write_bytes(content)
    except Exception as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ExtractionError(f"Failed to download or extract arXiv source: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
        inner_tmp_path.unlink(missing_ok=True)

    return destination, False


def load_paper_registry(registry_path: Path) -> OrderedDict[str, str]:
    """Load a paper registry while preserving insertion order."""
    registry: OrderedDict[str, str] = OrderedDict()
    if not registry_path.exists():
        return registry

    for line in registry_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        arxiv_id, separator, title = line.partition(":")
        if not separator:
            continue
        registry[arxiv_id.strip()] = title.strip()
    return registry


def update_paper_registry(registry_path: Path, paper_id: str, title: str) -> str:
    """Create or update paper-id.txt without downgrading good titles."""
    registry = load_paper_registry(registry_path)
    if title == TITLE_UNAVAILABLE and paper_id in registry and registry[paper_id] != TITLE_UNAVAILABLE:
        resolved_title = registry[paper_id]
    else:
        resolved_title = title
        registry[paper_id] = resolved_title

    if paper_id not in registry:
        registry[paper_id] = resolved_title

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(f"{key}: {value}" for key, value in registry.items())
    if content:
        content += "\n"
    registry_path.write_text(content, encoding="utf-8")
    return resolved_title


def allocate_incrementing_dir(base_dir: Path) -> Path:
    """Return base_dir or a suffixed sibling like -2, -3 when it already exists."""
    candidate = base_dir
    suffix = 2
    while candidate.exists():
        candidate = base_dir.with_name(f"{base_dir.name}-{suffix}")
        suffix += 1
    return candidate


def allocate_mineru_output_dir(mineru_root: Path, pdf_path: Path) -> Path:
    """Return a non-conflicting MinerU output directory based on the PDF stem."""
    base_name = pdf_path.stem or "paper"
    return allocate_incrementing_dir(mineru_root / base_name)


def build_mineru_args(mineru_bin: Path, pdf_path: Path, output_dir: Path) -> list[str]:
    """Build the MinerU argv after validating inputs."""
    if not mineru_bin.exists():
        raise ExtractionError(f"MinerU binary not found: {mineru_bin}")
    if not pdf_path.exists():
        raise ExtractionError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ExtractionError(f"Input is not a PDF: {pdf_path}")

    return [
        str(mineru_bin),
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-m",
        "auto",
        "-b",
        "hybrid-auto-engine",
    ]


def build_mineru_command(mineru_bin: Path, pdf_path: Path, output_dir: Path) -> str:
    """Build a shell-safe MinerU command string."""
    return " ".join(shlex.quote(part) for part in build_mineru_args(mineru_bin, pdf_path, output_dir))


def build_job_id(prefix: str = "mineru") -> str:
    """Build a unique job ID for a background MinerU task."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


def run_mineru(mineru_bin: Path, pdf_path: Path, output_dir: Path) -> str:
    """Run MinerU for a PDF and return the executed command string."""
    command_args = build_mineru_args(mineru_bin, pdf_path, output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        completed = subprocess.run(
            command_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise ExtractionError(f"Failed to launch MinerU: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "MinerU exited with a non-zero status."
        raise ExtractionError(f"MinerU failed for {pdf_path}: {detail}")

    return " ".join(shlex.quote(part) for part in command_args)


def start_mineru_background(
    mineru_bin: Path,
    pdf_path: Path,
    output_dir: Path,
    jobs_root: Path,
) -> dict[str, object]:
    """Start MinerU in the background and persist job metadata."""
    command_args = build_mineru_args(mineru_bin, pdf_path, output_dir)
    command = " ".join(shlex.quote(part) for part in command_args)
    jobs_root.mkdir(parents=True, exist_ok=True)
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    job_id = build_job_id()
    job_path = jobs_root / f"{job_id}.json"
    log_path = jobs_root / f"{job_id}.log"

    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command_args,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        raise ExtractionError(f"Failed to launch MinerU in background: {exc}") from exc

    metadata = {
        "job_id": job_id,
        "pid": process.pid,
        "status": "running",
        "route": "mineru",
        "input_pdf": str(pdf_path),
        "output_dir": str(output_dir),
        "log_path": str(log_path),
        "command": command,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    job_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metadata["job_path"] = str(job_path)
    return metadata


def dispatch_mineru(
    mineru_mode: str,
    mineru_bin: Path,
    pdf_path: Path,
    output_dir: Path,
    jobs_root: Path,
) -> dict[str, object]:
    """Dispatch a PDF to manual, background, or inline MinerU execution."""
    command = build_mineru_command(mineru_bin, pdf_path, output_dir)
    if mineru_mode == "manual":
        return {
            "status": "manual",
            "message": "Run this command in your terminal",
            "command": command,
            "job_path": None,
            "log_path": None,
            "pid": None,
        }
    if mineru_mode == "background":
        job = start_mineru_background(mineru_bin, pdf_path, output_dir, jobs_root)
        return {
            "status": "background",
            "message": "MinerU started in background",
            "command": str(job["command"]),
            "job_path": str(job["job_path"]),
            "log_path": str(job["log_path"]),
            "pid": int(job["pid"]),
        }
    if mineru_mode == "inline":
        command = run_mineru(mineru_bin, pdf_path, output_dir)
        return {
            "status": "ok",
            "message": "MinerU output created",
            "command": command,
            "job_path": None,
            "log_path": None,
            "pid": None,
        }
    raise ExtractionError(f"Unsupported MinerU mode: {mineru_mode}")


def validate_python_import(python_path: Path, module_name: str) -> None:
    """Validate that a specific Python interpreter can import a module."""
    if not python_path.exists():
        raise ExtractionError(f"Python interpreter not found: {python_path}")

    try:
        completed = subprocess.run(
            [str(python_path), "-c", f"import {module_name}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ExtractionError(f"Failed to launch Python interpreter: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"cannot import {module_name}"
        raise ExtractionError(f"{python_path} cannot import {module_name}: {detail}")


def run_openreview_download(
    openreview_python: Path,
    helper_script: Path,
    forum_id: str,
    output_dir: Path,
) -> dict[str, object]:
    """Run the OpenReview helper and parse its JSON result."""
    completed = subprocess.run(
        [
            str(openreview_python),
            str(helper_script),
            "--forum-id",
            forum_id,
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload: dict[str, object] | None = None
    try:
        payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    except json.JSONDecodeError as exc:
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "OpenReview helper failed."
            raise ExtractionError(detail) from exc
        raise ExtractionError(f"OpenReview helper returned invalid JSON: {exc}") from exc

    if completed.returncode != 0:
        detail = (
            str(payload.get("message"))
            if isinstance(payload, dict) and payload.get("message")
            else completed.stderr.strip() or completed.stdout.strip() or "OpenReview helper failed."
        )
        raise ExtractionError(detail)

    if not isinstance(payload, dict):
        raise ExtractionError("OpenReview helper returned no JSON payload.")

    if payload.get("status") not in {"ok", "skip"}:
        raise ExtractionError(str(payload.get("message", "OpenReview download failed.")))
    return payload


def format_result(result: ExtractionResult) -> str:
    """Format a result line for terminal output."""
    parts = [f"[{result.status.upper()}]", result.route, result.raw_input]
    if result.output_path:
        parts.append(f"-> {result.output_path}")
    if result.message:
        parts.append(f"({result.message})")
    line = " ".join(parts)
    details: list[str] = []
    if result.command:
        details.append(f"command: {result.command}")
    if result.pid is not None:
        details.append(f"pid: {result.pid}")
    if result.job_path:
        details.append(f"job: {result.job_path}")
    if result.log_path:
        details.append(f"log: {result.log_path}")
    if details:
        return f"{line}\n" + "\n".join(details)
    return line


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract paper source materials into ./papers via arXiv, OpenReview, and MinerU."
    )
    parser.add_argument(
        "--arxiv",
        action="append",
        default=[],
        help="Explicit arXiv ID or arXiv URL. Repeat for multiple papers.",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        default=[],
        help="Absolute path to a local PDF file. Repeat for multiple files.",
    )
    parser.add_argument(
        "--openreview",
        action="append",
        default=[],
        help="Explicit OpenReview forum ID or forum URL. Repeat for multiple papers.",
    )
    parser.add_argument(
        "--papers-root",
        default="./papers",
        help="Root directory for extraction outputs (default: ./papers).",
    )
    parser.add_argument(
        "--mineru-bin",
        default=str(DEFAULT_MINERU_BIN),
        help=f"MinerU binary path used for PDF extraction (default: {DEFAULT_MINERU_BIN}).",
    )
    parser.add_argument(
        "--mineru-mode",
        choices=["manual", "background", "inline"],
        default="background",
        help=(
            "How to handle MinerU for non-arXiv PDFs: manual prints a command, "
            "background starts MinerU and returns immediately, inline waits for completion "
            "(default: background)."
        ),
    )
    parser.add_argument(
        "--openreview-python",
        default=str(DEFAULT_OPENREVIEW_PYTHON),
        help=(
            "Python interpreter used to call OpenReview API helper "
            f"(default: {DEFAULT_OPENREVIEW_PYTHON})."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.arxiv and not args.openreview and not args.pdf:
        raise SystemExit("Provide at least one --arxiv, --openreview, or --pdf input.")

    papers_root = Path(args.papers_root).expanduser().resolve()
    arxiv_root = papers_root / "arxiv"
    openreview_root = papers_root / "openreview"
    mineru_root = papers_root / "mineru"
    jobs_root = papers_root / "jobs"
    registry_path = arxiv_root / "paper-id.txt"
    openreview_registry_path = openreview_root / "paper-id.txt"
    mineru_bin = normalize_cli_path(args.mineru_bin)
    openreview_python = normalize_cli_path(args.openreview_python)
    openreview_helper = Path(__file__).resolve().parent / "fetch_openreview_submission.py"

    openreview_runtime_error: str | None = None
    if args.openreview:
        try:
            validate_python_import(openreview_python, "openreview")
        except ExtractionError as exc:
            openreview_runtime_error = str(exc)

    tasks, results = build_execution_plan(args.arxiv, args.openreview, args.pdf)

    for task in tasks:
        if task.route == "arxiv":
            fetched_title = fetch_arxiv_title(task.normalized_input)
            desired_title = fetched_title or TITLE_UNAVAILABLE
            try:
                destination, existed = download_arxiv_source(task.normalized_input, arxiv_root)
                stored_title = update_paper_registry(
                    registry_path,
                    task.normalized_input,
                    desired_title,
                )
            except ExtractionError as exc:
                results.append(
                    ExtractionResult(
                        route="arxiv",
                        raw_input=task.raw_input,
                        status="fail",
                        message=str(exc),
                    )
                )
                continue

            message_parts = ["existing source reused" if existed else "source downloaded"]
            status = "skip" if existed else "ok"
            if fetched_title is None and stored_title == TITLE_UNAVAILABLE:
                status = "warn"
                message_parts.append("title lookup failed")
            results.append(
                ExtractionResult(
                    route="arxiv",
                    raw_input=task.raw_input,
                    status=status,
                    output_path=str(destination),
                    message=", ".join(message_parts),
                )
            )
            continue

        if task.route == "openreview":
            if openreview_runtime_error is not None:
                results.append(
                    ExtractionResult(
                        route="openreview",
                        raw_input=task.raw_input,
                        status="fail",
                        message=openreview_runtime_error,
                    )
                )
                continue

            output_dir = openreview_root / task.normalized_input
            mineru_output_dir = allocate_incrementing_dir(output_dir / "mineru")
            try:
                payload = run_openreview_download(
                    openreview_python,
                    openreview_helper,
                    task.normalized_input,
                    output_dir,
                )
                stored_title = update_paper_registry(
                    openreview_registry_path,
                    task.normalized_input,
                    str(payload.get("title") or TITLE_UNAVAILABLE),
                )
                pdf_path = Path(str(payload["pdf_path"]))
                mineru_result = dispatch_mineru(
                    args.mineru_mode,
                    mineru_bin,
                    pdf_path,
                    mineru_output_dir,
                    jobs_root,
                )
            except ExtractionError as exc:
                results.append(
                    ExtractionResult(
                        route="openreview",
                        raw_input=task.raw_input,
                        status="fail",
                        message=str(exc),
                    )
                )
                continue

            results.append(
                ExtractionResult(
                    route="openreview",
                    raw_input=task.raw_input,
                    status=str(mineru_result["status"]),
                    output_path=str(payload["output_dir"]),
                    message=(
                        f"{payload['message']}; {mineru_result['message']}"
                        if stored_title != TITLE_UNAVAILABLE
                        else f"{payload['message']}; registry stored title-unavailable; {mineru_result['message']}"
                    ),
                    command=str(mineru_result["command"]),
                    job_path=(
                        str(mineru_result["job_path"])
                        if mineru_result["job_path"] is not None
                        else None
                    ),
                    log_path=(
                        str(mineru_result["log_path"])
                        if mineru_result["log_path"] is not None
                        else None
                    ),
                    pid=(
                        int(mineru_result["pid"])
                        if mineru_result["pid"] is not None
                        else None
                    ),
                )
            )
            continue

        pdf_path = Path(task.normalized_input)
        output_dir = allocate_mineru_output_dir(mineru_root, pdf_path)
        try:
            mineru_result = dispatch_mineru(
                args.mineru_mode,
                mineru_bin,
                pdf_path,
                output_dir,
                jobs_root,
            )
        except ExtractionError as exc:
            results.append(
                ExtractionResult(
                    route="mineru",
                    raw_input=task.raw_input,
                    status="fail",
                    message=str(exc),
                )
            )
            continue

        results.append(
            ExtractionResult(
                route="mineru",
                raw_input=task.raw_input,
                status=str(mineru_result["status"]),
                output_path=str(output_dir),
                message=str(mineru_result["message"]),
                command=str(mineru_result["command"]),
                job_path=(
                    str(mineru_result["job_path"])
                    if mineru_result["job_path"] is not None
                    else None
                ),
                log_path=(
                    str(mineru_result["log_path"])
                    if mineru_result["log_path"] is not None
                    else None
                ),
                pid=(
                    int(mineru_result["pid"])
                    if mineru_result["pid"] is not None
                    else None
                ),
            )
        )

    for result in results:
        print(format_result(result))

    return 1 if any(result.status == "fail" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
