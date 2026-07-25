from __future__ import annotations


def permission_slot_for_job(job_id: str | int) -> int:
    """Return the native FF1PR job_group.csv slot.

    The last confirmed working equipment editor (v0.24/v0.25) changed
    job1_accept for displayed job 1, job2_accept for displayed job 2, etc.
    Do not remap base jobs to promoted slots and do not create extra groups.
    """
    try:
        value = int(str(job_id).strip())
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def permission_field_for_job(job_id: str | int) -> str:
    slot = permission_slot_for_job(job_id)
    return f"job{slot}_accept" if slot else ""
