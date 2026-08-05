"""§5.2.10: an independent second reading of the auth surface.

Every counter on ``AuthCoverageSection`` is derived from evidence the auth
layer *emitted*. That makes them structurally blind to the failure they exist
to catch: a construct dropped before emission contributes to none of them and
leaves its endpoint looking cleanly authenticated. It is how 365
train-ticket-aitest endpoints published ``authenticated=true`` with no roles
while the tracker read zero withheld.

This module is the other eye. It reads the SOURCE TEXT of the same tree the
extractor parsed and asks what the auth layer *should* have found, sharing no
code path with the CPG — no Joern, no tags, no pack vocabulary object. When
the two disagree, the disagreement is the finding.

It is deliberately dumb, and that is the design:

* **Regex over stripped text, not parsing.** A parser sophisticated enough to
  be right is sophisticated enough to fail the same way the pass did. The
  oracle's value is that it cannot be fooled by a chain shape, because it does
  not know what a chain is.
* **Over-counting is acceptable; under-counting is not.** A false gap costs a
  reader one look at a file. A missed gap is the thing that shipped.
* **Findings are facts, never errors** (P10). A gap says how far to trust the
  auth answer for that service; it never fails a snapshot.

The comparison is per FILE rather than per service, because a service with one
fully-read config and one wholly-unread one is exactly the case a service-wide
total would hide.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path

from wadi_contracts.boundary import AuthExtractionGap
from wadi_contracts.enums import AuthGapCode
from wadi_contracts.source import SourceAnchor
from wadi_joern_client.export import RulePatternConfidence, ServiceExport

logger = logging.getLogger(__name__)

#: Files this large are not hand-written security configs; skipping them keeps
#: a generated or vendored blob from dominating the count.
_MAX_FILE_BYTES = 512_000

#: Up to this many example sites per finding — examples, never the whole list.
_MAX_SAMPLES = 5

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")
#: A Java string literal, escapes included. Replaced by an empty literal rather
#: than removed so `access("hasRole('X')")` keeps its call parentheses — the
#: SITE is real even though the role text inside it must not be counted twice.
_STRING_LITERAL = re.compile(r'"(?:\\.|[^"\\])*"')

#: What marks a file as configuring authorization at all. Both the servlet and
#: the reactive stack, and both DSL eras — a file wadi cannot read is exactly
#: the file whose idiom it does not know, so this test must not depend on
#: knowing the idiom.
_SECURITY_CONFIG = re.compile(
    r"\b(?:"
    r"authorizeHttpRequests|authorizeRequests|authorizeExchange"
    r"|SecurityFilterChain|SecurityWebFilterChain|WebSecurityConfigurerAdapter"
    r")\b"
)

#: Reactive security, tracked apart so a whole stack cannot hide inside a
#: generic unresolved-scope number.
_REACTIVE = re.compile(r"\b(?:ServerHttpSecurity|authorizeExchange|pathMatchers|anyExchange)\b")

#: The access vocabulary, matched as a CALL on a receiver. Kept as literal text
#: rather than imported from the pack: a shared list would let one edit blind
#: both readers at once, which is precisely the coupling this module exists to
#: avoid.
_ACCESS_CALL = re.compile(
    r"\.\s*(?:"
    r"hasRole|hasAnyRole|hasAuthority|hasAnyAuthority"
    r"|authenticated|fullyAuthenticated|anonymous|rememberMe|hasIpAddress"
    r"|permitAll|denyAll|access"
    r")\s*\("
)


def _strip_noise(source: str) -> str:
    """Comments and string bodies out, line structure preserved.

    Newlines inside removed spans are kept so a finding's sample line number
    still points at the right line.
    """

    def _blank(match: re.Match[str]) -> str:
        return "\n" * match.group(0).count("\n")

    without_blocks = _BLOCK_COMMENT.sub(_blank, source)
    without_lines = _LINE_COMMENT.sub("", without_blocks)
    return _STRING_LITERAL.sub('""', without_lines)


def _access_sites(text: str) -> list[int]:
    """1-based line numbers of every access call in stripped text."""
    return [text.count("\n", 0, match.start()) + 1 for match in _ACCESS_CALL.finditer(text)]


def scan_auth_extraction(parse_root: Path, export: ServiceExport) -> list[AuthExtractionGap] | None:
    """Compare what the sources say about auth against what the export carried.

    ``parse_root`` is the staged tree the extractor actually handed Joern, not
    the repository — so a divergence is a *reading* failure and never a
    staging one, which keeps the finding actionable.

    Returns ``None`` only when the tree cannot be read at all; ``[]`` means
    checked and clean. The two are never conflated (P10).
    """
    if not parse_root.is_dir():
        return None

    emitted_sites_by_file: dict[str, set[int]] = defaultdict(set)
    unresolved_by_file: dict[str, list[int]] = defaultdict(list)
    for rule in export.security_rules:
        emitted_sites_by_file[rule.anchor.file].add(rule.call_id)
        if rule.pattern_confidence is RulePatternConfidence.NONE:
            unresolved_by_file[rule.anchor.file].append(max(rule.anchor.line, 1))

    unemitted: list[SourceAnchor] = []
    unemitted_total = 0
    unread_configs: list[SourceAnchor] = []
    reactive: list[SourceAnchor] = []
    worst: tuple[int, str] | None = None

    for path in sorted(parse_root.rglob("*.java")):
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - unreadable file is not a finding
            logger.warning("auth oracle could not read %s", path)
            continue
        if not _SECURITY_CONFIG.search(source):
            continue

        relative = path.relative_to(parse_root).as_posix()
        text = _strip_noise(source)
        lines = _access_sites(text)
        if not lines:
            continue

        emitted = len(emitted_sites_by_file.get(relative, ()))
        if emitted == 0:
            unread_configs.append(
                SourceAnchor(file=relative, start_line=lines[0], end_line=lines[0])
            )
        missing = len(lines) - emitted
        if missing > 0:
            unemitted_total += missing
            if worst is None or missing > worst[0]:
                worst = (missing, relative)
            # The LAST sites are the interesting ones: a chain reads top-down,
            # so what went unread is usually past the rules that parsed.
            for line in lines[-min(missing, _MAX_SAMPLES) :]:
                unemitted.append(SourceAnchor(file=relative, start_line=line, end_line=line))

        if _REACTIVE.search(source):
            reactive.append(SourceAnchor(file=relative, start_line=lines[0], end_line=lines[0]))

    gaps: list[AuthExtractionGap] = []
    if unemitted_total > 0:
        detail = f"source names {unemitted_total} more access call(s) than the export carried"
        if worst is not None:
            detail += f"; worst: {worst[1]} (+{worst[0]})"
        gaps.append(
            AuthExtractionGap(
                code=AuthGapCode.UNEMITTED_ACCESS_SITE,
                count=unemitted_total,
                sample_sites=unemitted[:_MAX_SAMPLES],
                detail=detail,
            )
        )
    if unread_configs:
        gaps.append(
            AuthExtractionGap(
                code=AuthGapCode.UNREAD_SECURITY_CONFIG,
                count=len(unread_configs),
                sample_sites=unread_configs[:_MAX_SAMPLES],
                detail="filter-chain configuration that produced no rules at all",
            )
        )
    if reactive:
        gaps.append(
            AuthExtractionGap(
                code=AuthGapCode.REACTIVE_CHAIN,
                count=len(reactive),
                sample_sites=reactive[:_MAX_SAMPLES],
                detail="reactive (WebFlux) security configuration present",
            )
        )
    unresolved_total = sum(len(lines) for lines in unresolved_by_file.values())
    if unresolved_total > 0:
        samples = [
            SourceAnchor(file=file, start_line=line, end_line=line)
            for file, lines in sorted(unresolved_by_file.items())
            for line in lines[:1]
        ]
        gaps.append(
            AuthExtractionGap(
                code=AuthGapCode.UNRESOLVED_SCOPE,
                count=unresolved_total,
                sample_sites=samples[:_MAX_SAMPLES],
                detail="rule sites emitted whose path could not be resolved",
            )
        )
    return gaps
