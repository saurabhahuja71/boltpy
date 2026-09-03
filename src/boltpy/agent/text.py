"""Helpers for preserving code while tidying model response whitespace."""
from __future__ import annotations

import re


_FENCE_LINE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<tail>[^\r\n]*)(?:\r?\n)?$")
_EXCESSIVE_BLANK_LINES = re.compile(r"(?:[ \t]*\r?\n){3,}")
_LEADING_BLANK_LINES = re.compile(r"^(?:[ \t]*\r?\n){2,}")
_PYTHON_IMPORT = re.compile(r"^(?:import\s+\w|from\s+\S+\s+import\s+)")
_PYTHON_DECLARATION = re.compile(r"^(?:async\s+)?(?:def|class)\s+\w+")
_PYTHON_DECORATOR = re.compile(r"^@\w")
_PYTHON_CONTROL = re.compile(r"^(?:if|elif|else|for|while|try|except|finally|with|match|case)\b")
_PYTHON_RETURN = re.compile(r"^(?:return|yield|raise)\b")
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?\s*=")
_SHELL_COMMAND = re.compile(r"^(?:\$\s*)?(?:python(?:\d+(?:\.\d+)?)?|pip(?:3)?|uv|npm|yarn|git|curl|wget|cd|mkdir|export|source|sudo)\b")
_STRUCTURED_VALUE = re.compile(r"^(?:[A-Za-z_]\w*|[\"'][^\"']+[\"'])\s*:\s*\S")


def _fence_marker(line: str) -> tuple[str, int] | None:
    match = _FENCE_LINE.match(line)
    if match is None:
        return None
    marker = match.group("marker")
    return marker[0], len(marker)


def _is_closing_fence(line: str, fence: tuple[str, int]) -> bool:
    match = _FENCE_LINE.match(line)
    if match is None or match.group("tail").strip():
        return False
    marker = match.group("marker")
    return marker[0] == fence[0] and len(marker) >= fence[1]


def _collapse_blank_lines(text: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        newline = "\r\n" if "\r\n" in match.group(0) else "\n"
        return newline * 2

    return _EXCESSIVE_BLANK_LINES.sub(replacement, text)


def _compact_after_fence(text: str) -> str:
    """Keep at most one blank line after a preserved closing fence."""
    match = _LEADING_BLANK_LINES.match(text)
    if match is None:
        return text
    newline = "\r\n" if "\r\n" in match.group(0) else "\n"
    return newline + text[match.end():]


def _code_line_kind(line: str) -> str | None:
    """Classify only strong, line-level indicators of unfenced code."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if _PYTHON_IMPORT.match(stripped):
        return "import"
    if _PYTHON_DECLARATION.match(stripped):
        return "declaration"
    if _PYTHON_DECORATOR.match(stripped):
        return "decorator"
    if _PYTHON_CONTROL.match(stripped):
        return "control"
    if _PYTHON_RETURN.match(stripped):
        return "return"
    if _SHELL_COMMAND.match(stripped):
        return "shell"
    if _STRUCTURED_VALUE.match(stripped):
        return "structured"
    if _ASSIGNMENT.match(stripped):
        return "assignment"
    return None


def _nearby_code_kinds(lines: list[str], index: int, step: int) -> list[str]:
    kinds: list[str] = []
    cursor = index + step
    while 0 <= cursor < len(lines) and len(kinds) < 6:
        line = lines[cursor]
        if line.strip("\r\n \t"):
            kind = _code_line_kind(line)
            if kind is None:
                break
            kinds.append(kind)
        cursor += step
    return kinds


def _normalize_unfenced_code(text: str) -> str:
    """Remove only high-confidence artificial gaps in unfenced code clusters."""
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        return text
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip("\r\n \t"):
            output.append(line)
            index += 1
            continue
        end = index
        while end < len(lines) and not lines[end].strip("\r\n \t"):
            end += 1
        if output and end < len(lines):
            previous_kind = _code_line_kind(output[-1])
            next_kind = _code_line_kind(lines[end])
            surrounding = _nearby_code_kinds(lines, end, 1) + _nearby_code_kinds(lines, index, -1)
            if (previous_kind and next_kind and len(surrounding) >= 3
                    and not (previous_kind == "assignment" and next_kind == "decorator")):
                index = end
                continue
        output.extend(lines[index:end])
        index = end
    return "".join(output)


def _normalize_outside_fences(text: str) -> str:
    return _normalize_unfenced_code(_collapse_blank_lines(text))


def normalize_response_text(text: str) -> str:
    """Collapse excessive blank lines outside fenced Markdown code blocks.

    Fence lines and all content between a matching opening and closing fence
    are copied unchanged. This function intentionally operates on a complete
    response, so fences and newline runs split across provider chunks are
    handled together.
    """
    output: list[str] = []
    outside: list[str] = []
    fence: tuple[str, int] | None = None
    closed_fence = False

    for line in text.splitlines(keepends=True):
        if fence is None:
            marker = _fence_marker(line)
            if marker is None:
                outside.append(line)
                continue
            outside_text = _normalize_outside_fences("".join(outside))
            output.append(_compact_after_fence(outside_text) if closed_fence else outside_text)
            outside.clear()
            output.append(line)
            fence = marker
            closed_fence = False
        else:
            output.append(line)
            if _is_closing_fence(line, fence):
                fence = None
                closed_fence = True

    if outside:
        outside_text = _normalize_outside_fences("".join(outside))
        output.append(_compact_after_fence(outside_text) if closed_fence else outside_text)
    return "".join(output)
