---
name: model-choose
description: Automatically selects the most cost-effective and task-appropriate model in Gemini CLI to save tokens and minimize costs. Use when you need to decide which model to use for a specific task or want to switch models during a session.
---

# Model Selection Guide

This skill provides a workflow for Gemini CLI to analyze tasks and switch to the most "fit" model using the `/model set` command.

## Workflow

### 1. Task Analysis
Before starting a task, categorize it based on complexity and context size:

- **Simple (Fast/Cheap):** Summarization, single-file code explanation, unit test generation, basic CLI commands, text editing.
  - **Preferred Model:** `gemini-2.0-flash`
- **Moderate (Standard):** Multi-file analysis, complex debugging, refactoring, feature implementation in medium codebases.
  - **Preferred Model:** `gemini-2.0-flash` (First attempt), `gemini-2.0-pro-exp` (If Flash fails).
- **Complex (Deep Reasoning):** Architectural design, complex logic across many files, root-cause analysis in large repositories.
  - **Preferred Model:** `gemini-2.0-pro-exp` or `gemini-1.5-pro` (If available).

### 2. Context Optimization
To minimize tokens, follow these steps before switching models:
- **Search First:** Use `grep_search` or `glob` to find relevant files.
- **Selective Reading:** Only use `read_file` for specific line ranges if the file is large.
- **Summarize Early:** If context is growing too large, summarize existing findings before switching to a more expensive model.

### 3. Execution
Use the `/model set <model-name>` command to switch to the appropriate model.

- **Example:** If the user asks for a simple unit test and you are currently on a Pro model, switch to Flash: `/model set gemini-2.0-flash`.
- **Note:** Always inform the user when switching models to ensure transparency about potential performance changes.

## Model Reference
For a detailed list of model capabilities, context windows, and cost tiers, refer to [references/model-matrix.md](references/model-matrix.md).
