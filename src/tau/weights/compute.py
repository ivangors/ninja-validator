"""The weight distribution rule for the rolling king window.

Before all five non-burn king slots are populated, the existing winners split 100%
by the bootstrap table. Once five non-burn kings exist, distribution returns to the
regular rule: 40% to the reigning king and 15% to each of the next four prior kings.
Emission follows the hotkey and shares accumulate per uid.
"""

from __future__ import annotations

from collections.abc import Sequence

from .types import MetagraphView, RecentKing, WeightPlan

KING_EMISSION_SHARES: tuple[float, ...] = (0.40, 0.15, 0.15, 0.15, 0.15)
BOOTSTRAP_KING_EMISSION_SHARES: dict[int, tuple[float, ...]] = {
    1: (1.00,),
    2: (0.60, 0.40),
    3: (0.40, 0.30, 0.30),
    4: (0.40, 0.20, 0.20, 0.20),
}


def king_emission_shares(
    window: int, king_count: int | None = None
) -> tuple[float, ...]:
    slots = max(0, window)
    if king_count is None:
        return KING_EMISSION_SHARES[:slots]
    filled_slots = min(max(0, king_count), slots)
    if filled_slots in BOOTSTRAP_KING_EMISSION_SHARES:
        return BOOTSTRAP_KING_EMISSION_SHARES[filled_slots]
    return KING_EMISSION_SHARES[:slots]


def compute_weights(
    kings: Sequence[RecentKing],
    meta: MetagraphView,
    *,
    window: int,
    burn_uid: int,
) -> WeightPlan:
    eligible_kings = _non_burn_kings(kings, meta, burn_uid)
    king_count = min(len(eligible_kings), max(0, window))
    shares = king_emission_shares(window, king_count)
    weights_by_uid: dict[int, float] = {u: 0.0 for u in meta.uids}
    king_shares: dict[int, float] = {}
    burn = 0.0

    for slot, share in enumerate(shares):
        king = eligible_kings[slot] if slot < len(eligible_kings) else None
        uid = meta.uid_by_hotkey.get(king.hotkey) if king is not None else None
        if king is not None and uid is not None and uid in weights_by_uid:
            weights_by_uid[uid] += share
            king_shares[uid] = king_shares.get(uid, 0.0) + share
        else:
            burn += share

    if not meta.uids:
        return WeightPlan((), (), False, "no neurons in metagraph", "")
    if burn > 0 and burn_uid not in weights_by_uid:
        return WeightPlan((), (), False, f"burn uid {burn_uid} absent from metagraph", "")
    if burn > 0:
        weights_by_uid[burn_uid] += burn

    uids = tuple(meta.uids)
    weights = tuple(weights_by_uid[u] for u in uids)
    kings_str = ", ".join(f"uid{u}={s:.2f}" for u, s in king_shares.items())
    summary = f"kings=[{kings_str}] burn={burn:.2f}"
    return WeightPlan(uids, weights, True, None, summary)


def _non_burn_kings(
    kings: Sequence[RecentKing], meta: MetagraphView, burn_uid: int
) -> list[RecentKing]:
    return [
        king
        for king in kings
        if meta.uid_by_hotkey.get(king.hotkey) != burn_uid
    ]
