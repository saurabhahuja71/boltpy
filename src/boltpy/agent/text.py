"""Helpers for preserving code while tidying model response whitespace."""
from __future__ import annotations

import re


_FENCE_LINE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<tail>[^\r\n]*)(?:\r?\n)?$")
_EXCESSIVE_BLANK_LINES = re.compile(r"(?:[ \t]*\r?\n){3,}")
_LEADING_BLANK_LINES = re.compile(r"^(?:[ \t]*\r?\n){2,}")


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
            outside_text = _collapse_blank_lines("".join(outside))
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
        outside_text = _collapse_blank_lines("".join(outside))
        output.append(_compact_after_fence(outside_text) if closed_fence else outside_text)
    return "".join(output)
