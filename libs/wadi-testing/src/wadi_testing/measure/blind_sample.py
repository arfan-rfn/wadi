"""A blind hand check of entity access, drawn and scored from the repository (§5.2.17).

    uv run python -m wadi_testing.measure.blind_sample draw --snapshot <id> \\
        --seed <int> --size <N> --corpus <root> [--api <url>] [--out-dir <dir>]
    uv run python -m wadi_testing.measure.blind_sample score \\
        --key key.json --labels labels.json [--json score.json]

Reviews D3 to D5 found the first hand check unable to support its claim: the
reader was handed wadi's answers, the sample was stratified by wadi's own
output with no seed behind it, and nothing that drew or scored it was in the
repository. This module is the replacement.

**The draw.** Every endpoint of the snapshot, sorted by id so the draw does
not depend on the order the API lists them, is the population; predating and
empty endpoints are in it. ``random.Random(seed).sample`` takes N of them: the
``random`` stratum, a simple random sample. Every other endpoint whose summary
has two or more entity rows or three or more call sites is added as the
``hard`` stratum, which is therefore every hard endpoint the random draw did
not already take. ``blind.json`` holds what a reader needs to find each
handler: service, method, route, handler class and method, and the handler's
file relative to the corpus root with its line (the ICFG root entry's anchor;
a staged library path is mapped back to the library, §5.2.14). It holds
nothing wadi concluded and not the stratum, and its rows are sorted by
service and route under sample ids (``b001``...), so neither a field nor the
order tells a reader which endpoints wadi found hard. ``key.json`` maps each
sample id to its endpoint id, stratum and wadi's ``entity_access``, with the
seed, N, snapshot and draw time.

**The labels.** ``labels.json`` maps a sample id (or an endpoint id) to the
accesses the reader found in source alone: ``[{"entity": "Order",
"operations": ["read", "update"]}]``, an entity as a simple or qualified class
name and operations from create, read, update and delete. ``[]`` means the
reader found none.

**Scoring rules.** Each true entity is paired with wadi's row of the same
entity: a qualified label matches the qualified name, a simple one the simple
name, and a simple name two of wadi's rows share is refused as ambiguous.
Within a pair, each true operation is

* *exact* when wadi lists it;
* *less specific* when it is create or update and wadi lists
  ``create-or-update``, which is consistent with it and weaker;
* *withheld* when wadi lists ``unknown``;
* a *miss* otherwise;

and each operation wadi lists is an *over-claim* when it is a verb the truth
lacks (``create-or-update`` where the truth has neither create nor update).
``unknown`` claims no verb. A true entity with no named row is withheld when
wadi has an undetermined-entity row whose operations cover each true one
(``unknown`` covers anything), and a miss otherwise. A row for an entity the
truth does not touch is an over-claim whatever it lists. The undetermined row
is an over-claim for any verb no true access of the endpoint has; a row that
restates accesses already paired is withheld.

Each (endpoint, entity) pair gets one verdict, the worst it shows:
over-claim, then miss, then withheld, then less specific, then exact. An
endpoint is in **full agreement** when every pair is exact (no pair at all
when both sides found nothing), and has an **error** when any pair is an
over-claim or a miss; withheld and less specific are honest gaps, not
errors. For each stratum the report gives the endpoints scored, those in
full agreement, those with an error, the pair counts per verdict, and a
one-sided 95% Clopper-Pearson upper bound on the endpoint error rate. Only
the random stratum's bound speaks for the population; the hard stratum is
every such endpoint the draw had left, so its count is the census of that
set. A predating endpoint (wadi's answer None) is not scored; an unlabeled
endpoint or a label for no drawn endpoint makes the command exit 1.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from wadi_contracts import (
    EndpointEntityAccess,
    EndpointSummary,
    EntityOperation,
    Icfg,
    ServiceKind,
    ServiceSummary,
)

DEFAULT_API = "http://127.0.0.1:9234/api/v1"
BLIND_FORMAT = "1"
KEY_FORMAT = "1"
#: Where §5.2.14 stages a library inside a dependent's parse root.
STAGED_LIBRARY_PREFIX = "wadi-libs/"
_LIBRARY_SOURCE_ROOT = "src/main/java/"

#: How a reader writes one access; the blind file says so, and nothing else.
LABELS_FORMAT = (
    'labels.json: {"<id>": [{"entity": "<simple or qualified class>", '
    '"operations": ["create" | "read" | "update" | "delete", ...]}, ...]}; '
    "[] when the endpoint touches no entity. Read the source only."
)


class Stratum(StrEnum):
    RANDOM = "random"
    HARD = "hard"


class TrueOperation(StrEnum):
    """What a reader may label: the four verbs, never wadi's hedges."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


class PairVerdict(StrEnum):
    """One (endpoint, entity) pair's verdict, declared worst first."""

    OVER_CLAIM = "over-claim"
    MISS = "miss"
    WITHHELD = "withheld"
    LESS_SPECIFIC = "less-specific"
    EXACT = "exact"


_SEVERITY = list(PairVerdict)
_ERRORS = frozenset({PairVerdict.OVER_CLAIM, PairVerdict.MISS})
_VERBS = {op.value: op for op in TrueOperation}
_SPLIT = frozenset({TrueOperation.CREATE, TrueOperation.UPDATE})


class LabelError(ValueError):
    """A labels file the scorer cannot read without guessing."""


# --- the draw -------------------------------------------------------------------------


@dataclass(frozen=True)
class Draw:
    blind: dict[str, Any]
    key: dict[str, Any]


def is_hard(endpoint: EndpointSummary) -> bool:
    """Two or more entity rows, or three or more call sites (review D4)."""
    rows = endpoint.entity_access or []
    return len(rows) >= 2 or sum(row.call_sites for row in rows) >= 3


def draw(
    client: httpx.Client,
    snapshot_id: str,
    *,
    seed: int,
    size: int,
    corpus: Path,
    now: datetime | None = None,
) -> Draw:
    """Draw the sample from the orchestrator at ``client``'s base URL."""
    services = TypeAdapter(list[ServiceSummary]).validate_python(
        _get(client, f"/snapshots/{snapshot_id}/services")
    )
    population: list[tuple[ServiceSummary, EndpointSummary]] = []
    for service in services:
        rows = TypeAdapter(list[EndpointSummary]).validate_python(
            _get(client, f"/snapshots/{snapshot_id}/services/{service.service_id}/endpoints")
        )
        population.extend((service, endpoint) for endpoint in rows)
    population.sort(key=lambda pair: pair[1].id)
    if size > len(population):
        raise ValueError(
            f"a sample of {size} from a snapshot of {len(population)} endpoints "
            "is not a sample; ask for fewer"
        )
    drawn = random.Random(seed).sample(population, size)
    drawn_ids = {endpoint.id for _, endpoint in drawn}
    hard = [pair for pair in population if is_hard(pair[1]) and pair[1].id not in drawn_ids]
    strata = [(pair, Stratum.RANDOM) for pair in drawn] + [(pair, Stratum.HARD) for pair in hard]
    strata.sort(key=lambda item: (item[0][0].name, item[0][1].full_uri, item[0][1].http_method))
    libraries = [service for service in services if service.kind is ServiceKind.LIBRARY]

    blind_rows: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for number, ((service, endpoint), stratum) in enumerate(strata, start=1):
        sample_id = f"b{number:03d}"
        handler_class, handler_method = _handler(endpoint.handler.signature)
        anchor = _root_anchor(client, snapshot_id, endpoint.id)
        blind_rows.append(
            {
                "id": sample_id,
                "service": service.name,
                "http_method": endpoint.http_method.value,
                "full_uri": endpoint.full_uri,
                "handler_class": handler_class,
                "handler_method": handler_method,
                "source_file": (
                    _locate(anchor[0], service, libraries, corpus) if anchor is not None else None
                ),
                "line": anchor[1] if anchor is not None else None,
            }
        )
        key_rows.append(
            {
                "id": sample_id,
                "endpoint_id": endpoint.id,
                "stratum": stratum.value,
                "service": service.name,
                "http_method": endpoint.http_method.value,
                "full_uri": endpoint.full_uri,
                "entity_access": (
                    None
                    if endpoint.entity_access is None
                    else [row.model_dump(mode="json") for row in endpoint.entity_access]
                ),
            }
        )
    return Draw(
        blind={"blind_format": BLIND_FORMAT, "labels": LABELS_FORMAT, "endpoints": blind_rows},
        key={
            "key_format": KEY_FORMAT,
            "snapshot_id": snapshot_id,
            "seed": seed,
            "size": size,
            "drawn_at": (now or datetime.now(UTC)).isoformat(),
            "api": str(client.base_url),
            "population": len(population),
            "hard_population": sum(is_hard(endpoint) for _, endpoint in population),
            "endpoints": key_rows,
        },
    )


def _get(client: httpx.Client, path: str) -> Any:
    """GET ``path`` under the client's base URL (httpx appends a relative path to it)."""
    response = client.get(path.lstrip("/"))
    response.raise_for_status()
    return response.json()


def _root_anchor(
    client: httpx.Client, snapshot_id: str, endpoint_id: str
) -> tuple[str, int] | None:
    """(file, line) of the handler: its ICFG's root entry, which the detail view lacks."""
    response = client.get(f"snapshots/{snapshot_id}/endpoints/{endpoint_id}/icfg")
    if response.status_code == 404:
        return None  # an endpoint with no flow graph; the reader has the class
    response.raise_for_status()
    anchor = Icfg.model_validate(response.json()).root_entry().anchor
    return anchor.file, anchor.start_line


def _handler(signature: str) -> tuple[str, str]:
    """`com.acme.OrderController.show:Order(String)` -> (`com.acme.OrderController`, `show`)."""
    qualified = signature.split(":", 1)[0].split("(", 1)[0]
    owner, _, method = qualified.rpartition(".")
    return owner, method


def _locate(
    file: str, service: ServiceSummary, libraries: Sequence[ServiceSummary], corpus: Path
) -> str | None:
    """The anchor's file relative to the corpus root, when it is a file there."""
    candidates: list[Path] = []
    if file.startswith(STAGED_LIBRARY_PREFIX):
        index = file.find(_LIBRARY_SOURCE_ROOT)
        if index < 0:
            return None
        in_library = file[index:]
        for library in libraries:
            candidates.append(Path(library.repo) / library.build_root / in_library)
            candidates.append(corpus / library.build_root / in_library)
    else:
        candidates.append(Path(service.repo) / service.build_root / file)
        # A repo recorded as a URL: the corpus root is its checkout.
        candidates.append(corpus / service.build_root / file)
    root = corpus.resolve()
    for candidate in candidates:
        try:
            relative = candidate.resolve().relative_to(root)
        except ValueError:
            continue
        if (root / relative).is_file():
            return relative.as_posix()
    return None


# --- the score ------------------------------------------------------------------------


class _KeyEndpoint(BaseModel):
    id: str
    endpoint_id: str
    stratum: Stratum
    service: str
    http_method: str
    full_uri: str
    entity_access: list[EndpointEntityAccess] | None


class _Key(BaseModel):
    key_format: str
    snapshot_id: str
    seed: int
    size: int
    drawn_at: str
    api: str
    population: int
    hard_population: int
    endpoints: list[_KeyEndpoint]


class _Label(BaseModel):
    entity: str = Field(min_length=1)
    operations: list[TrueOperation] = Field(min_length=1)


_LABELS = TypeAdapter(dict[str, list[_Label]])


@dataclass(frozen=True)
class PairScore:
    """One (endpoint, entity) pair: the truth's label or wadi's name, and its verdict."""

    entity: str | None
    wadi_entity: str | None
    verdict: PairVerdict
    true_operations: list[str]
    wadi_operations: list[str]
    #: Per operation, what it was: exact, less-specific, withheld, miss, over-claim.
    detail: dict[str, str]


@dataclass(frozen=True)
class EndpointScore:
    id: str
    endpoint_id: str
    stratum: Stratum
    service: str
    http_method: str
    full_uri: str
    pairs: list[PairScore]

    @property
    def full_agreement(self) -> bool:
        return all(pair.verdict is PairVerdict.EXACT for pair in self.pairs)

    @property
    def error(self) -> bool:
        return any(pair.verdict in _ERRORS for pair in self.pairs)


@dataclass(frozen=True)
class StratumScore:
    endpoints: int
    full_agreement: int
    errors: int
    pairs: dict[PairVerdict, int]
    error_rate_upper_95: float | None


@dataclass(frozen=True)
class ScoreReport:
    strata: dict[Stratum, StratumScore]
    endpoints: list[EndpointScore]
    predating: list[str] = field(default_factory=list[str])
    unlabeled: list[str] = field(default_factory=list[str])
    unknown_labels: list[str] = field(default_factory=list[str])


def score(key_document: Mapping[str, Any], labels_document: Mapping[str, Any]) -> ScoreReport:
    """Score a reader's labels against the key (rules in the module docstring)."""
    key = _Key.model_validate(dict(key_document))
    try:
        labels = _LABELS.validate_python(labels_document)
    except ValidationError as error:
        raise LabelError(f"labels.json does not follow the format: {error}") from error
    known = {e.id for e in key.endpoints} | {e.endpoint_id for e in key.endpoints}
    scored: list[EndpointScore] = []
    predating: list[str] = []
    unlabeled: list[str] = []
    for endpoint in key.endpoints:
        if endpoint.entity_access is None:
            predating.append(endpoint.id)
            continue
        truth = labels.get(endpoint.id, labels.get(endpoint.endpoint_id))
        if truth is None:
            unlabeled.append(endpoint.id)
            continue
        scored.append(
            EndpointScore(
                id=endpoint.id,
                endpoint_id=endpoint.endpoint_id,
                stratum=endpoint.stratum,
                service=endpoint.service,
                http_method=endpoint.http_method,
                full_uri=endpoint.full_uri,
                pairs=_score_endpoint(endpoint.id, endpoint.entity_access, truth),
            )
        )
    return ScoreReport(
        strata={stratum: _stratum(scored, stratum) for stratum in Stratum},
        endpoints=scored,
        predating=predating,
        unlabeled=unlabeled,
        unknown_labels=sorted(set(labels) - known),
    )


def clopper_pearson_upper(errors: int, n: int, confidence: float = 0.95) -> float | None:
    """One-sided upper confidence bound on a rate seen as ``errors`` in ``n``.

    The p at which seeing ``errors`` or fewer has probability 1 - confidence,
    found by bisection on the binomial distribution; None when n is 0.
    """
    if n == 0:
        return None
    if errors >= n:
        return 1.0
    alpha = 1 - confidence
    low, high = 0.0, 1.0
    for _ in range(100):
        middle = (low + high) / 2
        if _binomial_cdf(errors, n, middle) > alpha:
            low = middle
        else:
            high = middle
    return high


def _binomial_cdf(errors: int, n: int, p: float) -> float:
    """P(X <= errors) for X ~ Binomial(n, p), summed in log space."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    log_p, log_q = math.log(p), math.log1p(-p)
    return sum(
        math.exp(
            math.lgamma(n + 1)
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
            + k * log_p
            + (n - k) * log_q
        )
        for k in range(errors + 1)
    )


def _stratum(scored: Sequence[EndpointScore], stratum: Stratum) -> StratumScore:
    members = [endpoint for endpoint in scored if endpoint.stratum is stratum]
    verdicts = Counter(pair.verdict for endpoint in members for pair in endpoint.pairs)
    errors = sum(endpoint.error for endpoint in members)
    return StratumScore(
        endpoints=len(members),
        full_agreement=sum(endpoint.full_agreement for endpoint in members),
        errors=errors,
        pairs={verdict: verdicts[verdict] for verdict in PairVerdict},
        error_rate_upper_95=clopper_pearson_upper(errors, len(members)),
    )


def _score_endpoint(
    sample_id: str, rows: Sequence[EndpointEntityAccess], labels: Sequence[_Label]
) -> list[PairScore]:
    truth: dict[str, set[TrueOperation]] = {}
    for label in labels:
        truth.setdefault(label.entity, set()).update(label.operations)
    named = [row for row in rows if row.entity is not None]
    undetermined = {op for row in rows if row.entity is None for op in row.operations}
    has_undetermined = any(row.entity is None for row in rows)
    pairs: list[PairScore] = []
    paired: set[int] = set()
    unpaired: list[tuple[str, set[TrueOperation]]] = []
    for entity, operations in truth.items():
        matches = [
            index
            for index, row in enumerate(named)
            if row.entity is not None and _same_entity(entity, row.entity)
        ]
        if len(matches) > 1:
            names = ", ".join(str(named[index].entity) for index in matches)
            raise LabelError(
                f"{sample_id}: label {entity!r} is ambiguous between {names}; qualify it"
            )
        if matches:
            paired.add(matches[0])
            row = named[matches[0]]
            pairs.append(_pair(entity, row.entity, operations, set(row.operations)))
        else:
            unpaired.append((entity, operations))
    for entity, operations in unpaired:
        if has_undetermined:
            pairs.append(_pair(entity, None, operations, undetermined, entity_known=False))
        else:
            pairs.append(_pair(entity, None, operations, set()))
    for index, row in enumerate(named):
        if index not in paired:
            wadi = [op.value for op in row.operations]
            pairs.append(
                PairScore(
                    entity=row.entity,
                    wadi_entity=row.entity,
                    verdict=PairVerdict.OVER_CLAIM,
                    true_operations=[],
                    wadi_operations=wadi,
                    detail=dict.fromkeys(wadi, PairVerdict.OVER_CLAIM.value),
                )
            )
    if has_undetermined:
        every_true = {op for operations in truth.values() for op in operations}
        over = sorted(op.value for op in undetermined if _over_claims(op, every_true))
        if over or not unpaired:
            pairs.append(
                PairScore(
                    entity=None,
                    wadi_entity=None,
                    verdict=PairVerdict.OVER_CLAIM if over else PairVerdict.WITHHELD,
                    true_operations=[],
                    wadi_operations=sorted(op.value for op in undetermined),
                    detail=dict.fromkeys(over, PairVerdict.OVER_CLAIM.value),
                )
            )
    return pairs


def _pair(
    entity: str,
    wadi_entity: str | None,
    truth: set[TrueOperation],
    wadi: set[EntityOperation],
    *,
    entity_known: bool = True,
) -> PairScore:
    """One true entity against the wadi operations that cover it.

    ``entity_known=False`` is the undetermined row standing in for it: what it
    covers is withheld rather than exact, and its over-claims are counted on
    its own pair.
    """
    detail: dict[str, PairVerdict] = {}
    for operation in sorted(truth):
        if EntityOperation(operation.value) in wadi:
            found = PairVerdict.EXACT if entity_known else PairVerdict.WITHHELD
        elif operation in _SPLIT and EntityOperation.CREATE_OR_UPDATE in wadi:
            found = PairVerdict.LESS_SPECIFIC if entity_known else PairVerdict.WITHHELD
        elif EntityOperation.UNKNOWN in wadi:
            found = PairVerdict.WITHHELD
        else:
            found = PairVerdict.MISS
        detail[operation.value] = found
    if entity_known:
        for claimed in wadi:
            if _over_claims(claimed, truth):
                detail[claimed.value] = PairVerdict.OVER_CLAIM
    verdict = min(detail.values(), key=_SEVERITY.index) if detail else PairVerdict.MISS
    return PairScore(
        entity=entity,
        wadi_entity=wadi_entity,
        verdict=verdict,
        true_operations=sorted(op.value for op in truth),
        wadi_operations=sorted(op.value for op in wadi),
        detail={operation: found.value for operation, found in detail.items()},
    )


def _over_claims(claimed: EntityOperation, truth: set[TrueOperation]) -> bool:
    """Whether a verb wadi lists is one the truth does not have."""
    if claimed is EntityOperation.UNKNOWN:
        return False
    if claimed is EntityOperation.CREATE_OR_UPDATE:
        return not (truth & _SPLIT)
    return _VERBS[claimed.value] not in truth


def _same_entity(label: str, entity: str) -> bool:
    entity = entity.replace("$", ".")
    if "." in label:
        return label.replace("$", ".") == entity
    return label == entity.rsplit(".", 1)[-1]


def to_json(report: ScoreReport, key: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "key": {name: key.get(name) for name in ("snapshot_id", "seed", "size", "drawn_at")},
        "strata": {
            stratum.value: {
                "endpoints": result.endpoints,
                "full_agreement": result.full_agreement,
                "errors": result.errors,
                "pairs": {verdict.value: count for verdict, count in result.pairs.items()},
                "error_rate_upper_95": result.error_rate_upper_95,
            }
            for stratum, result in report.strata.items()
        },
        "endpoints": [
            {
                "id": endpoint.id,
                "endpoint_id": endpoint.endpoint_id,
                "stratum": endpoint.stratum.value,
                "service": endpoint.service,
                "http_method": endpoint.http_method,
                "full_uri": endpoint.full_uri,
                "full_agreement": endpoint.full_agreement,
                "error": endpoint.error,
                "pairs": [
                    {
                        "entity": pair.entity,
                        "wadi_entity": pair.wadi_entity,
                        "verdict": pair.verdict.value,
                        "true_operations": pair.true_operations,
                        "wadi_operations": pair.wadi_operations,
                        "detail": pair.detail,
                    }
                    for pair in endpoint.pairs
                ],
            }
            for endpoint in report.endpoints
        ],
        "predating": report.predating,
        "unlabeled": report.unlabeled,
        "unknown_labels": report.unknown_labels,
    }


# --- the command ----------------------------------------------------------------------


def main(argv: Sequence[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wadi_testing.measure.blind_sample",
        description="Draw a blind entity-access hand check, or score a reader's labels.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    drawing = commands.add_parser("draw", help="draw the sample: writes blind.json and key.json")
    drawing.add_argument(
        "--api", default=DEFAULT_API, help=f"orchestrator API (default {DEFAULT_API})"
    )
    drawing.add_argument("--snapshot", required=True)
    drawing.add_argument("--seed", type=int, required=True)
    drawing.add_argument("--size", type=int, required=True, help="N, the simple random sample")
    drawing.add_argument("--corpus", type=Path, required=True, help="the analyzed source root")
    drawing.add_argument("--out-dir", type=Path, default=Path())
    scoring = commands.add_parser("score", help="score labels.json against key.json")
    scoring.add_argument("--key", type=Path, required=True)
    scoring.add_argument("--labels", type=Path, required=True)
    scoring.add_argument("--json", type=Path, help="write the full report here")
    args = parser.parse_args(argv)

    if args.command == "draw":
        corpus: Path = args.corpus
        if not corpus.is_dir():
            parser.error(f"not a directory: {corpus}")
        with httpx.Client(base_url=args.api, transport=transport, timeout=120) as client:
            try:
                result = draw(client, args.snapshot, seed=args.seed, size=args.size, corpus=corpus)
            except ValueError as error:
                parser.error(str(error))
        out: Path = args.out_dir
        out.mkdir(parents=True, exist_ok=True)
        (out / "blind.json").write_text(json.dumps(result.blind, indent=2) + "\n")
        (out / "key.json").write_text(json.dumps(result.key, indent=2) + "\n")
        strata = Counter(row["stratum"] for row in result.key["endpoints"])
        unlocated = sum(row["source_file"] is None for row in result.blind["endpoints"])
        print(
            f"drew random {strata[Stratum.RANDOM.value]} + hard {strata[Stratum.HARD.value]}"
            f" of {result.key['population']} endpoints"
            f" (hard population {result.key['hard_population']})"
        )
        if unlocated:
            print(f"{unlocated} handler file(s) not found under {corpus}: the reader has the class")
        print(f"wrote {out / 'blind.json'} (give the reader this) and {out / 'key.json'}")
        return 0

    key_document = json.loads(Path(args.key).read_text())
    try:
        report = score(key_document, json.loads(Path(args.labels).read_text()))
    except LabelError as error:
        print(f"labels refused: {error}")
        return 1
    for stratum, result in report.strata.items():
        bound = result.error_rate_upper_95
        print(
            f"{stratum.value}: {result.endpoints} endpoints, {result.full_agreement} in full"
            f" agreement, {result.errors} with an error"
            + (f", error rate <= {bound:.1%} (95%, one-sided)" if bound is not None else "")
        )
        print(
            "  pairs: "
            + "   ".join(f"{verdict.value} {count}" for verdict, count in result.pairs.items())
        )
    for endpoint in report.endpoints:
        if endpoint.error:
            pairs = ", ".join(
                f"{p.entity or 'undetermined'} {p.verdict.value}" for p in endpoint.pairs
            )
            print(f"  error {endpoint.id} {endpoint.http_method} {endpoint.full_uri}: {pairs}")
    if report.predating:
        print(f"not scored, predating entity facts: {', '.join(report.predating)}")
    if report.unlabeled:
        print(f"unlabeled: {', '.join(report.unlabeled)}")
    if report.unknown_labels:
        print(f"labels for no drawn endpoint: {', '.join(report.unknown_labels)}")
    if args.json is not None:
        output: Path = args.json
        output.write_text(json.dumps(to_json(report, key_document), indent=2) + "\n")
        print(f"wrote {output}")
    return 1 if report.unlabeled or report.unknown_labels else 0


if __name__ == "__main__":
    sys.exit(main())
