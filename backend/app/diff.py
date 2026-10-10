from dataclasses import dataclass


@dataclass
class ReplySnapshot:
    score: int | None
    child_ids: list[str]
    snippets: dict[str, str]
    deleted: bool


def diff_reply(
    *,
    has_baseline: bool,
    old_score: int | None,
    old_child_ids: list[str],
    old_deleted: bool,
    snap: ReplySnapshot,
) -> list[tuple[str, str]]:
    """Return (kind, detail) events. The first successful check only sets a baseline."""
    if not has_baseline:
        return []
    events: list[tuple[str, str]] = []
    if snap.deleted and not old_deleted:
        events.append(("deleted", "这条回复已经看不到了"))
        return events
    fresh = [cid for cid in snap.child_ids if cid not in set(old_child_ids)]
    if fresh:
        bits = [snap.snippets.get(cid, "").strip() for cid in fresh]
        bits = [bit for bit in bits if bit]
        detail = "\n\n".join(bits) if bits else f"新回复 {len(fresh)} 条"
        events.append(("new_child", detail[:2000]))
    if (
        snap.score is not None
        and old_score is not None
        and snap.score != old_score
    ):
        events.append(("score_change", f"{old_score} → {snap.score}"))
    return events
