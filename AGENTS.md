# Repository Guidelines

## Project Structure & Module Organization
- `scripts/`: core Python CLIs for reference-processing workflows.
  - `extract_mineru_refs.py`: extract references from Mineru `content_list.json`.
  - `download_arxiv_tex.py`: resolve arXiv IDs, download/extract TeX sources, and write mapping JSON.
  - `extract_arxiv_refs.py`: parse `.bbl` files into normalized reference JSON.
- `Ref/`: input/reference assets (papers, parsed outputs, skill examples). Treat as data/examples, not core runtime code.
- Root JSON artifacts (`refs.json`, `refs-tex.josn`): generated outputs and intermediate data.

## Build, Test, and Development Commands
This repository has no build system; use script-level commands directly.
- `python3 scripts/extract_mineru_refs.py <content_list.json> -o refs.json`
  - Extracts and normalizes references from Mineru output.
- `python3 scripts/download_arxiv_tex.py --input refs.json --output refs-tex.json --papers-dir ~/Desktop/Papers`
  - Downloads and extracts arXiv TeX sources for matched references.
- `python3 scripts/extract_arxiv_refs.py <paper_dir> -o arxiv_refs.json`
  - Extracts references from a TeX project’s `.bbl` file.
- `python3 scripts/<script>.py -h`
  - Shows CLI options and expected inputs.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and clear, single-purpose functions.
- Use `snake_case` for functions/variables, `UPPER_SNAKE_CASE` for constants.
- Keep CLI behavior explicit: argument parsing in `main()`, pure helper functions outside `main()`.
- Preserve UTF-8 handling for mixed Chinese/English text processing.

## Testing Guidelines
- No automated test framework is configured yet.
- Minimum requirement for changes: run a CLI smoke test on real sample data and verify output JSON schema (`id`, `text`, optional `cite_key`/`arxiv_id`/`tex_path`).
- If adding non-trivial parsing logic, add `pytest` tests under `tests/` (new directory) and cover edge cases (split refs, malformed LaTeX, missing files).

## Commit & Pull Request Guidelines
- Current repository has no commit history yet; adopt Conventional Commits going forward (e.g., `feat: add arxiv title fallback`, `fix: handle empty bibitem`).
- Keep commits focused to one functional change.
- PRs should include:
  - purpose and scope,
  - sample command used for validation,
  - before/after output snippet or file path,
  - linked issue/task if available.

## Local Runtime Environment
- On this machine, always run Python commands in this repository with `/Users/yuzy/.venv/bin/python3`.
- On this machine, use `/Users/yuzy/.venv/bin/mineru` for MinerU invocations in this repository.
- Do not use bare `python3`, `pip`, or `pip3` for commands in this repository.
- When installing packages, use `/Users/yuzy/.venv/bin/python3 -m pip ...`.
- If a script or tool accepts an interpreter argument such as `--python-path` or `--openreview-python`, pass `/Users/yuzy/.venv/bin/python3`.
- If a script or tool accepts a MinerU binary argument such as `--mineru-bin`, pass `/Users/yuzy/.venv/bin/mineru`.
- If a script hardcodes bare `python3` or a machine-specific MinerU path, treat it as an environment drift risk and prefer making the runtime externally injectable or documenting it here.
- This section overrides the generic `python3` examples above for local execution in this repository and is the only place for machine-specific runtime paths.
