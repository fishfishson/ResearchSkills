#!/usr/bin/env python3
"""Best-effort OpenReview public review fetcher for paper-analyzer.

This script standardizes OpenReview discovery and public discussion fetching.
It is intentionally tolerant:

- if `openreview` is unavailable in the current interpreter, it returns
  `status=env_missing`
- if no reliable public forum can be found, it returns `status=not_found`
- if a public forum is found, it returns `status=found` plus normalized nodes

Typical usage:
  python3 fetch_openreview_public.py --input-path /path/to/paper_dir
  /path/to/python3 fetch_openreview_public.py --input-path /path/to/main.tex
  python3 fetch_openreview_public.py --input-path /path/to/paper_dir --python-path /path/to/python3
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen


DEFAULT_V2_BASEURL = "https://api2.openreview.net"
DEFAULT_V1_BASEURL = "https://api.openreview.net"
TEXT_SUFFIXES = {".md", ".tex"}
FORUM_URL_RE = re.compile(r"https?://openreview\.net/forum\?id=([A-Za-z0-9_-]+)")
FORUM_ID_RE = re.compile(r"Forum ID:\s*`?([A-Za-z0-9_-]+)`?", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Best-effort fetch of public OpenReview materials for a local paper input."
    )
    parser.add_argument("--input-path", required=True, help="Local paper directory or file.")
    parser.add_argument(
        "--python-path",
        help="Optional absolute Python path that can import openreview. "
        "If provided, this script re-executes itself with that interpreter.",
    )
    parser.add_argument(
        "--format",
        default="json",
        choices=["json", "pretty-json"],
        help="Output format.",
    )
    parser.add_argument("--baseurl-v2", default=DEFAULT_V2_BASEURL)
    parser.add_argument("--baseurl-v1", default=DEFAULT_V1_BASEURL)
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def emit(data: dict[str, Any], output_format: str) -> int:
    indent = 2 if output_format == "pretty-json" else None
    print(json.dumps(data, ensure_ascii=False, indent=indent))
    return 0


def maybe_reexec(args: argparse.Namespace) -> int | None:
    if not args.python_path or args._worker:
        return None

    python_path = str(Path(args.python_path).expanduser().resolve())
    current = str(Path(sys.executable).resolve())
    if python_path == current:
        return None

    cmd = [
        python_path,
        str(Path(__file__).resolve()),
        "--input-path",
        args.input_path,
        "--format",
        args.format,
        "--baseurl-v2",
        args.baseurl_v2,
        "--baseurl-v1",
        args.baseurl_v1,
        "--_worker",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        data = {
            "status": "env_missing",
            "input_path": str(Path(args.input_path).expanduser().resolve()),
            "paper_title": None,
            "paper_title_source": None,
            "forum_id": None,
            "forum_url": None,
            "message": f"提供的 python_path 不可执行: {python_path}",
            "normalized_notes": [],
            "discussion_markdown": "",
            "openreview_section_markdown": build_section_markdown(
                "env_missing", f"提供的 python_path 不可执行: {python_path}"
            ),
        }
        return emit(data, args.format)
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def load_openreview() -> Any | None:
    try:
        import openreview  # type: ignore
    except Exception:
        return None
    return openreview


def discover_text_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]

    files = [
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
    ]

    def sort_key(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        if name == "main.tex":
            rank = 0
        elif name.endswith("_submission.md") or name == "paper.md":
            rank = 1
        elif name.endswith(".md"):
            rank = 2
        elif name.endswith(".tex"):
            rank = 3
        else:
            rank = 4
        return (rank, str(path))

    return sorted(files, key=sort_key)


def discover_metadata_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.name == "metadata.json" else []
    return sorted(
        path
        for path in input_path.rglob("metadata.json")
        if path.is_file()
    )


def read_text(path: Path, limit: int = 250_000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:limit]


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_title(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip("#").strip()


def extract_title_from_markdown(text: str) -> str | None:
    match = re.search(r"^\s*#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    if match:
        title = clean_title(match.group(1))
        return title or None
    return None


def extract_title_from_tex(text: str) -> str | None:
    match = re.search(r"\\title\s*\{(.+?)\}", text, flags=re.DOTALL)
    if not match:
        return None
    title = re.sub(r"\\[a-zA-Z]+\s*", " ", match.group(1))
    title = re.sub(r"[{}]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title or None


def extract_title(files: list[Path]) -> tuple[str | None, Path | None]:
    for path in files:
        text = read_text(path)
        if path.suffix.lower() == ".md":
            title = extract_title_from_markdown(text)
        else:
            title = extract_title_from_tex(text)
        if title:
            return title, path
    return None, None


def extract_title_from_metadata(files: list[Path]) -> tuple[str | None, Path | None]:
    for path in files:
        payload = read_json(path)
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip(), path
    return None, None


def extract_forum_candidates(files: list[Path]) -> list[str]:
    found: list[str] = []
    for path in files:
        text = read_text(path)
        found.extend(FORUM_URL_RE.findall(text))
        found.extend(FORUM_ID_RE.findall(text))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in found:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def extract_forum_candidates_from_metadata(files: list[Path]) -> list[str]:
    found: list[str] = []
    for path in files:
        payload = read_json(path)
        forum_id = payload.get("forum_id")
        forum_url = payload.get("forum_url")
        if isinstance(forum_id, str) and forum_id.strip():
            found.append(forum_id.strip())
        if isinstance(forum_url, str) and forum_url.strip():
            found.extend(FORUM_URL_RE.findall(forum_url))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in found:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def normalize_title(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


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


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [stringify_value(item) for item in value]
        parts = [part for part in parts if part]
        return "\n".join(f"- {part}" for part in parts) if parts else ""
    if isinstance(value, dict):
        if set(value.keys()) == {"value"}:
            return stringify_value(value["value"])
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value).strip()


def get_attr(note: Any, name: str, default: Any = None) -> Any:
    if hasattr(note, name):
        return getattr(note, name)
    if isinstance(note, dict):
        return note.get(name, default)
    return default


def extract_note_title(note: Any) -> str | None:
    title = normalize_content(get_attr(note, "content")).get("title")
    if isinstance(title, str):
        return title.strip() or None
    return None


def build_clients(openreview_mod: Any, args: argparse.Namespace) -> tuple[Any, Any]:
    client_v2 = openreview_mod.api.OpenReviewClient(baseurl=args.baseurl_v2)
    client_v1 = openreview_mod.Client(baseurl=args.baseurl_v1)
    return client_v2, client_v1


def try_get_notes(client: Any, **kwargs: Any) -> list[Any]:
    for method_name in ("get_notes", "get_all_notes"):
        method = getattr(client, method_name, None)
        if not callable(method):
            continue
        try:
            notes = method(**kwargs)
        except Exception:
            continue
        if notes:
            return list(notes)
    return []


def find_forum_by_title(client_v2: Any, client_v1: Any, title: str) -> str | None:
    wanted = normalize_title(title)
    candidates: list[Any] = []

    for client in (client_v2, client_v1):
        notes = try_get_notes(client, content={"title": title})
        candidates.extend(notes)

    if not candidates:
        return None

    matched_forums: list[str] = []
    seen: set[str] = set()
    for note in candidates:
        note_title = extract_note_title(note)
        if not note_title:
            continue
        if normalize_title(note_title) != wanted:
            continue
        forum_id = get_attr(note, "forum") or get_attr(note, "id")
        if forum_id and forum_id not in seen:
            seen.add(forum_id)
            matched_forums.append(str(forum_id))

    if len(matched_forums) == 1:
        return matched_forums[0]
    return None


def note_sort_key(note: Any) -> tuple[int, str]:
    timestamp = (
        get_attr(note, "cdate")
        or get_attr(note, "tcdate")
        or get_attr(note, "pdate")
        or 0
    )
    return (int(timestamp), str(get_attr(note, "id", "")))


def note_timestamp(note: Any) -> str | None:
    timestamp = (
        get_attr(note, "pdate")
        or get_attr(note, "cdate")
        or get_attr(note, "tcdate")
    )
    if not timestamp:
        return None
    dt = datetime.fromtimestamp(int(timestamp) / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def note_invitation(note: Any) -> str:
    invitations = get_attr(note, "invitations")
    if isinstance(invitations, list) and invitations:
        return str(invitations[0])
    invitation = get_attr(note, "invitation")
    return str(invitation or "")


def note_signature(note: Any) -> str:
    signatures = get_attr(note, "signatures")
    if isinstance(signatures, list) and signatures:
        return str(signatures[0])
    return ""


def note_role_label(note: Any) -> str:
    signature = note_signature(note)
    if signature:
        return signature.split("/")[-1]
    invitation = note_invitation(note)
    if invitation:
        return invitation.split("/")[-1]
    return "Unknown"


def classify_note(note: Any) -> str | None:
    invitation = note_invitation(note).lower()
    signature = note_signature(note).lower()
    content = normalize_content(get_attr(note, "content"))
    note_id = str(get_attr(note, "id", ""))
    forum_id = str(get_attr(note, "forum", ""))
    replyto = get_attr(note, "replyto")

    if not content:
        return None
    if note_id and forum_id and note_id == forum_id and not replyto:
        return None
    if "acknowledgement" in invitation:
        return None
    if "decision" in invitation:
        return "decision"
    if "metareview" in invitation or "meta_review" in invitation:
        return "meta_review"
    if "official_review" in invitation or invitation.endswith("/review"):
        return "official_review"
    if "rebuttal" in invitation:
        return "author_rebuttal"
    if "author_final_remarks" in invitation:
        return "author_final_remarks"
    if "comment" in invitation:
        if "authors" in signature:
            return "author_comment"
        if "reviewer" in signature or "area_chair" in signature or "program_chairs" in signature:
            return "reviewer_comment"
        return "comment"
    if "reviewer" in signature:
        return "official_review"
    if "authors" in signature:
        return "author_comment"
    return None


def format_note_content(note: Any) -> str:
    content = normalize_content(get_attr(note, "content"))
    ordered_keys = [
        "title",
        "summary",
        "paper_summary",
        "review",
        "main_review",
        "strengths_and_weaknesses",
        "questions",
        "limitations",
        "comment",
        "decision",
        "metareview",
        "rating",
        "confidence",
    ]
    labels = {
        "title": "标题",
        "summary": "总结",
        "paper_summary": "论文总结",
        "review": "详细意见",
        "main_review": "主要意见",
        "strengths_and_weaknesses": "优点与不足",
        "questions": "问题",
        "limitations": "局限性",
        "comment": "回复内容",
        "decision": "Decision",
        "metareview": "Meta Review",
        "rating": "评分",
        "confidence": "置信度",
    }

    lines: list[str] = []
    used: set[str] = set()
    for key in ordered_keys:
        if key not in content:
            continue
        text = stringify_value(content[key])
        if not text:
            continue
        lines.append(f"**{labels.get(key, key)}:**")
        lines.append(text)
        used.add(key)

    for key in sorted(content):
        if key in used:
            continue
        if key in {"authors", "authorids", "keywords"}:
            continue
        text = stringify_value(content[key])
        if not text:
            continue
        lines.append(f"**{key}:**")
        lines.append(text)

    return "\n\n".join(lines) if lines else "*(无可展示文本内容)*"


def build_discussion_markdown(paper_title: str, forum_id: str, notes: list[Any], source: str) -> str:
    lines = [
        f"# 论文：{paper_title} - OpenReview 公开记录",
        f"**Forum ID:** `{forum_id}`",
        f"**原链接:** https://openreview.net/forum?id={forum_id}",
        f"**数据源:** OpenReview API {source}",
        "",
        "---",
        "",
    ]

    by_parent: dict[str | None, list[Any]] = defaultdict(list)
    note_dict: dict[str, Any] = {}
    for note in notes:
        note_id = str(get_attr(note, "id"))
        note_dict[note_id] = note
        by_parent[get_attr(note, "replyto")].append(note)

    for parent in list(by_parent):
        by_parent[parent].sort(key=note_sort_key)

    root_id = forum_id if forum_id in note_dict else None
    visited: set[str] = set()

    def add_node(note: Any, depth: int) -> None:
        note_id = str(get_attr(note, "id"))
        if note_id in visited:
            return
        visited.add(note_id)

        if depth > 0:
            prefix = "> " * depth
            role = note_role_label(note)
            timestamp = note_timestamp(note)
            header = f"### [{role}]"
            if timestamp:
                header += f" - {timestamp}"
            lines.append(f"{prefix}{header}")
            invitation = note_invitation(note)
            if invitation:
                lines.append(f"{prefix}**Invitation:** `{invitation}`")
            for line in format_note_content(note).splitlines():
                lines.append(f"{prefix}{line}" if line else prefix.rstrip())
            lines.append(f"{prefix}---")
            lines.append("")

        for child in by_parent.get(note_id, []):
            if str(get_attr(child, "id")) == note_id:
                continue
            add_node(child, depth + 1)

    if root_id:
        add_node(note_dict[root_id], 0)
    else:
        for note in sorted(notes, key=note_sort_key):
            if str(get_attr(note, "replyto")) == forum_id or get_attr(note, "replyto") is None:
                add_node(note, 1)

    remaining = [
        note for note in sorted(notes, key=note_sort_key)
        if str(get_attr(note, "id")) not in visited
    ]
    if remaining:
        lines.extend(["## 其他未挂接节点", "", "---", ""])
        for note in remaining:
            role = note_role_label(note)
            timestamp = note_timestamp(note)
            header = f"### [{role}]"
            if timestamp:
                header += f" - {timestamp}"
            lines.append(header)
            replyto = get_attr(note, "replyto")
            if replyto:
                lines.append(f"**ReplyTo:** `{replyto}`")
            invitation = note_invitation(note)
            if invitation:
                lines.append(f"**Invitation:** `{invitation}`")
            lines.append(format_note_content(note))
            lines.extend(["---", ""])

    return "\n".join(lines).rstrip() + "\n"


def build_section_markdown(status: str, message: str = "") -> str:
    if status == "env_missing":
        return "\n".join(
            [
                "## openreview",
                "",
                "OpenReview 环境未就绪，本次未抓取公开审稿。",
                "",
                f"说明：{message}" if message else "",
            ]
        ).strip() + "\n"
    if status == "not_found":
        return "\n".join(
            [
                "## openreview",
                "",
                "未检索到可靠公开 OpenReview 人类审稿/作者回复。",
                "",
                f"说明：{message}" if message else "",
            ]
        ).strip() + "\n"
    return "\n".join(
        [
            "## openreview",
            "",
            "### 1. 整体评价",
            "",
            "- 仅基于公开 OpenReview reviewer comments, author replies, decision, or meta review 撰写。",
            "",
            "### 2. 论文的具体优点和缺点",
            "",
            "- 仅基于公开 OpenReview 内容撰写。",
            "",
            "### 3. 主要问题、作者回答与 rebuttal 是否解决",
            "",
            "| 问题 | 来源 | 作者回答摘要 | rebuttal 是否解决 | 说明 |",
            "| --- | --- | --- | --- | --- |",
        ]
    ) + "\n"


def fetch_public_discussion(
    client_v2: Any, client_v1: Any, forum_id: str
) -> tuple[list[Any], str]:
    notes = try_get_notes(client_v2, forum=forum_id)
    source = "v2"

    try:
        root_note = client_v2.get_note(forum_id)
    except Exception:
        root_note = None

    if not notes and root_note is None:
        notes = try_get_notes(client_v1, forum=forum_id)
        source = "v1"

    note_dict: dict[str, Any] = {}
    if root_note is not None:
        note_dict[str(get_attr(root_note, "id"))] = root_note
    for note in notes:
        note_dict[str(get_attr(note, "id"))] = note

    return list(note_dict.values()), source


def normalize_nodes(notes: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for note in sorted(notes, key=note_sort_key):
        category = classify_note(note)
        if not category:
            continue
        content = normalize_content(get_attr(note, "content"))
        if not content:
            continue
        normalized.append(
            {
                "id": str(get_attr(note, "id", "")),
                "forum": str(get_attr(note, "forum", "")),
                "replyto": str(get_attr(note, "replyto", "")),
                "category": category,
                "role": note_role_label(note),
                "timestamp_utc": note_timestamp(note),
                "invitation": note_invitation(note),
                "signature": note_signature(note),
                "content": content,
                "content_markdown": format_note_content(note),
            }
        )
    return normalized


def fetch_forum_title(forum_id: str) -> str | None:
    url = f"https://openreview.net/forum?id={forum_id}"
    try:
        with urlopen(url, timeout=20) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    title = re.sub(r"\|\s*OpenReview\s*$", "", title).strip()
    return title or None


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input_path).expanduser().resolve()
    files = discover_text_files(input_path)
    metadata_files = discover_metadata_files(input_path)
    paper_title, title_source = extract_title(files)
    if paper_title is None:
        paper_title, title_source = extract_title_from_metadata(metadata_files)

    forum_candidates = extract_forum_candidates(files)
    forum_candidates.extend(
        candidate
        for candidate in extract_forum_candidates_from_metadata(metadata_files)
        if candidate not in forum_candidates
    )

    result: dict[str, Any] = {
        "status": "env_missing",
        "input_path": str(input_path),
        "paper_title": paper_title,
        "paper_title_source": str(title_source) if title_source else None,
        "forum_id": forum_candidates[0] if forum_candidates else None,
        "forum_url": None,
        "message": "",
        "normalized_notes": [],
        "discussion_markdown": "",
        "openreview_section_markdown": "",
    }

    openreview_mod = load_openreview()
    if openreview_mod is None:
        result["status"] = "env_missing"
        result["message"] = "当前解释器无法导入 openreview。"
        result["openreview_section_markdown"] = build_section_markdown(
            "env_missing", result["message"]
        )
        return result

    try:
        client_v2, client_v1 = build_clients(openreview_mod, args)
    except Exception as exc:
        result["status"] = "env_missing"
        result["message"] = f"OpenReview client 初始化失败: {exc}"
        result["openreview_section_markdown"] = build_section_markdown(
            "env_missing", result["message"]
        )
        return result

    forum_id = result["forum_id"]
    if not forum_id and paper_title:
        forum_id = find_forum_by_title(client_v2, client_v1, paper_title)
        result["forum_id"] = forum_id

    if not forum_id:
        result["status"] = "not_found"
        result["message"] = "未从输入材料或标题匹配中找到唯一可靠的公开 OpenReview forum。"
        result["openreview_section_markdown"] = build_section_markdown(
            "not_found", result["message"]
        )
        return result

    notes, source = fetch_public_discussion(client_v2, client_v1, forum_id)
    normalized = normalize_nodes(notes)

    if paper_title is None:
        paper_title = fetch_forum_title(forum_id)
        result["paper_title"] = paper_title

    result["forum_url"] = f"https://openreview.net/forum?id={forum_id}"

    if not normalized:
        result["status"] = "not_found"
        result["message"] = "OpenReview forum 可访问，但没有返回可用的公开人类审稿、作者回复或决定节点。"
        result["openreview_section_markdown"] = build_section_markdown(
            "not_found", result["message"]
        )
        return result

    result["status"] = "found"
    result["message"] = f"已抓取公开 OpenReview 记录，共 {len(normalized)} 个规范化节点。"
    result["normalized_notes"] = normalized
    result["discussion_markdown"] = build_discussion_markdown(
        paper_title or forum_id, forum_id, notes, source
    )
    result["openreview_section_markdown"] = build_section_markdown("found")
    return result


def main() -> int:
    args = parse_args()

    delegated = maybe_reexec(args)
    if delegated is not None:
        return delegated

    return emit(build_result(args), args.format)


if __name__ == "__main__":
    raise SystemExit(main())
