from scripts.contract_ai_review_gate import REVIEW_SURFACES, snapshot_sha256, validate_review_record


def make_review(snapshot: str, overrides=None) -> str:
    overrides = overrides or {}
    rows = []
    for surface in REVIEW_SURFACES:
        verdict, note = overrides.get(surface, ("PASS", "source fields and wire semantics reviewed"))
        rows.append(f"| {surface} | {verdict} | {note} |")
    return "\n".join(
        [
            "# Review",
            "",
            f"Snapshot-SHA256: `{snapshot_sha256(snapshot)}`",
            "",
            "| Surface | Verdict | Evidence |",
            "| --- | --- | --- |",
            *rows,
        ]
    )


def test_gate_accepts_a_fresh_complete_review_record():
    snapshot = "current snapshot"
    review = make_review(
        snapshot,
        {"HydroEventReportRequest": ("REVIEW", "nested HydroRiskAlert remains tracked")},
    )

    assert validate_review_record(snapshot, review) == []


def test_gate_rejects_stale_or_unapproved_review():
    snapshot = "current snapshot"
    stale = make_review("old snapshot")
    blocked = make_review(snapshot, {"AgentCommand": ("REVIEW", "needs review")})

    assert "review record is stale" in validate_review_record(snapshot, stale)[0]
    assert "AI review requires follow-up before merge: AgentCommand" in validate_review_record(
        snapshot, blocked
    )
