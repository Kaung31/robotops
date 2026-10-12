"""Backend-neutral, pure contact-window validation. Silence never means zero."""


def evaluate_contacts(frames: list[dict], start_ns: int, end_ns: int) -> dict:
    result = dict(
        schema_version=1,
        verdict="UNKNOWN",
        reasons=[],
        contacts=[],
        start_ns=start_ns,
        end_ns=end_ns,
        frame_count=0,
        scope="adapter-monitored contact geometry; boundary windows conservative",
    )
    reasons = result["reasons"]
    if end_ns <= start_ns or start_ns <= 0:
        reasons.append("Invalid mission clock interval")
        return result
    relevant = [f for f in frames if f["end_ns"] > start_ns and f["start_ns"] < end_ns]
    result["frame_count"] = len(relevant)
    if not relevant:
        reasons.append("No contact coverage for mission interval")
        return result
    previous = None
    inventory = None
    for frame in relevant:
        signature = (frame["source_id"], frame["monitored_bodies"], frame["support_pairs"])
        if inventory is None:
            inventory = signature
        if signature != inventory:
            reasons.append("Contact source or coverage policy changed")
        if not frame["source_id"] or not frame["monitored_bodies"]:
            reasons.append("Missing source/body inventory")
        if not frame["coverage_complete"] or frame["physics_steps"] <= 0:
            reasons.append("Adapter reports incomplete physics coverage")
        if not 0 < frame["end_ns"] - frame["start_ns"] <= 250_000_000:
            reasons.append("Invalid contact window duration")
        if previous and (
            frame["sequence"] != previous["sequence"] + 1
            or frame["start_ns"] != previous["end_ns"]
        ):
            reasons.append("Contact sequence/time discontinuity")
        previous = frame
        for pair in frame["contacts"]:
            if not (
                pair["body_a"]
                and pair["body_b"]
                and frame["start_ns"] < pair["first_ns"] <= pair["last_ns"] <= frame["end_ns"]
            ):
                reasons.append("Invalid contact timestamp/body")
                continue
            if pair["last_ns"] >= start_ns and pair["first_ns"] <= end_ns:
                result["contacts"].append(pair)
    if relevant[0]["start_ns"] > start_ns or relevant[-1]["end_ns"] < end_ns:
        reasons.append("Contact windows do not cover both mission boundaries")
    result["source_id"] = inventory[0]
    result["monitored_bodies"] = inventory[1]
    result["support_pairs"] = inventory[2]
    result["reasons"] = list(dict.fromkeys(reasons))
    # Positive observed contact survives a coverage gap; zero requires complete coverage.
    if result["contacts"]:
        result["verdict"] = "CONTACT_DETECTED"
    elif not reasons:
        result["verdict"] = "NO_CONTACT_OBSERVED"
    return result
