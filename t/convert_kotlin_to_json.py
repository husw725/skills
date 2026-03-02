#!/usr/bin/env python3
"""Convert Kotlin Questions in Datas.kt to JSON.

Parses entries like:
  Question("text", listOf("A","B","C","D"), 2),

Output:
  {"version": 1, "questions": [{"text":..., "options":[...], "correctIndex":...}, ...]}

Notes:
- Handles // and /* */ comments.
- Handles normal quoted strings and Kotlin triple-quoted strings.
- Preserves UTF-8 characters (e.g., Chinese) correctly.
"""

import json
import re
import sys


def strip_comments(s: str) -> str:
    s = re.sub(r"//.*?$", "", s, flags=re.M)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s


def decode_kotlin_string(lit: str) -> str:
    if lit.startswith('"""'):
        return lit[3:-3]
    inner = lit[1:-1]
    # Minimal unescaping (dataset is mostly plain UTF-8)
    inner = inner.replace(r"\\", "\\")
    inner = inner.replace(r"\"", '"')
    inner = inner.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t")
    return inner


def parse_questions(kotlin: str):
    kotlin = strip_comments(kotlin)

    q_re = re.compile(
        r"Question\(\s*"
        r"(\"\"\".*?\"\"\"|\"(?:\\.|[^\"\\])*\")\s*,\s*"
        r"(?:listOf|mutableListOf)\(\s*(.*?)\s*\)\s*,\s*"
        r"(\d+)\s*\)",
        re.S,
    )

    str_lit_re = re.compile(r"\"\"\".*?\"\"\"|\"(?:\\.|[^\"\\])*\"", re.S)

    questions = []
    for m in q_re.finditer(kotlin):
        text = decode_kotlin_string(m.group(1))
        options_payload = m.group(2)
        correct_idx = int(m.group(3))
        options = [decode_kotlin_string(s) for s in str_lit_re.findall(options_payload)]
        questions.append({"text": text, "options": options, "correctIndex": correct_idx})

    return questions


def main():
    if len(sys.argv) < 2:
        print("Usage: convert_kotlin_to_json.py <input.kt> [output.json]", file=sys.stderr)
        sys.exit(2)

    inp = sys.argv[1]
    outp = sys.argv[2] if len(sys.argv) >= 3 else "full_questions_output.json"

    kotlin = open(inp, "r", encoding="utf-8").read()
    questions = parse_questions(kotlin)

    data = {"version": 1, "questions": questions}
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Converted {len(questions)} questions -> {outp}")


if __name__ == "__main__":
    main()
