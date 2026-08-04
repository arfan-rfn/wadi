"""Line splitting for the source route — no infrastructure, pure function.

Every ICFG anchor is a COMPILER line number. If this route counts lines any
other way, the source panel highlights the wrong region while printing line
numbers that look right, which is the least detectable kind of wrong.
"""

from wadi_orchestrator.app import source_lines


class TestSourceLines:
    def test_splits_on_newlines_and_keeps_terminators(self) -> None:
        assert source_lines("a\nb\nc\n") == ["a\n", "b\n", "c\n"]

    def test_a_file_with_no_trailing_newline_keeps_its_last_line(self) -> None:
        assert source_lines("a\nb") == ["a\n", "b"]

    def test_empty_content_is_no_lines(self) -> None:
        assert source_lines("") == []

    def test_crlf_counts_as_one_line(self) -> None:
        # \r stays in the content (it is part of the analyzed text) but does
        # not start a line of its own.
        assert source_lines("a\r\nb\r\n") == ["a\r\n", "b\r\n"]

    def test_form_feed_and_friends_do_not_start_a_line(self) -> None:
        """`str.splitlines` breaks on \\f, \\v, \\x1c-\\x1e, \\x85 and U+2028.

        Java, JavaScript and Go do not. One form feed in a file was enough to
        shift every line after it by one against the ICFG's anchors — the
        highlight moved, silently, and the gutter still agreed with itself.
        """
        # Escaped, not literal: ruff rightly refuses invisible separators in
        # source, and these are exactly the characters that look like nothing.
        for separator in ("\f", "\v", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            content = f"line one{separator}still line one\nline two\n"
            assert len("".join(content).splitlines()) == 3, "precondition: Python would split"
            assert source_lines(content) == [
                f"line one{separator}still line one\n",
                "line two\n",
            ], f"{separator!r} must not terminate a line"

    def test_a_form_feed_does_not_shift_later_line_numbers(self) -> None:
        # The regression in one assertion: line 3 must still be line 3.
        content = "a\nb\fb2\nc\nd\n"
        assert source_lines(content)[2] == "c\n"
