from __future__ import annotations
from dataclasses import dataclass
import math

STRONG_HP_BONUS_PR = 24

@dataclass(frozen=True)
class HpProjection:
    points: list[tuple[int, int]]
    final_hp: int
    strong_levels: tuple[int, ...]
    standard_gain: int
    strong_gain: int

def distribute_flags(levels: list[int], count: int, curve_type: str = "Linear", slope: float = 1.0) -> set[int]:
    if not levels or count <= 0:
        return set()
    count = min(count, len(levels))
    slope = max(0.2, min(5.0, slope))

    def weight(index: int) -> float:
        x = index / max(1, len(levels) - 1)
        if curve_type == "Front Loaded":
            return (1.0 - x + 0.02) ** slope
        if curve_type in ("Back Loaded", "Late Start"):
            return (x + 0.02) ** slope
        if curve_type == "S Curve":
            return 0.25 + 1.0 / (1.0 + math.exp(-8.0 * slope * (x - 0.5)))
        if curve_type == "Early Burst":
            return (1.0 - min(1.0, x * 1.5) + 0.02) ** (1.0 / slope)
        if curve_type == "Exponential":
            return math.exp(slope * x)
        if curve_type == "Logarithmic":
            return math.log1p(slope * (1.0 - x) + 0.01)
        return 1.0

    ranked = sorted(range(len(levels)), key=lambda index: (-weight(index), levels[index]))
    return {levels[index] for index in ranked[:count]}

def vitality_by_level(
    base_vitality: int,
    rows: list[dict[str, str]],
    max_level: int,
) -> dict[int, int]:
    increments: dict[int, int] = {}
    for row in rows:
        try:
            level = int(row.get("lv", "0") or 0)
            increments[level] = int(row.get("vitality", "0") or 0)
        except ValueError:
            continue

    vitality = max(0, base_vitality)
    result = {1: vitality}
    for level in range(2, max_level + 1):
        vitality += increments.get(level, 0)
        result[level] = vitality
    return result

def project_hp(
    *,
    base_hp: int,
    base_vitality: int,
    rows: list[dict[str, str]],
    max_level: int,
    strong_levels: set[int] | None = None,
    extended_target: int | None = None,
) -> HpProjection:
    strong_levels = set(strong_levels or ())
    vit = vitality_by_level(base_vitality, rows, max_level)
    hp = max(1, base_hp)
    points = [(1, hp)]
    standard_total = 0
    strong_total = 0

    table_max = max(
        [int(row.get("lv", "0") or 0) for row in rows if str(row.get("lv", "")).isdigit()]
        or [1]
    )

    # Base-table projection: standard gain is floor(Vitality/4)+1,
    # and hp_value1 is treated as a strong-HP flag adding 24 in Pixel Remaster.
    for level in range(2, max_level + 1):
        current_vit = vit[level]
        standard = current_vit // 4 + 1
        strong = STRONG_HP_BONUS_PR if level in strong_levels else 0
        standard_total += standard
        strong_total += strong
        hp += standard + strong
        points.append((level, min(hp, 9999)))

    # NG+++ beyond the base table is a design projection. It does not write
    # unsafe rows. Blend toward the requested cap so the runtime bridge can
    # later implement the extended-level formula.
    if extended_target is not None and max_level > table_max:
        anchor_index = max(0, table_max - 1)
        anchor_hp = points[anchor_index][1]
        target = max(anchor_hp, min(9999, extended_target))
        span = max(1, max_level - table_max)
        revised = points[:anchor_index + 1]
        for level in range(table_max + 1, max_level + 1):
            x = (level - table_max) / span
            smooth = x * x * (3.0 - 2.0 * x)
            value = round(anchor_hp + (target - anchor_hp) * smooth)
            revised.append((level, min(9999, value)))
        points = revised
        hp = points[-1][1]

    return HpProjection(points, min(hp, 9999), tuple(sorted(strong_levels)), standard_total, strong_total)

def flags_for_target(
    *,
    base_hp: int,
    base_vitality: int,
    rows: list[dict[str, str]],
    target_hp: int,
    curve_type: str,
    slope: float,
) -> set[int]:
    levels = sorted(
        int(row.get("lv", "0") or 0)
        for row in rows
        if str(row.get("lv", "")).isdigit() and int(row.get("lv", "0") or 0) >= 2
    )
    if not levels:
        return set()

    baseline = project_hp(
        base_hp=base_hp,
        base_vitality=base_vitality,
        rows=rows,
        max_level=max(levels),
        strong_levels=set(),
    ).final_hp
    needed = max(0, target_hp - baseline)
    strong_count = round(needed / STRONG_HP_BONUS_PR)
    return distribute_flags(levels, strong_count, curve_type, slope)

def write_strong_hp_flags(rows: list[dict[str, str]], strong_levels: set[int]) -> None:
    for row in rows:
        try:
            level = int(row.get("lv", "0") or 0)
        except ValueError:
            continue
        if "hp_value1" in row:
            row["hp_value1"] = "1" if level in strong_levels else "0"
