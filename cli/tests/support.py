"""Shared helpers for CLI output assertions.

Rich styles and wraps CLI output when it detects a CI environment
(GITHUB_ACTIONS forces a color terminal): the option highlighter splits
``--force`` into two styled spans (``-`` + ``-force``), and panel wrapping
can break any phrase — or even a long token — across box-drawn lines. A
naive substring assertion on ``result.output`` therefore passes locally and
fails in CI. Assert against :func:`plain` output instead.
"""

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_BOX = re.compile(r"[│╭╮╰╯─┄]")


def plain(output: str) -> str:
    """Style-stripped, wrap-collapsed text for substring assertions."""
    text = _ANSI.sub("", output)
    text = _BOX.sub(" ", text)
    return re.sub(r"\s+", " ", text)
