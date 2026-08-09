"""Fail-closed strict-k disclosure for the versioned v2 latent trace."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .v2_config import K_VALUES, RELEASES, canonical_json_sha256

ACTION_FIELDS = {"record_type", "action_id", "eligible_id", "action_type", "day", "within_day_tick", "global_order"}
CHECKPOINT_COMMON_FIELDS = {"record_type", "checkpoint_id", "release", "day", "within_day_tick", "global_order", "rate"}
CHECKPOINT_TOTAL_FIELDS = CHECKPOINT_COMMON_FIELDS | {"checkpoint_assets", "checkpoint_shares"}
CHECKPOINT_RATE_ONLY_FIELDS = CHECKPOINT_COMMON_FIELDS
FORBIDDEN_TRUTH_FIELDS = {
    "assets", "shares", "position_before", "position_after", "full_withdraw", "profile_log_shares", "residual_log",
    "aggregate_shares_after", "aggregate_assets_after", "activation_event", "withdrawal_reselected", "withdrawal_converted",
}


@dataclass(frozen=True)
class Window:
    index: int
    k: int
    previous_checkpoint_day: int
    end_day: int
    event: bool
    events: tuple[dict[str, Any], ...]

    @property
    def participant_count(self) -> int:
        return len({item["eligible_id"] for item in self.events})

    @property
    def action_count(self) -> int:
        return len(self.events)

    @property
    def duration_days(self) -> int:
        return self.end_day - self.previous_checkpoint_day


@dataclass(frozen=True)
class StrictKPartition:
    k: int
    completed: tuple[Window, ...]
    censored: Window


def _ordered(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(events, key=lambda item: (int(item["day"]), int(item["within_day_tick"]), int(item["global_order"]), str(item["action_id"])))
    ids = [item["action_id"] for item in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("v2 actions require unique stable IDs")
    return ordered


def partition_strict_k(events: Iterable[dict[str, Any]], *, days: int, k: int) -> StrictKPartition:
    """Release directly after the action adding the kth distinct identifier."""

    if k not in K_VALUES:
        raise ValueError(f"k must be in {K_VALUES}")
    if days <= 0:
        raise ValueError("days must be positive")
    completed: list[Window] = []
    pending: list[dict[str, Any]] = []
    participants: set[str] = set()
    previous_day = 0
    for item in _ordered(events):
        if not 0 <= int(item["day"]) < days:
            raise ValueError("action day outside observation period")
        pending.append(item); participants.add(item["eligible_id"])
        if len(participants) == k:
            window = Window(len(completed), k, previous_day, int(item["day"]), True, tuple(pending))
            if window.participant_count != k:
                raise AssertionError("strict-k checkpoint missed immediate threshold")
            completed.append(window)
            previous_day = int(item["day"])
            pending, participants = [], set()
    censored = Window(len(completed), k, previous_day, days, False, tuple(pending))
    return StrictKPartition(k, tuple(completed), censored)


def _public_action(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_type": "action", "action_id": event["action_id"], "eligible_id": event["eligible_id"],
        "action_type": event["action_type"], "day": int(event["day"]), "within_day_tick": int(event["within_day_tick"]),
        "global_order": int(event["global_order"]),
    }


def build_transcript(events: Iterable[dict[str, Any]], *, days: int, partition: StrictKPartition, release: str) -> list[dict[str, Any]]:
    """Build one allowlisted transcript. Final censored windows have no release."""

    if release not in RELEASES:
        raise ValueError(f"release must be one of {RELEASES}")
    completion = {window.events[-1]["action_id"]: window for window in partition.completed}
    transcript: list[dict[str, Any]] = []
    for event in _ordered(events):
        transcript.append(_public_action(event))
        window = completion.get(event["action_id"])
        if window is None:
            continue
        checkpoint: dict[str, Any] = {
            "record_type": "checkpoint", "checkpoint_id": window.index, "release": release,
            "day": int(event["day"]), "within_day_tick": int(event["within_day_tick"]),
            "global_order": int(event["global_order"]), "rate": int(event["rate"]),
        }
        if release == "checkpoint_totals":
            checkpoint["checkpoint_assets"] = int(event["aggregate_assets_after"])
            checkpoint["checkpoint_shares"] = int(event["aggregate_shares_after"])
        transcript.append(checkpoint)
    assert_public_only(transcript)
    return transcript


def checkpoint_schedule(partition: StrictKPartition) -> list[dict[str, Any]]:
    return [{"checkpoint_id": window.index, "k": window.k, "day": window.end_day, "end_action_id": window.events[-1]["action_id"], "action_ids": [item["action_id"] for item in window.events]} for window in partition.completed]


def build_matched_transcripts(events: Iterable[dict[str, Any]], *, days: int, k: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Return exact and rate-only treatments with a common latent schedule."""

    events = list(events)
    partition = partition_strict_k(events, days=days, k=k)
    totals = build_transcript(events, days=days, partition=partition, release="checkpoint_totals")
    rate_only = build_transcript(events, days=days, partition=partition, release="rate_only")
    totals_actions = [item for item in totals if item["record_type"] == "action"]
    rate_actions = [item for item in rate_only if item["record_type"] == "action"]
    schedule_hash = canonical_json_sha256(checkpoint_schedule(partition))
    return totals, rate_only, {
        "action_trace_hash": canonical_json_sha256(totals_actions),
        "rate_only_action_trace_hash": canonical_json_sha256(rate_actions),
        "checkpoint_schedule_hash": schedule_hash,
        "rate_only_checkpoint_schedule_hash": schedule_hash,
    }


def assert_public_only(transcript: Iterable[dict[str, Any]]) -> None:
    """Fail closed on every key outside the public transcript allowlist."""

    prior: tuple[int, int, int, int] | None = None
    for record in transcript:
        if not isinstance(record, dict):
            raise AssertionError("public record must be a dictionary")
        record_type = record.get("record_type")
        if record_type == "action":
            if set(record) != ACTION_FIELDS or set(record) & FORBIDDEN_TRUTH_FIELDS:
                raise AssertionError("action contains non-public truth")
            if record.get("action_type") not in {"deposit", "withdraw"}:
                raise AssertionError("invalid public action direction")
            type_order = 0
        elif record_type == "checkpoint":
            release = record.get("release")
            expected = CHECKPOINT_TOTAL_FIELDS if release == "checkpoint_totals" else CHECKPOINT_RATE_ONLY_FIELDS
            if release not in RELEASES or set(record) != expected:
                raise AssertionError("checkpoint disclosure violates allowlist")
            if int(record["rate"]) <= 0:
                raise AssertionError("public checkpoint rate must be positive")
            type_order = 1
        else:
            raise AssertionError("unknown public record type")
        order = (int(record["day"]), int(record["within_day_tick"]), int(record["global_order"]), type_order)
        if prior is not None and order < prior:
            raise AssertionError("public transcript ordering is unstable")
        prior = order
