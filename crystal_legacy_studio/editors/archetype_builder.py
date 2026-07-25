from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

CORE_STATS = ("strength", "vitality", "agility", "intelligence", "spirit", "luck")

ROLE_WEIGHTS = {
    "Warrior": {
        "strength": 1.00, "vitality": 0.76, "agility": 0.48,
        "intelligence": 0.06, "spirit": 0.12, "luck": 0.34,
        "accuracy_rate": 0.78, "evasion_rate": 0.40,
    },
    "Tank": {
        "strength": 0.66, "vitality": 1.00, "agility": 0.24,
        "intelligence": 0.05, "spirit": 0.38, "luck": 0.20,
        "accuracy_rate": 0.65, "evasion_rate": 0.28,
    },
    "Ninja": {
        "strength": 0.70, "vitality": 0.40, "agility": 1.00,
        "intelligence": 0.22, "spirit": 0.15, "luck": 0.74,
        "accuracy_rate": 0.98, "evasion_rate": 0.80,
    },
    "Caster": {
        "strength": 0.08, "vitality": 0.28, "agility": 0.44,
        "intelligence": 1.00, "spirit": 0.86, "luck": 0.44,
        "accuracy_rate": 0.44, "evasion_rate": 0.78,
    },
}

@dataclass(frozen=True)
class ArchetypePlan:
    roles: tuple[str, ...]
    core_targets: dict[str, int]
    accuracy_target: int
    evasion_target: int
    hp_target_99: int
    stat_budget: int

def _normalize(raw: dict[str, float], budget: int) -> dict[str, int]:
    total = sum(max(value, 0.01) for value in raw.values())
    result = {
        key: max(20, round(max(value, 0.01) / total * budget))
        for key, value in raw.items()
    }

    delta = budget - sum(result.values())
    order = sorted(raw, key=raw.get, reverse=True)
    index = 0
    while delta:
        key = order[index % len(order)]
        if delta > 0:
            result[key] += 1
            delta -= 1
        elif result[key] > 20:
            result[key] -= 1
            delta += 1
        index += 1

    high = sorted(
        (key for key, value in result.items() if value >= 90),
        key=lambda key: result[key],
        reverse=True,
    )
    for key in high[2:]:
        excess = result[key] - 89
        result[key] = 89
        recipients = [candidate for candidate in order if candidate not in high[:2] and candidate != key]
        for position in range(excess):
            result[recipients[position % len(recipients)]] += 1
    return result

def build_archetype_plan(
    roles: Iterable[str],
    stat_budget: int = 420,
) -> ArchetypePlan:
    selected = tuple(role for role in roles if role in ROLE_WEIGHTS) or ("Warrior",)
    raw = {stat: 0.0 for stat in CORE_STATS}
    accuracy = 0.0
    evasion = 0.0

    for role in selected:
        weights = ROLE_WEIGHTS[role]
        for stat in CORE_STATS:
            raw[stat] += weights[stat]
        accuracy += weights["accuracy_rate"]
        evasion += weights["evasion_rate"]

    count = float(len(selected))
    raw = {key: value / count for key, value in raw.items()}
    core = _normalize(raw, stat_budget)
    vitality = core["vitality"]
    tank_factor = 1.0 if "Tank" in selected else 0.0
    warrior_factor = 1.0 if "Warrior" in selected else 0.0
    caster_penalty = 1.0 if selected == ("Caster",) else 0.0
    hp_target = round(
        520
        + vitality * 3.15
        + tank_factor * 135
        + warrior_factor * 55
        - caster_penalty * 85
    )
    hp_target = min(1150, max(520, hp_target))
    return ArchetypePlan(
        selected,
        core,
        min(500, max(180, round(accuracy / count * 500))),
        min(500, max(160, round(evasion / count * 500))),
        hp_target,
        stat_budget,
    )
