from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_V2_BASEURL = "https://api2.openreview.net"
DEFAULT_V1_BASEURL = "https://api.openreview.net"
FORUM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class OpenReviewDownloadError(RuntimeError):
    """Raised when a public OpenReview submission cannot be fetched."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a public OpenReview submission PDF and metadata."
    )
    parser.add_argument("--forum-id", required=True, help="OpenReview forum ID or forum URL.")
    parser.add_argument("--output-dir", required=True, help="Destination directory.")
    parser.add_argument("--baseurl-v2", default=DEFAULT_V2_BASEURL)
    parser.add_argument("--baseurl-v1", default=DEFAULT_V1_BASEURL)
    return parser.parse_args()


def emit(data: dict[str, Any], exit_code: int) -> int:
    print(json.dumps(data, ensure_ascii=False))
    return exit_code


def normalize_openreview_forum_id(value: str) -> str:
    text = value.strip()
    parsed = urlparse(text)
    if parsed.netloc in {"openreview.net", "www.openreview.net"}:
        forum_id = parse_qs(parsed.query).get("id", [None])[0]
        if forum_id and FORUM_ID_PATTERN.fullmatch(forum_id):
            return forum_id
        raise ValueError(f"Unsupported OpenReview input: {value}")
    if FORUM_ID_PATTERN.fullmatch(text):
        return text
    raise ValueError(f"Unsupported OpenReview input: {value}")


def get_attr(note: Any, name: str, default: Any = None) -> Any:
    if hasattr(note, name):
        return getattr(note, name)
    if isinstance(note, dict):
        return note.get(name, default)
    return default


def normalize_content(content: Any) -> dict[str, Any]:
    if not isinstance(content, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in content.items():
        if isinstance(value, dict) and "value" in value:
            normalized[key] = value["value"]
        else:
            normalized[key] = value
    return normalized


def build_clients(openreview_mod: Any, args: argparse.Namespace) -> tuple[Any, Any]:
    client_v2 = openreview_mod.api.OpenReviewClient(baseurl=args.baseurl_v2)
    client_v1 = openreview_mod.Client(baseurl=args.baseurl_v1)
    return client_v2, client_v1


def fetch_root_note(client_v2: Any, client_v1: Any, forum_id: str) -> tuple[Any, str]:
    errors: list[str] = []
    try:
        return client_v2.get_note(forum_id), "v2"
    except Exception as exc:  # pragma: no cover - depends on OpenReview state
        errors.append(f"v2: {exc}")
    try:
        return client_v1.get_note(forum_id), "v1"
    except Exception as exc:
        errors.append(f"v1: {exc}")
    raise OpenReviewDownloadError(
        "OpenReview forum not accessible: " + " | ".join(errors)
    )


def download_pdf_attachment(note_id: str, client_v2: Any, client_v1: Any) -> tuple[bytes, str]:
    errors: list[str] = []
    for source, client, kwargs in (
        ("v2", client_v2, {"field_name": "pdf", "id": note_id}),
        ("v1", client_v1, {"id": note_id, "field_name": "pdf"}),
    ):
        try:
            payload = client.get_attachment(**kwargs)
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            continue
        if payload:
            return payload, source
    raise OpenReviewDownloadError(
        "Failed to download OpenReview PDF: " + " | ".join(errors)
    )


def fetch_submission_bundle(
    client_v2: Any,
    client_v1: Any,
    forum_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    note, note_source = fetch_root_note(client_v2, client_v1, forum_id)
    note_id = str(get_attr(note, "id", forum_id))
    content = normalize_content(get_attr(note, "content"))
    if "pdf" not in content:
        raise OpenReviewDownloadError("OpenReview note has no public pdf field.")

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / "submission.pdf"
    metadata_path = output_dir / "metadata.json"

    pdf_reused = pdf_path.exists()
    pdf_source = note_source
    if not pdf_reused:
        payload, pdf_source = download_pdf_attachment(note_id, client_v2, client_v1)
        pdf_path.write_bytes(payload)

    metadata = {
        "forum_id": forum_id,
        "forum_url": f"https://openreview.net/forum?id={forum_id}",
        "note_id": note_id,
        "title": content.get("title"),
        "authors": content.get("authors"),
        "venue": content.get("venue"),
        "pdf": content.get("pdf"),
        "abstract": content.get("abstract"),
        "keywords": content.get("keywords"),
        "note_source": note_source,
        "pdf_source": pdf_source,
        "pdf_reused": pdf_reused,
        "output_dir": str(output_dir),
        "pdf_path": str(pdf_path),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "status": "skip" if pdf_reused else "ok",
        "message": "existing submission reused" if pdf_reused else "submission downloaded",
        "forum_id": forum_id,
        "forum_url": metadata["forum_url"],
        "note_id": note_id,
        "title": content.get("title"),
        "output_dir": str(output_dir),
        "pdf_path": str(pdf_path),
        "metadata_path": str(metadata_path),
        "pdf_reused": pdf_reused,
    }


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()

    try:
        forum_id = normalize_openreview_forum_id(args.forum_id)
    except ValueError as exc:
        return emit(
            {
                "status": "fail",
                "message": str(exc),
                "forum_id": None,
                "output_dir": str(output_dir),
            },
            1,
        )

    try:
        import openreview  # type: ignore
    except Exception as exc:
        return emit(
            {
                "status": "env_missing",
                "message": f"Current interpreter cannot import openreview: {exc}",
                "forum_id": forum_id,
                "output_dir": str(output_dir),
            },
            1,
        )

    try:
        client_v2, client_v1 = build_clients(openreview, args)
        result = fetch_submission_bundle(client_v2, client_v1, forum_id, output_dir)
    except OpenReviewDownloadError as exc:
        return emit(
            {
                "status": "fail",
                "message": str(exc),
                "forum_id": forum_id,
                "output_dir": str(output_dir),
            },
            1,
        )
    except Exception as exc:  # pragma: no cover - unexpected runtime failure
        return emit(
            {
                "status": "fail",
                "message": f"Unexpected OpenReview error: {exc}",
                "forum_id": forum_id,
                "output_dir": str(output_dir),
            },
            1,
        )

    return emit(result, 0)


if __name__ == "__main__":
    raise SystemExit(main())
