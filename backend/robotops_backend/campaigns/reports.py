"""Read-only report derivation and confined local artifact verification."""

import hashlib
import html
import json
import math
import os
import re
import stat
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean

from .models import CampaignRecord, PlannedTrial
from .report_models import (
    ArtifactCheck,
    CampaignReport,
    MetricSummary,
    ProfileReport,
    TrialIntegrity,
)
from .repository import CampaignConflict

LIMITATIONS = [
    "ROS outcome, localized pose validation and contact evidence are separate; no combined pass.",
    "Artifact integrity was checked only at report generation; downloads retain that snapshot.",
    "Hashes support local integrity, not signed authenticity. Missing evidence is not a pass.",
    "Contact windows measure monitored geometry, not unique episodes or physical safety.",
    "Metric means use available successful-trial samples; runs are not statistical proof.",
    "Legacy browser estimates are separate and are not imported into this report.",
]


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class ArtifactReader:
    """Open beneath one root without following symlinks, including parent directories."""

    def __init__(self, root: Path, budget: int = 512 * 1024 * 1024):
        self.root = root.absolute()
        self.remaining = budget

    def check(
        self, reference: str, expected: str | None = None, *, read_json: bool = False
    ) -> tuple[ArtifactCheck, object | None]:
        check = ArtifactCheck(reference=reference, state="UNAVAILABLE", expected_sha256=expected)
        fd = None
        try:
            path = Path(reference)
            if not path.is_absolute() or ".." in path.parts:
                raise ValueError("Artifact path must be absolute and confined")
            parts = path.relative_to(self.root).parts
            if not parts:
                raise ValueError("Artifact reference must name a file")
            if expected is not None and not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise ValueError("Invalid expected SHA-256")
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for index, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if index < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Artifact is not a regular file")
            if before.st_size > self.remaining or (
                read_json and before.st_size > 16 * 1024 * 1024
            ):
                check.reason = "Artifact verification byte budget exceeded"
                return check, None
            self.remaining -= before.st_size
            sha = hashlib.sha256()
            chunks = []
            size = 0
            while chunk := os.read(fd, 1024 * 1024):
                size += len(chunk)
                if size > before.st_size:
                    raise ValueError("Artifact changed while reading")
                sha.update(chunk)
                if read_json:
                    chunks.append(chunk)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or size != before.st_size:
                raise ValueError("Artifact changed while reading")
            check.actual_sha256 = sha.hexdigest()
            check.state = (
                "VERIFIED" if expected is None or check.actual_sha256 == expected else "MISMATCH"
            )
            data = json.loads(b"".join(chunks)) if read_json else None
            return check, data
        except FileNotFoundError:
            check.state, check.reason = "MISSING", "Artifact file or directory is missing"
        except (ValueError, UnicodeError, RecursionError):
            check.state, check.reason = (
                "UNTRUSTED",
                "Unsafe, changed or invalid artifact reference/content",
            )
        except OSError:
            check.state, check.reason = (
                "UNTRUSTED",
                "Artifact cannot be safely opened without symlinks",
            )
        finally:
            if fd is not None:
                os.close(fd)
        return check, None


def trial_integrity(
    record: CampaignRecord, trial: PlannedTrial, reader: ArtifactReader
) -> TrialIntegrity:
    result = TrialIntegrity(trial_id=trial.id, state="UNAVAILABLE")
    evidence = trial.evidence
    if evidence is None:
        result.reasons.append("No finalized runner evidence")
        return result
    check, manifest = reader.check(evidence.manifest_path, read_json=True)
    result.artifacts.append(check)
    if check.state != "VERIFIED":
        result.state = "UNAVAILABLE" if check.state == "UNAVAILABLE" else "ISSUES"
        result.reasons.append("Runner manifest unavailable or invalid")
        return result
    try:
        if manifest["experiment_id"] != evidence.experiment_id:
            raise ValueError("Experiment ID differs")
        context = manifest["config"].get("execution_context")
        if context != {"campaign_id": record.id, "trial_id": trial.id}:
            raise ValueError("Campaign/trial context is absent or differs")
        saved_trials = manifest["trials"]
        if len(saved_trials) != 1:
            raise ValueError("Expected one runner trial")
        saved = saved_trials[0]
        for key, expected in (
            ("run_id", evidence.mission_run_id),
            ("outcome", evidence.outcome),
            ("metrics", evidence.metrics),
            ("validation", evidence.validation),
            ("collision", evidence.collision),
        ):
            if saved.get(key, {} if key == "metrics" else None) != expected:
                raise ValueError(f"Stored {key} differs from runner manifest")
        provenance = (evidence.validation or {}).get("provenance", {})
        if provenance.get("state") != "confirmed":
            result.reasons.append("No confirmed mission artifact provenance")
            return result
        if (
            digest(manifest["config"]) != provenance["config_sha256"]
            or digest(saved["parameters"]) != provenance["parameters_sha256"]
        ):
            raise ValueError("Configuration/parameter fingerprint differs")
        if saved.get("parameters_after", saved["parameters"]) != saved["parameters"]:
            raise ValueError("After-trial parameters differ")
        check.reason = (
            "Runner fields bound to stored evidence; no prior whole-manifest fingerprint"
        )
        hashes = provenance["artifact_sha256"]
        if (
            not isinstance(hashes, dict)
            or not {"metadata.json", "result.json", "metadata.yaml"}.issubset(hashes)
            or not any(re.fullmatch(r"telemetry/[^/]+\.mcap", k) for k in hashes)
        ):
            raise ValueError("Incomplete mission artifact fingerprints")
        run = Path(saved["artifact_directory"])
        for name, expected_hash in sorted(hashes.items()):
            if not isinstance(expected_hash, str) or not re.fullmatch(
                r"[a-f0-9]{64}", expected_hash
            ):
                raise ValueError("Missing or invalid mission artifact fingerprint")
            if name in ("metadata.json", "result.json"):
                reference = run / name
            elif name == "metadata.yaml":
                reference = run / "telemetry/metadata.yaml"
            elif re.fullmatch(r"telemetry/[^/]+\.mcap", name):
                reference = run / name
            else:
                raise ValueError("Unexpected mission artifact reference")
            result.artifacts.append(reader.check(str(reference), expected_hash)[0])
        if evidence.collision is not None:
            artifact = evidence.collision.get("artifact")
            if not isinstance(artifact, dict):
                result.reasons.append("Contact evidence artifact reference unavailable")
            else:
                if not isinstance(artifact.get("sha256"), str):
                    raise ValueError("Contact artifact fingerprint unavailable")
                result.artifacts.append(reader.check(artifact["path"], artifact["sha256"])[0])
        result.state = "VERIFIED"
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        result.reasons.append(str(error))
        result.state = "ISSUES"
    if any(a.state in ("MISSING", "MISMATCH", "UNTRUSTED") for a in result.artifacts):
        result.state = "ISSUES"
        result.reasons.append("One or more artifact checks failed")
    elif result.state == "VERIFIED" and (
        result.reasons or any(a.state == "UNAVAILABLE" for a in result.artifacts)
    ):
        result.state = "UNAVAILABLE"
    return result


def summarize(record: CampaignRecord) -> list[ProfileReport]:
    profiles = []
    for profile in record.definition.profiles:
        trials = [t for t in record.trials if t.profile == profile]
        attempted = [
            t
            for t in trials
            if t.evidence is not None or t.state in ("succeeded", "failed", "interrupted")
        ]
        successes = [
            t
            for t in attempted
            if t.state == "succeeded" and t.evidence and t.evidence.outcome == "succeeded"
        ]

        def metric(key: str, successes: list[PlannedTrial] = successes) -> dict:
            values = [t.evidence.metrics.get(key) for t in successes]
            values = [v for v in values if type(v) in (float, int) and math.isfinite(v) and v >= 0]
            return dict(mean=fmean(values) if values else None, samples=len(values))

        def verdicts(key: str, trials: list[PlannedTrial] = trials) -> dict[str, int]:
            return dict(
                Counter(
                    (getattr(t.evidence, key, None) or {}).get("verdict", "UNVALIDATED")
                    for t in trials
                )
            )

        profiles.append(
            ProfileReport(
                profile=profile,
                requested=len(trials),
                attempted=len(attempted),
                ros_successes=len(successes),
                ros_success_rate=len(successes) / len(attempted) if attempted else None,
                duration_seconds=metric("mission_ros_seconds"),
                odom_metres=metric("odom_path_metres"),
                pose_verdicts=verdicts("validation"),
                contact_verdicts=verdicts("collision"),
            )
        )
    return profiles


def build_report(record: CampaignRecord, artifact_root: Path) -> CampaignReport:
    if record.state not in ("completed", "failed", "canceled", "interrupted"):
        raise CampaignConflict("Reports require a finalized campaign; execution is never changed")
    reader = ArtifactReader(artifact_root)
    integrity = [trial_integrity(record, t, reader) for t in record.trials]
    source_sha = digest(record.model_dump(mode="json"))
    payload = dict(
        schema_version=1,
        source_sha256=source_sha,
        campaign=record.model_dump(mode="json"),
        profiles=[p.model_dump() for p in summarize(record)],
        integrity=[i.model_dump() for i in integrity],
        limitations=LIMITATIONS,
    )
    return CampaignReport(id=digest(payload), created_at=datetime.now(UTC), **payload)


def render_html(report: CampaignReport) -> str:
    def escape(value: object) -> str:
        return html.escape(str(value), quote=True)

    def measurement(value: MetricSummary, unit: str) -> str:
        return (
            "Unavailable (0 samples)"
            if value.mean is None
            else (f"{value.mean:.3f} {unit} ({value.samples} samples)")
        )

    record = report.campaign
    profiles = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(v)}</td>"
            for v in (
                p.profile,
                f"{p.ros_successes}/{p.attempted} attempts; {p.requested} requested",
                "Unavailable" if p.ros_success_rate is None else f"{p.ros_success_rate:.1%}",
                measurement(p.duration_seconds, "s"),
                measurement(p.odom_metres, "m"),
                json.dumps(p.pose_verdicts),
                json.dumps(p.contact_verdicts),
            )
        )
        + "</tr>"
        for p in report.profiles
    )
    audits = {i.trial_id: i for i in report.integrity}
    trials = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(v)}</td>"
            for v in (
                t.id,
                t.profile,
                t.repetition,
                t.state,
                t.evidence.outcome if t.evidence else "Unavailable",
                (t.evidence.validation or {}).get("verdict", "UNVALIDATED")
                if t.evidence
                else "UNVALIDATED",
                (t.evidence.collision or {}).get("verdict", "UNVALIDATED")
                if t.evidence
                else "UNVALIDATED",
                audits[t.id].state,
            )
        )
        + "</tr>"
        for t in record.trials
    )
    notes = "".join(f"<li>{escape(note)}</li>" for note in report.limitations)
    audit_details = ""
    for audit in report.integrity:
        reasons = "".join(f"<li>{escape(reason)}</li>" for reason in audit.reasons)
        files = "".join(
            f"<tr><td>{escape(a.reference)}</td><td>{escape(a.state)}</td>"
            f"<td>{escape(a.reason or '')}<br>"
            f"Expected: {escape(a.expected_sha256 or 'Not recorded')}"
            f"<br>Observed: {escape(a.actual_sha256 or 'Unavailable')}</td></tr>"
            for a in audit.artifacts
        )
        audit_details += (
            f"<details><summary>Trial {escape(audit.trial_id)} · {escape(audit.state)}</summary>"
            f"<ul>{reasons}</ul><div class='scroll'><table><tr><th>Reference</th>"
            f"<th>Check</th><th>Details</th></tr>{files}</table></div></details>"
        )
    snapshot = escape(report.model_dump_json(indent=2))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RobotOps report · {escape(record.definition.name)}</title>
<style>body{{font:16px system-ui;max-width:1200px;margin:32px auto;padding:0 20px;color:#172332}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{border:1px solid #ccd3dc;padding:8px;text-align:left;
vertical-align:top;overflow-wrap:anywhere}}
.scroll{{overflow:auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}
small{{overflow-wrap:anywhere}}
@media print{{body{{margin:0;max-width:none}}table{{font-size:10px}}
details{{display:block}}}}</style>
<h1>RobotOps experiment report</h1><h2>{escape(record.definition.name)}</h2>
<p>Campaign {escape(record.id)} · {escape(record.state)} · {escape(record.definition.runtime_mode)}
· {escape(record.definition.world)} / {escape(record.definition.map_id)}</p>
<p>Generated {escape(report.created_at.isoformat())}. Integrity is a snapshot at this time.</p>
<small>Report {escape(report.id)}<br>
Campaign snapshot SHA-256 {escape(report.source_sha256)}</small>
<h2>Profile results</h2><div class="scroll"><table><tr><th>Profile</th><th>ROS attempts</th>
<th>ROS success rate</th><th>Mean ROS duration</th><th>Mean odometry distance</th>
<th>Pose verdicts</th><th>Contact verdicts</th></tr>{profiles}</table></div>
<h2>Trial results</h2><div class="scroll"><table><tr><th>Trial ID</th>
<th>Profile</th><th>Repetition</th><th>State</th><th>ROS outcome</th><th>Pose</th>
<th>Contact</th><th>Artifact integrity</th></tr>{trials}</table></div>
<h2>Artifact checks at generation</h2>{audit_details}
<h2>Scope and limitations</h2><ul>{notes}</ul>
<details><summary>Complete report snapshot, evidence and integrity checks</summary>
<pre>{snapshot}</pre></details></html>"""
