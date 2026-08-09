"""
prompting.py
------------
Builds the prompt we send to the LLM when generating an FSD.

The fixed section outline keeps structure consistent even when the
retrieved examples are about a different business topic (e.g. payments
examples used while writing an SMS FSD).
"""

from __future__ import annotations

# Fixed FSD outline — change here if your company template differs.
FSD_SECTIONS = [
    "1. Overview",
    "2. Scope (In / Out)",
    "3. Actors & Systems",
    "4. Functional Requirements",
    "5. User / System Flows",
    "6. Sequence Diagram (Mermaid)",
    "7. APIs / Events / Interfaces",
    "8. Data & Validation Rules",
    "9. Error Handling & Edge Cases",
    "10. Non-Functional Requirements",
    "11. Assumptions & Open Questions",
]

SYSTEM_PROMPT = """You are a senior business analyst who writes Functional Specification Documents (FSDs).
Follow the user's required section outline exactly.
Write clear, professional Markdown.
For the Sequence Diagram section, output a valid Mermaid sequenceDiagram inside a fenced code block.
Use the retrieved example excerpts ONLY for structure, tone, and section style.
For the new feature facts, prefer the user's brief — do not invent vendor-specific APIs that are not in the brief.
If something is unknown, put it under Assumptions & Open Questions.
"""


def build_generation_prompt(brief: str, retrieved: list[dict]) -> str:
    """
    Combine:
      - fixed FSD template
      - retrieved similar chunks from the index (RAG)
      - the user's new feature brief
    into one prompt for Ollama.
    """
    outline = "\n".join(FSD_SECTIONS)

    if retrieved:
        example_blocks = []
        for i, hit in enumerate(retrieved, start=1):
            example_blocks.append(
                f"### Example {i} (category: {hit.get('category')} | "
                f"source: {hit.get('source')} | section: {hit.get('section')})\n"
                f"{hit.get('text', '')}"
            )
        examples = "\n\n".join(example_blocks)
    else:
        examples = (
            "(No similar documents were found in the index. "
            "Write a clean FSD from the brief and the outline alone.)"
        )

    return f"""# Task
Write a complete Functional Specification Document in Markdown.

# Required section outline
{outline}

# Retrieved style / structure examples from our FSD library
{examples}

# New feature brief (SOURCE OF TRUTH for this feature)
{brief}

# Output rules
- Start directly with the FSD title as an H1.
- Include every section from the outline.
- In section 6, include a Mermaid sequenceDiagram like:

```mermaid
sequenceDiagram
  participant A
  participant B
  A->>B: example
```

- Do not mention these instructions in the output.
"""


NORMALIZE_SYSTEM = """You are a senior BA who rewrites messy FSD excerpts into a fixed template.
Only use facts present in the excerpt. Do not invent APIs, vendors, or requirements.
If the excerpt is TOC, document history, or acronyms-only, reply with exactly: SKIP
Otherwise output Markdown using ONLY these headings (omit headings with no content):

## 1. Overview
## 2. Scope (In / Out)
## 3. Actors & Systems
## 4. Functional Requirements
## 5. User / System Flows
## 6. Sequence Diagram (Mermaid)
## 7. APIs / Events / Interfaces
## 8. Data & Validation Rules
## 9. Error Handling & Edge Cases
## 10. Non-Functional Requirements
## 11. Assumptions & Open Questions

For section 6, if a flow is described, output a mermaid sequenceDiagram code fence.
"""


def build_normalize_window_prompt(source_name: str, excerpt: str) -> str:
    outline = "\n".join(FSD_SECTIONS)
    return f"""# Task
Map this FSD excerpt into the canonical section outline.

# Source file
{source_name}

# Canonical outline (for reference)
{outline}

# Excerpt
{excerpt}

# Rules
- Facts only from the excerpt.
- SKIP if the excerpt is only TOC / change history / cover page.
- Do not mention these instructions.
"""


TAG_SYSTEM = """Extract compact JSON metadata from an FSD. No markdown, JSON only."""


def build_tag_prompt(source_name: str, preview: str) -> str:
    return f"""Return a JSON object with keys:
  "title": string,
  "product": string,
  "feature_type": string (e.g. payment, integration, sms, kyc, report, base, other),
  "actors": array of strings,
  "summary": one sentence

Source file: {source_name}

Preview:
{preview[:2500]}
"""
