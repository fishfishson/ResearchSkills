from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "paper-extract" / "scripts" / "extract_sources.py"
OPENREVIEW_HELPER_PATH = REPO_ROOT / "paper-extract" / "scripts" / "fetch_openreview_submission.py"
SKILL_PATH = REPO_ROOT / "paper-extract" / "SKILL.md"
AGENT_PATH = REPO_ROOT / "paper-extract" / "agents" / "openai.yaml"

MODULE_NAME = "paper_extract_extract_sources"
SPEC = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

OPENREVIEW_MODULE_NAME = "paper_extract_fetch_openreview_submission"
OPENREVIEW_SPEC = importlib.util.spec_from_file_location(
    OPENREVIEW_MODULE_NAME,
    OPENREVIEW_HELPER_PATH,
)
OPENREVIEW_MODULE = importlib.util.module_from_spec(OPENREVIEW_SPEC)
sys.modules[OPENREVIEW_MODULE_NAME] = OPENREVIEW_MODULE
assert OPENREVIEW_SPEC.loader is not None
OPENREVIEW_SPEC.loader.exec_module(OPENREVIEW_MODULE)


class ExtractSourcesTests(unittest.TestCase):
    def test_normalize_arxiv_id_accepts_ids_and_urls(self) -> None:
        self.assertEqual(MODULE.normalize_arxiv_id("2401.12345"), "2401.12345")
        self.assertEqual(MODULE.normalize_arxiv_id("arXiv:2401.12345v2"), "2401.12345")
        self.assertEqual(
            MODULE.normalize_arxiv_id("https://arxiv.org/abs/2401.12345v3"),
            "2401.12345",
        )
        self.assertEqual(
            MODULE.normalize_arxiv_id("https://arxiv.org/pdf/2401.12345.pdf"),
            "2401.12345",
        )

    def test_normalize_arxiv_id_rejects_invalid_or_legacy_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported arXiv input"):
            MODULE.normalize_arxiv_id("cs/0112017")

    def test_normalize_cli_path_preserves_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "python-real"
            link = tmp_path / "python-link"

            target.write_text("", encoding="utf-8")
            link.symlink_to(target)

            self.assertEqual(MODULE.normalize_cli_path(str(link)), link)

    def test_normalize_openreview_forum_id_accepts_id_and_url(self) -> None:
        self.assertEqual(MODULE.normalize_openreview_forum_id("abc123_DEF"), "abc123_DEF")
        self.assertEqual(
            MODULE.normalize_openreview_forum_id("https://openreview.net/forum?id=abc123_DEF"),
            "abc123_DEF",
        )
        with self.assertRaisesRegex(ValueError, "Unsupported OpenReview input"):
            MODULE.normalize_openreview_forum_id("https://openreview.net/forum")

    def test_update_paper_registry_dedupes_and_updates_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "paper-id.txt"

            stored = MODULE.update_paper_registry(registry_path, "2401.12345", "Original Title")
            self.assertEqual(stored, "Original Title")
            self.assertEqual(
                registry_path.read_text(encoding="utf-8"),
                "2401.12345: Original Title\n",
            )

            stored = MODULE.update_paper_registry(
                registry_path,
                "2401.12345",
                MODULE.TITLE_UNAVAILABLE,
            )
            self.assertEqual(stored, "Original Title")
            self.assertEqual(
                registry_path.read_text(encoding="utf-8"),
                "2401.12345: Original Title\n",
            )

            stored = MODULE.update_paper_registry(registry_path, "2401.12345", "Updated Title")
            self.assertEqual(stored, "Updated Title")
            self.assertEqual(
                registry_path.read_text(encoding="utf-8"),
                "2401.12345: Updated Title\n",
            )

            MODULE.update_paper_registry(registry_path, "2501.00001", MODULE.TITLE_UNAVAILABLE)
            self.assertEqual(
                registry_path.read_text(encoding="utf-8").splitlines(),
                [
                    "2401.12345: Updated Title",
                    "2501.00001: title-unavailable",
                ],
            )

    def test_allocate_mineru_output_dir_uses_incrementing_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            mineru_root = Path(tmp_dir) / "mineru"
            mineru_root.mkdir()

            (mineru_root / "paper").mkdir()
            (mineru_root / "paper-2").mkdir()

            candidate = MODULE.allocate_mineru_output_dir(mineru_root, Path("/tmp/paper.pdf"))
            self.assertEqual(candidate, mineru_root / "paper-3")

    def test_allocate_incrementing_dir_supports_named_base_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "mineru").mkdir()
            (tmp_path / "mineru-2").mkdir()

            candidate = MODULE.allocate_incrementing_dir(tmp_path / "mineru")

            self.assertEqual(candidate, tmp_path / "mineru-3")

    def test_build_mineru_command_returns_shell_safe_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            mineru_bin = tmp_path / "mineru"
            pdf_path = tmp_path / "paper name.pdf"
            output_dir = tmp_path / "papers" / "mineru" / "paper name"

            mineru_bin.write_text("", encoding="utf-8")
            pdf_path.write_text("%PDF-1.4", encoding="utf-8")

            command = MODULE.build_mineru_command(mineru_bin, pdf_path, output_dir)

            self.assertIn(str(mineru_bin), command)
            self.assertIn("-p", command)
            self.assertIn("-o", command)
            self.assertIn(f"'{pdf_path}'", command)
            self.assertIn(f"'{output_dir}'", command)

    def test_run_mineru_executes_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            mineru_bin = tmp_path / "mineru"
            pdf_path = tmp_path / "paper.pdf"
            output_dir = tmp_path / "papers" / "mineru" / "paper"

            mineru_bin.write_text("", encoding="utf-8")
            pdf_path.write_text("%PDF-1.4", encoding="utf-8")

            with mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=MODULE.subprocess.CompletedProcess(["mineru"], 0, "", ""),
            ) as run_mock:
                command = MODULE.run_mineru(mineru_bin, pdf_path, output_dir)

            self.assertIn(str(mineru_bin), command)
            self.assertTrue(output_dir.parent.exists())
            run_mock.assert_called_once()

    def test_start_mineru_background_writes_job_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            mineru_bin = tmp_path / "mineru"
            pdf_path = tmp_path / "paper.pdf"
            output_dir = tmp_path / "papers" / "mineru" / "paper"
            jobs_root = tmp_path / "papers" / "jobs"

            mineru_bin.write_text("", encoding="utf-8")
            pdf_path.write_text("%PDF-1.4", encoding="utf-8")

            fake_process = mock.Mock(pid=4321)
            with mock.patch.object(MODULE.subprocess, "Popen", return_value=fake_process) as popen_mock:
                result = MODULE.start_mineru_background(mineru_bin, pdf_path, output_dir, jobs_root)

            self.assertEqual(result["pid"], 4321)
            self.assertTrue(Path(str(result["job_path"])).exists())
            self.assertTrue(Path(str(result["log_path"])).exists())
            metadata = json.loads(Path(str(result["job_path"])).read_text(encoding="utf-8"))
            self.assertEqual(metadata["pid"], 4321)
            self.assertEqual(metadata["status"], "running")
            popen_mock.assert_called_once()

    def test_build_execution_plan_orders_arxiv_openreview_before_pdf_and_dedupes(self) -> None:
        tasks, failures = MODULE.build_execution_plan(
            [
                "https://arxiv.org/abs/2401.12345v2",
                "2401.12345",
                "not-an-arxiv-id",
            ],
            [
                "https://openreview.net/forum?id=abc123_DEF",
                "abc123_DEF",
                "https://openreview.net/forum",
            ],
            [
                "/tmp/alpha.pdf",
                "/tmp/alpha.pdf",
                "/tmp/beta.pdf",
            ],
        )

        self.assertEqual(
            [task.route for task in tasks],
            ["arxiv", "openreview", "mineru", "mineru"],
        )
        self.assertEqual(tasks[0].normalized_input, "2401.12345")
        self.assertEqual(tasks[1].normalized_input, "abc123_DEF")
        self.assertTrue(tasks[2].normalized_input.endswith("/tmp/alpha.pdf"))
        self.assertTrue(tasks[3].normalized_input.endswith("/tmp/beta.pdf"))
        self.assertEqual(len(failures), 2)
        self.assertEqual(failures[0].route, "arxiv")
        self.assertEqual(failures[0].status, "fail")
        self.assertEqual(failures[1].route, "openreview")

    def test_validate_python_import_checks_openreview_runtime(self) -> None:
        with self.assertRaises(MODULE.ExtractionError):
            MODULE.validate_python_import(Path(sys.executable), "definitely_missing_module_name")
        MODULE.validate_python_import(Path("/Users/yuzy/.venv/bin/python3"), "openreview")

    def test_format_result_includes_background_details(self) -> None:
        rendered = MODULE.format_result(
            MODULE.ExtractionResult(
                route="mineru",
                raw_input="/tmp/paper.pdf",
                status="background",
                output_path="/tmp/papers/mineru/paper",
                message="MinerU started in background",
                command="/Users/yuzy/.venv/bin/mineru -p /tmp/paper.pdf -o /tmp/papers/mineru/paper -m auto -b hybrid-auto-engine",
                job_path="/tmp/papers/jobs/mineru-1.json",
                log_path="/tmp/papers/jobs/mineru-1.log",
                pid=1234,
            )
        )
        self.assertIn("[BACKGROUND] mineru /tmp/paper.pdf", rendered)
        self.assertIn("command: /Users/yuzy/.venv/bin/mineru", rendered)
        self.assertIn("pid: 1234", rendered)
        self.assertIn("job: /tmp/papers/jobs/mineru-1.json", rendered)
        self.assertIn("log: /tmp/papers/jobs/mineru-1.log", rendered)

    def test_openreview_helper_writes_submission_and_metadata(self) -> None:
        class FakeClient:
            def __init__(self, note: dict[str, object], payload: bytes) -> None:
                self.note = note
                self.payload = payload

            def get_note(self, note_id: str) -> dict[str, object]:
                self.requested_id = note_id
                return self.note

            def get_attachment(self, **_: object) -> bytes:
                return self.payload

        note = {
            "id": "abc123_DEF",
            "content": {
                "title": "OpenReview Paper",
                "authors": ["Alice", "Bob"],
                "venue": "ICLR 2026",
                "pdf": "/pdf?id=abc123_DEF",
            },
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "papers" / "openreview" / "abc123_DEF"
            client_v2 = FakeClient(note, b"%PDF-1.4")
            client_v1 = FakeClient(note, b"%PDF-1.4")

            result = OPENREVIEW_MODULE.fetch_submission_bundle(
                client_v2,
                client_v1,
                "abc123_DEF",
                output_dir,
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue((output_dir / "submission.pdf").exists())
            self.assertTrue((output_dir / "metadata.json").exists())
            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["title"], "OpenReview Paper")
            self.assertEqual(metadata["venue"], "ICLR 2026")
            self.assertFalse(metadata["pdf_reused"])

    def test_update_paper_registry_supports_openreview_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "paper-id.txt"

            stored = MODULE.update_paper_registry(registry_path, "abc123_DEF", "OpenReview Paper")

            self.assertEqual(stored, "OpenReview Paper")
            self.assertEqual(
                registry_path.read_text(encoding="utf-8"),
                "abc123_DEF: OpenReview Paper\n",
            )

    def test_skill_metadata_matches_expected_contract(self) -> None:
        skill_text = SKILL_PATH.read_text(encoding="utf-8")
        self.assertTrue(skill_text.startswith("---\nname: paper-extract\n"))
        self.assertIn("technical report", skill_text)
        self.assertIn("explicit arXiv ID or arXiv URL", skill_text)
        self.assertIn("OpenReview forum ID", skill_text)
        self.assertIn("./papers", skill_text)
        self.assertIn("/Users/yuzy/.venv/bin/mineru", skill_text)
        self.assertIn("/Users/yuzy/.venv/bin/python3", skill_text)
        self.assertIn("--mineru-mode background", skill_text)
        self.assertIn("Do not poll background MinerU jobs", skill_text)
        self.assertIn("./papers/jobs/<job-id>.json", skill_text)
        self.assertIn("./papers/openreview/paper-id.txt", skill_text)
        self.assertIn("forum-id: title", skill_text)

        agent_text = AGENT_PATH.read_text(encoding="utf-8")
        self.assertIn('display_name: "Paper Extract"', agent_text)
        self.assertIn("OpenReview", agent_text)
        self.assertIn("background mode by default", agent_text)


if __name__ == "__main__":
    unittest.main()
