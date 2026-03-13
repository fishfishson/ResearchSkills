---
name: paper-analyzer
description: Analyze computer vision or graphics papers from local LaTeX source files/directories or Markdown documents, optionally incorporating public OpenReview reviews, and write a Chinese evidence-grounded overview.md.
---

# Paper Analyzer

## Overview

Use this skill to produce a Chinese deep-reading `overview.md` for a computer vision or computer graphics paper and write it to the local input location by default.

This skill is for AI-readable text materials only. It prioritizes local LaTeX source files/directories and Markdown documents, then extracts the paper's problem setting, method logic, experimental evidence, innovation boundary, and limitations into a structured overview with explicit evidence anchors.

Before finalizing `overview.md`, this skill should also proactively attempt to fetch public OpenReview review materials. When public reviewer comments, author replies, rebuttal, decision, or meta review are available, use them as supplementary evidence and add a dedicated `openreview` chapter at the end of `overview.md`.

By default, the final analysis must be written to a real local `overview.md` file:

- directory input -> `<input_dir>/overview.md`
- single `.tex` or `.md` file input -> `<parent_dir>/overview.md`

After writing the file, return only a short confirmation with the output path and a brief summary.

## Input Contract

Accept only the following input types:

1. A single LaTeX source file, such as `main.tex`
2. A LaTeX project directory containing files such as `main.tex`, chapter `.tex` files, appendix `.tex` files, or supplementary `.tex` files
3. One or more Markdown documents containing paper text, structured notes, parsed sections, or author summaries

Recommended input combinations:

- `main.tex` plus appendix or supplementary `.tex`
- A complete LaTeX project directory
- A main Markdown document plus supplementary Markdown notes

Optional helpful hints:

- an explicit OpenReview forum URL
- an OpenReview forum ID
- a local note mentioning the paper's OpenReview link

All accepted inputs must be:

- text-readable by the model
- quoteable and locatable by section, figure, table, equation, appendix, or Markdown heading
- sufficient to trace major claims back to explicit textual evidence

## Unsupported Inputs

Do not treat the following as valid default inputs:

- PDF only
- images, screenshots, scans, or photo captures
- webpage screenshots or slide screenshots
- other purely visual layout files that are not directly machine-readable text

If the user provides only unsupported inputs, do not produce a deep-reading conclusion. Instead, ask the user to provide one of:

- a local `.tex` file
- a LaTeX source directory
- a `.md` document

## Input Priority And Degradation Rules

1. If LaTeX source is available, use LaTeX as the primary source.
2. If only Markdown is available, analyze directly from Markdown.
3. If both `.tex` and `.md` are available, use the more complete and better anchored source as primary input, and use the other one only for cross-checking.
4. If only partial chapters or partial Markdown notes are available, continue only as a partial analysis and explicitly state that the overview is based on incomplete materials.
5. If key evidence such as experiment tables, appendix details, or equation context is missing, mark related judgments as `待核实` or `证据不足`.

## Output Path Rules

Resolve the output path before writing the final analysis:

1. If the input is a directory, write to `<input_dir>/overview.md`.
2. If the input is a single `.tex` or `.md` file, write to `<parent_dir_of_input>/overview.md`.
3. If the user provides multiple explicit files, write automatically only when all files are in the same directory. Otherwise, stop and ask the user to provide a single paper directory.
4. If `overview.md` already exists at the target path, overwrite it directly.

Examples:

- input `/path/paper_dir` -> output `/path/paper_dir/overview.md`
- input `/path/main.tex` -> output `/path/overview.md`
- input `/path/paper.md` -> output `/path/overview.md`

## OpenReview Preflight

Run this section before any OpenReview-related work.

Treat OpenReview availability as Python importability, not as a shell CLI binary. The required check is whether a Python interpreter can run `import openreview`.

Deterministic preflight sequence:

1. Try the current interpreter first:

```bash
python3 -c "import openreview"
```

2. If that succeeds, treat the current `python3` as the OpenReview runtime for the rest of the turn.
3. If that fails, ask the user for an absolute `python_path`, for example `/Users/yuzy/.venv/bin/python3`.
4. Validate the user-provided interpreter:

```bash
<python_path> -c "import openreview"
```

5. If validation succeeds, reuse that exact interpreter for every OpenReview-related command in the turn. Do not mix interpreters.
6. If validation still fails, do not block the overall paper analysis. Continue writing `overview.md`, but in the `openreview` chapter explicitly state that the environment is unresolved and public OpenReview content was not fetched in this run.

Expected failure prompt:

`当前 python3 无法导入 openreview。请提供一个可用的绝对 Python 路径，例如 /Users/yuzy/.venv/bin/python3。`

## OpenReview Fetch Rules

Use the bundled script for OpenReview discovery and fetching:

```bash
python3 paper-analyzer/scripts/fetch_openreview_public.py --input-path PATHTODIR
```

If the current `python3` cannot import `openreview`, rerun the same script with the validated interpreter:

```bash
<python_path> paper-analyzer/scripts/fetch_openreview_public.py --input-path PATHTODIR
```

The script returns a standardized result with at least:

- `status`: `found`, `not_found`, or `env_missing`
- `paper_title`
- `forum_id`
- `forum_url`
- normalized public review nodes
- raw discussion markdown for the public thread

Deterministic discovery order:

1. First parse explicit OpenReview forum URLs or forum IDs from the local paper materials.
2. If none are found, do best-effort forum discovery using the paper title.
3. If no unique reliable public forum can be found, treat the OpenReview status as `not_found`.

Only use public and human-authored OpenReview materials:

- official reviews
- reviewer official comments
- author rebuttal or official comments
- public decision or meta review

Do not rely on:

- private or unavailable review content
- acknowledgement-only nodes
- empty system nodes
- any guessed or reconstructed review content

## Core Workflow

1. **Check Input Legality**
   - Confirm the input is a local `.tex` file, LaTeX directory, or `.md` document.
   - If not, stop and request AI-readable text materials.
2. **Run OpenReview Preflight**
   - Check whether the current `python3` can import `openreview`.
   - If not, ask for `python_path`, but continue the overall paper analysis even if no valid interpreter is ultimately available.
3. **Build Paper Skeleton**
   - Identify the title, task setting, claimed contributions, method sections, experiment sections, appendices, and conclusion.
   - Ignore pure formatting commands such as `\vspace`, figure placement controls, or unrelated macro definitions.
4. **Try OpenReview Fetch**
   - Use the bundled script to parse explicit forum hints and do best-effort discovery.
   - If public OpenReview materials are found, read them before drafting the final overview.
   - If the script reports `env_missing` or `not_found`, keep that status for the final `openreview` chapter.
5. **Extract Evidence**
   - Pull the minimum necessary evidence from sections, figures, tables, equations, appendix materials, and OpenReview public materials when available.
   - Prefer decisive evidence: main comparison tables, key ablations, sensitivity analysis, efficiency results, failure-case or limitation discussions, and public reviewer concerns plus author rebuttal responses.
6. **Make Bounded Judgments**
   - Distinguish paper facts from your own analysis.
   - Judge not only what the paper claims, but also whether the available evidence is sufficient to support those claims.
   - Treat OpenReview content as review evidence, not as manuscript fact.
7. **Resolve Output Path**
   - Determine the target `overview.md` path using the rules above.
   - If multiple files come from different directories, stop and request a directory input instead of guessing the output location.
8. **Write `overview.md`**
   - Write the final Chinese structured overview to the resolved local path.
   - Overwrite an existing `overview.md` when present.
   - Retain English method names, dataset names, benchmark names, metric names, and critical equations.
9. **Reply Briefly**
   - Return a short confirmation containing the output path and a compact summary.
   - Do not repeat the entire `overview.md` body in the chat unless the user explicitly asks for it.

## CV/CG Analysis Checklist

For most computer vision or graphics papers, explicitly check the following:

- **Problem setting**: task definition, input/output, target bottleneck, assumptions, and why the task matters
- **Contribution type**: method innovation, representation innovation, supervision/data construction, task setting innovation, or system combination
- **Method logic**: pipeline, core modules, representation choice, losses/objectives, training flow, inference flow, and why each design is needed
- **Experimental evidence**: datasets, protocols, metrics, baselines, decisive gains, ablations, robustness, generalization, efficiency, and visual quality
- **Innovation boundary**: whether the work is a strong methodological advance, a solid systems paper, a data-centric contribution, or mainly a combination-style incremental improvement
- **Limitations**: author-stated weaknesses, evidence gaps, missing controls, and unresolved boundary conditions

Apply the following conditional checks when relevant:

- **If the paper involves 3D**: additionally check geometry consistency, supervision source, representation capacity, rendering speed, and memory/storage cost
- **If the paper involves graphics**: additionally check visual fidelity, controllability, geometry or physics plausibility, interaction cost, complexity, and deployability

If a paper involves both 3D and graphics, apply both sets of additional checks. Otherwise, use only the common checklist above.

## Deterministic Output Structure

Output `overview.md` using the following sections in order:

### 1. Title And TL;DR

- **Title**: [Paper title]
- **TL;DR**: [One sentence summarizing the problem, the core idea, and the main payoff]

### 2. Research Problem And Task Setting

- What problem the paper solves
- Why the problem matters
- What prior methods fail at
- What inputs, outputs, and assumptions define the task
- `来源依据：...`

### 3. Core Contributions And Innovation Boundary

- List the paper's claimed contributions
- Classify each contribution type
- State whether the innovation is strong, moderate, limited-but-valid, or mainly combinational
- Separate paper claims from your judgment
- `来源依据：...`

### 4. Method Overview

- Core pipeline or architecture
- Key representations, modules, losses, or optimization targets
- Training and inference flow
- Why each major design exists
- Preserve critical equations in LaTeX when they are central to the paper
- `来源依据：...`

### 5. Experimental Design And Evidence

- **Datasets / Tasks / Metrics**
- **Baselines**
- **Main Results**
- **Key Ablations**
- **Generalization / Robustness / Efficiency / Visualization**
- For each subsection, say what was tested, why it was tested, and what conclusion it supports
- `来源依据：...`

### 6. CV/CG-Specific Technical Checks

- Discuss the most relevant domain-specific checks for this paper
- Examples: geometry consistency, supervision source, representation choice, rendering speed, memory/storage cost, controllability, and visual fidelity versus numeric metrics
- If a check cannot be verified from the materials, mark it as `待核实`
- `来源依据：...`

### 7. Limitations And Open Questions

- Author-stated limitations
- Evidence-supported boundary conditions
- Claims that seem stronger than the available evidence
- Missing experiments, missing controls, or unclear assumptions
- `来源依据：...`

### 8. Overall Assessment

- State what the paper truly contributes to the field
- Judge whether it is best understood as a strong methods paper, a solid engineering paper, an insightful boundary case, or a data/system-centric work
- Keep the judgment evidence-grounded and bounded
- `来源依据：...`

## openreview

Keep this as a top-level chapter in the final `overview.md`.

If OpenReview public materials were found, this chapter must contain exactly these three subsections:

### 1. 整体评价

- Summarize the overall public reviewer consensus and decision tendency when visible
- Cite only OpenReview public materials

### 2. 论文的具体优点和缺点

- Summarize concrete strengths and weaknesses from public reviews
- Keep the source limited to OpenReview public content
- Do not mix in manuscript-only evidence in this chapter

### 3. 主要问题、作者回答与 rebuttal 是否解决

Use a table with the following columns:

| 问题 | 来源 | 作者回答摘要 | rebuttal 是否解决 | 说明 |
| --- | --- | --- | --- | --- |

Allowed resolution labels:

- `基本解决`
- `大体解决`
- `部分解决`
- `未解决`

If the OpenReview fetch status is `env_missing` or `not_found`, still keep the `## openreview` chapter, but replace the three subsections with a short status explanation:

- `env_missing`: `OpenReview 环境未就绪，本次未抓取公开审稿。`
- `not_found`: `未检索到可靠公开 OpenReview 人类审稿/作者回复。`

Do not fabricate reviewer opinions in these fallback cases.

## Evidence Rules

1. Every major judgment should be traceable to explicit evidence.
2. Use anchors such as:
   - `来源依据：第 3 节, Fig. 2, Table 1`
   - `来源依据：公式 (4), Appendix B`
   - `来源依据：Markdown 小节 "Method"`
3. Do not invent metrics, baselines, equations, datasets, or conclusions that are not present in the input materials.
4. When making an inference, phrase it as analysis rather than fact.
5. When evidence is incomplete, say `基于不完整材料` and mark missing parts as `待核实` or `证据不足`.
6. In the `openreview` chapter, cite sources separately, for example:
   - `来源依据：OpenReview official review #1`
   - `来源依据：OpenReview author rebuttal`
   - `来源依据：OpenReview decision note`
7. OpenReview reviews, rebuttals, and decisions may sharpen reviewer context, but they do not become manuscript fact.

## Writing Rules

1. Write in Chinese by default, but keep English technical terms, method names, dataset names, and metric names unchanged.
2. Use short paragraphs and compact bullets. Prefer density over fluff.
3. Do not copy large chunks of the paper. Quote only the minimum needed to support a judgment.
4. Define new abbreviations on first use.
5. Ignore non-content LaTeX markup and formatting noise.
6. Focus on the paper's main line, decisive technical logic, and strongest supporting evidence.
7. Do not output review-style sections about OpenReview, rebuttal, or meta review outside the required `## openreview` chapter.
8. The `openreview` chapter must contain only OpenReview public evidence or an explicit status explanation. Do not blend in manuscript-only claims there.

## Output Contract

When provided with valid inputs, return:

1. Write one real local `overview.md` file following the deterministic structure above
2. Use the resolved local path rules defined in this skill
3. Overwrite an existing target `overview.md` by default
4. Always include a top-level `## openreview` chapter in the final `overview.md`
5. If public OpenReview materials are available, fill that chapter using only public OpenReview evidence
6. If OpenReview environment is unavailable or no reliable public forum is found, keep the chapter and write an explicit status explanation
7. Return only a short confirmation with the output path and a brief summary
8. No extra preamble or side commentary

When provided only unsupported inputs, return:

1. A short request asking for a local LaTeX source file, LaTeX directory, or Markdown document
2. No fabricated analysis based on PDF-only or image-only content
