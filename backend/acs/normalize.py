"""Conservative state intervals. A stale feed never implies constant occupancy."""
import json
from datetime import timedelta
from .db import put
from .ingestion import CONFIG, utc, digest, now

UNAVAILABLE = {"INOPERATIVE", "OUTOFORDER", "UNKNOWN", "REMOVED", "BLOCKED", "RESERVED"}

def rebuild(db):
    for table in ("transitions", "heartbeats", "episodes"):
        db.execute(f"DELETE FROM {table}")
    gap_limit = timedelta(minutes=CONFIG["heartbeat_max_gap_minutes"])
    counts = {"transitions": 0, "heartbeats": 0, "episodes": 0}
    for plug in db.execute("SELECT id FROM plugs").fetchall():
        rows = db.execute("SELECT * FROM observations WHERE plug_id=? ORDER BY observed_at,transaction_at,id", (plug[0],)).fetchall()
        # A later transaction at the same valid time supersedes a former revision;
        # every revision is still retained in observations and raw evidence.
        effective = {r["observed_at"]: r for r in rows}
        rows = list(effective.values())
        previous = None
        episode = None
        unavailable_start = None
        longest_unavailable = 0
        unavailable_seconds = total_seconds = 0
        starts = 0
        longest_charging = 0
        def close(end, censored):
            nonlocal episode, longest_charging
            if episode is None:
                return
            duration = max(0, (utc(end) - utc(episode["start"])).total_seconds())
            longest_charging = max(longest_charging, duration)
            ident = digest(plug[0] + episode["start"])
            db.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?,?)", (
                ident, plug[0], episode["start"], end, duration, episode["left"], int(censored),
                int(duration < CONFIG["short_episode_seconds"]), int(duration >= CONFIG["long_episode_hours"] * 3600)))
            counts["episodes"] += 1
            episode = None
        for row in rows:
            gap = previous is None or utc(row["observed_at"]) - utc(previous["observed_at"]) > gap_limit
            repeated = previous is not None and row["status"] == previous["status"]
            db.execute("INSERT INTO heartbeats VALUES (?,?,?,?)", (row["id"], plug[0], row["observed_at"], int(repeated)))
            counts["heartbeats"] += 1
            if gap or not repeated:
                db.execute("INSERT INTO transitions VALUES (?,?,?,?,?,?,?)", (
                    row["id"], plug[0], row["observed_at"], previous["status"] if previous and not gap else None,
                    row["status"], row["id"], int(gap)))
                counts["transitions"] += 1
            if previous and not gap:
                seconds = (utc(row["observed_at"]) - utc(previous["observed_at"])).total_seconds()
                total_seconds += seconds
                if previous["status"] in UNAVAILABLE:
                    unavailable_seconds += seconds
                    if unavailable_start is None:
                        unavailable_start = previous["observed_at"]
                    longest_unavailable = max(longest_unavailable, (utc(row["observed_at"]) - utc(unavailable_start)).total_seconds())
                else:
                    unavailable_start = None
            if gap:
                if previous:
                    close(previous["observed_at"], True)
                unavailable_start = None
            elif previous["status"] == "CHARGING" and row["status"] != "CHARGING":
                close(row["observed_at"], False)
            if row["status"] == "CHARGING" and episode is None:
                episode = {"start": row["observed_at"], "left": int(gap)}
                if not gap:
                    starts += 1
            previous = row
        if previous:
            close(previous["observed_at"], True)
        ratio = unavailable_seconds / total_seconds if total_seconds else None
        # DC sibling coupling requires plant-specific evidence. Never classify it as a fault.
        metadata = json.loads(db.execute("SELECT payload FROM plugs WHERE id=?", (plug[0],)).fetchone()[0])
        dc = any(c.get("power_type") == "DC" for c in metadata["connectors"])
        flags = []
        if dc:
            flags.append("dc_pairing_review_required")
        elif longest_unavailable >= 14 * 86400 or (ratio is not None and ratio > .5 and starts == 0):
            flags.append("prolonged_unavailability")
        elif ratio is not None and ratio > .1:
            flags.append("frequent_unavailability")
        if longest_charging >= 48 * 3600:
            flags.append("long_occupancy_review")
        put(db, "quality", plug[0], {"plug_id": plug[0], "origin": "derived", "flags": flags,
            "observed_episode_starts": starts, "covered_seconds": total_seconds,
            "unavailable_fraction": ratio, "longest_unavailable_seconds": longest_unavailable,
            "first_observation": rows[0]["observed_at"] if rows else None,
            "last_observation": rows[-1]["observed_at"] if rows else None,
            "method": "normalize-v1", "dc_unavailability_validated": False if dc else None})
    put(db, "pipeline", "normalization", {"at": now(), "method": "normalize-v1", "config": CONFIG, "counts": counts})
    return counts
