#!/usr/bin/env python3
"""Validate the AI review record for selected Java/Python contract surfaces.

The gate does not define a schema and does not invoke an LLM. A reviewer first
uses ``contract_sync_snapshot.py`` as source-derived evidence, then records a
PASS / REVIEW / FAIL decision. This script makes that review freshness and
coverage enforceable: any source-derived snapshot change invalidates the old
record until an AI reviewer has examined it again.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

try:
    from .contract_sync_snapshot import (
        AGENT_COMMAND_SURFACES,
        DEFAULT_JAVA_PROTOCOL_ROOT,
        PHASE_ZERO_SURFACES,
        render_snapshot,
    )
except ImportError:  # Direct ``python scripts/...`` execution.
    from contract_sync_snapshot import (  # type: ignore[no-redef]
        AGENT_COMMAND_SURFACES,
        DEFAULT_JAVA_PROTOCOL_ROOT,
        PHASE_ZERO_SURFACES,
        render_snapshot,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_PATH = PROJECT_ROOT / "docs/contract-review/phase-zero-baseline.md"
REVIEW_HASH_PATTERN = re.compile(r"^Snapshot-SHA256:\s*`?([0-9a-f]{64})`?\s*$", re.MULTILINE)
REVIEW_ROW_PATTERN = re.compile(
    r"^\|\s*(?P<surface>[^|]+?)\s*\|\s*(?P<verdict>PASS|REVIEW|FAIL)\s*\|\s*(?P<note>[^|]+?)\s*\|\s*$",
    re.MULTILINE,
)

REVIEW_SURFACES = tuple(surface.name for surface in PHASE_ZERO_SURFACES) + tuple(
    surface.name for surface in AGENT_COMMAND_SURFACES
) + (
    "AgentCommandCatalog",
    "DeviceValueTypeEnum",
    "Python protocol public API boundary",
)

# A typed HydroRiskAlert mirror is deliberately deferred. The review record
# must explain that exception; any other REVIEW remains a blocking verdict.
ALLOWED_REVIEW_SURFACES = frozenset({"HydroEventReportRequest"})


def snapshot_sha256(snapshot: str) -> str:
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()


def parse_review_record(source: str) -> tuple[str, Dict[str, tuple[str, str]]]:
    hash_match = REVIEW_HASH_PATTERN.search(source)
    if hash_match is None:
        raise ValueError("review record is missing Snapshot-SHA256")

    verdicts: Dict[str, tuple[str, str]] = {}
    for match in REVIEW_ROW_PATTERN.finditer(source):
        surface = match.group("surface").strip()
        if surface in verdicts:
            raise ValueError(f"review record contains duplicate surface: {surface}")
        verdicts[surface] = (match.group("verdict"), match.group("note").strip())
    return hash_match.group(1), verdicts


def validate_review_record(
    snapshot: str,
    review_source: str,
    required_surfaces: Iterable[str] = REVIEW_SURFACES,
) -> list[str]:
    errors: list[str] = []
    try:
        recorded_hash, verdicts = parse_review_record(review_source)
    except ValueError as error:
        return [str(error)]

    current_hash = snapshot_sha256(snapshot)
    if recorded_hash != current_hash:
        errors.append(
            "review record is stale: Snapshot-SHA256 does not match the current source-derived snapshot"
        )

    for surface in required_surfaces:
        verdict = verdicts.get(surface)
        if verdict is None:
            errors.append(f"review record is missing verdict for {surface}")
            continue
        status, note = verdict
        if not note:
            errors.append(f"review record has no evidence note for {surface}")
        if status == "FAIL":
            errors.append(f"AI review failed: {surface}")
        if status == "REVIEW" and surface not in ALLOWED_REVIEW_SURFACES:
            errors.append(f"AI review requires follow-up before merge: {surface}")
    return errors


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--java-protocol-root",
        type=Path,
        default=DEFAULT_JAVA_PROTOCOL_ROOT,
        help="Path to the Java hydros-agent-protocol module.",
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=DEFAULT_REVIEW_PATH,
        help="Tracked AI review record for the selected contract surfaces.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.review.is_file():
        print(f"contract AI review gate failed: review record not found: {args.review}", file=sys.stderr)
        return 1
    try:
        snapshot = render_snapshot(args.java_protocol_root, PHASE_ZERO_SURFACES)
    except (FileNotFoundError, SyntaxError, ValueError) as error:
        print(f"contract AI review gate failed: snapshot generation failed: {error}", file=sys.stderr)
        return 1

    errors = validate_review_record(snapshot, args.review.read_text(encoding="utf-8"))
    if errors:
        for error in errors:
            print(f"contract AI review gate failed: {error}", file=sys.stderr)
        return 1
    print("contract AI review gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
