# ResearchSkills

`ResearchSkills` is a local Codex skill repository for academic paper workflows. The current public scope focuses on four tasks:

- staging paper sources from PDF, arXiv, or OpenReview inputs
- writing Chinese evidence-grounded paper overviews
- writing Chinese evidence-grounded peer reviews
- expanding one seed paper into a compact citation-first literature lineage

This repository is not a packaged Python library. It is designed to be opened directly in Codex as a workspace with bundled skills, scripts, and references.

## Included Skills

| Skill | Purpose | Typical Output |
| --- | --- | --- |
| `paper-extract` | Collect paper source materials from explicit local PDFs, arXiv IDs/URLs, or OpenReview forum IDs/URLs | `./papers/arxiv/...`, `./papers/openreview/...`, `./papers/mineru/...` |
| `paper-analyzer` | Analyze a CV/CG paper from local LaTeX or Markdown and write a Chinese deep-reading summary | `overview.md` beside the input |
| `paper-reviewer-en` | Review a paper/manuscript from local LaTeX or Markdown and write a Chinese peer-review style report | `review.md` beside the input |
| `paper-lineage-review` | Start from one local paper directory, expand a citation-first paper pool, and summarize the technical trajectory | `.paper_lineage_review/` package under the paper directory |

## Repository Layout

```text
.
├── AGENTS.md
├── paper-analyzer/
├── paper-extract/
├── paper-lineage-review/
├── paper-reviewer-en/
└── papers/                 # local workspace for extracted/generated materials
```

- `AGENTS.md`: repository-level instructions, including the local runtime environment for this machine
- `paper-*/SKILL.md`: the actual skill definitions used by Codex
- `paper-*/scripts/`: helper scripts for deterministic or repeated operations
- `paper-*/references/`: reusable references and writing constraints
- `papers/`: local working area for extracted papers and generated artifacts; this is workspace state rather than core repo logic

## Quick Start

1. Open this repository in Codex.
2. Read [`AGENTS.md`](AGENTS.md) and use the runtime settings defined in its `Local Runtime Environment` section.
3. Invoke a skill explicitly, or ask for a task that clearly matches one of the included skills.

Example prompts:

```text
Use $paper-extract to fetch arXiv 2503.01774 into the local papers workspace.
Use $paper-analyzer on ./papers/arxiv/2503.01774 and write overview.md.
Use $paper-reviewer-en to review ./papers/arxiv/2503.01774/main.tex.
Use $paper-lineage-review on ./papers/arxiv/2503.01774.
```

## Runtime Notes

- Machine-specific interpreter paths and tool paths belong in `AGENTS.md`, not in the skill bodies.
- OpenReview-backed flows require a Python interpreter that can `import openreview`.
- PDF extraction flows require a working `mineru` binary.
- Some skills are purely local to this repository and are not meant to be copied into global Codex skills.

## Current Status

The repository currently contains the skill definitions and helper scripts that have already been prepared for GitHub:

- `paper-extract` includes executable scripts plus unit tests
- `paper-lineage-review` includes a multi-step pipeline plus tests
- `paper-analyzer` and `paper-reviewer-en` currently focus on skill instructions, references, and OpenReview-aware workflows

## License

This repository is released under the terms in [LICENSE](LICENSE).
