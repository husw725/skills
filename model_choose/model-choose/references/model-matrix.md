# Gemini Model Matrix

| Model Name | Context Window | Speed | Cost | Ideal Use Case |
| :--- | :--- | :--- | :--- | :--- |
| `gemini-2.0-flash` | 1M Tokens | ⚡⚡⚡ | 🪙 | Summarization, simple coding, quick Q&A, chat. |
| `gemini-2.0-flash-lite-preview-02-05` | 1M Tokens | ⚡⚡⚡⚡ | 🪙 | Even cheaper/faster for very high-volume simple tasks. |
| `gemini-1.5-flash` | 1M Tokens | ⚡⚡ | 🪙 | Legacy support for high-throughput, simple workflows. |
| `gemini-2.0-pro-exp-02-05` | 2M Tokens | ⚡ | 🪙🪙🪙 | Deep reasoning, complex coding, multi-file analysis. |
| `gemini-1.5-pro` | 2M Tokens | ⚡ | 🪙🪙🪙 | Production-grade complex reasoning and large context. |

## Selection Heuristics

### Choose **Flash** when:
- The task is straightforward (e.g., "Explain this function").
- You need a fast response.
- You are doing high-volume, low-complexity tasks (e.g., unit test generation for many files).

### Choose **Pro** when:
- The task involves complex logic across multiple files.
- You need to design an architecture or refactor a large system.
- The task requires deep reasoning or following very strict constraints.
- Flash keeps failing to produce correct results.

## Token Optimization Tips
- **Grep Before Read:** Always search for the exact information needed.
- **Truncate Large Files:** Use `read_file` with `start_line` and `end_line`.
- **Reset Session:** If the context is full of irrelevant history, suggest the user to start a new session (`/reset`).
