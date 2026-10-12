"""Own a rosbag2 recorder process and validate its finalized MCAP artifacts."""

import re
import signal
import subprocess
from pathlib import Path

import yaml

TOPIC = re.compile(r"^/?[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*$")


def load_recording_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if (
        not isinstance(data, dict)
        or not {"topics", "required_topics", "qos"} <= set(data)
        or set(data) - {"topics", "required_topics", "qos", "startup_topics"}
    ):
        raise ValueError("Recording configuration needs topics, required_topics and qos")
    if not isinstance(data["required_topics"], list):
        raise ValueError("required_topics must be a list")
    data.setdefault("startup_topics", list(data["required_topics"]))
    for key in ("topics", "required_topics", "startup_topics"):
        values = data[key]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(t, str) or not TOPIC.fullmatch(t) for t in values)
        ):
            raise ValueError(f"{key} must be a nonempty list of valid topic names")
        if len(set(values)) != len(values):
            raise ValueError(f"Duplicate {key}")
    if not (set(data["required_topics"]) | set(data["startup_topics"])) <= set(data["topics"]):
        raise ValueError("Required topics must be in the recording topic list")
    if not isinstance(data["qos"], dict) or not set(data["qos"]) <= set(data["topics"]):
        raise ValueError("QoS entries must refer to recorded topics")
    for profile in data["qos"].values():
        if not isinstance(profile, dict) or set(profile) != {"reliability", "durability", "depth"}:
            raise ValueError("QoS needs reliability, durability and depth")
        if profile["reliability"] not in ("reliable", "best_effort") or profile[
            "durability"
        ] not in ("volatile", "transient_local"):
            raise ValueError("Invalid recording QoS policy")
        if type(profile["depth"]) is not int or profile["depth"] <= 0:
            raise ValueError("QoS depth must be a positive integer")
    return data


def inspect_bag(directory: Path, required: list[str]) -> dict:
    info = yaml.safe_load((directory / "metadata.yaml").read_text())["rosbag2_bagfile_information"]
    if info["storage_identifier"] != "mcap":
        raise RuntimeError("Recorder did not produce MCAP")
    paths = info["relative_file_paths"]
    if not paths:
        raise RuntimeError("No MCAP files finalized")
    size = 0
    for relative in paths:
        path = (directory / relative).resolve()
        if path.parent != directory.resolve() or path.suffix != ".mcap":
            raise RuntimeError("Invalid bag artifact path")
        with path.open("rb") as stream:
            start = stream.read(8)
            stream.seek(-8, 2)
            end = stream.read(8)
        if start != b"\x89MCAP0\r\n" or end != start:
            raise RuntimeError("MCAP file is incomplete")
        size += path.stat().st_size
    counts = {
        item["topic_metadata"]["name"]: item["message_count"]
        for item in info["topics_with_message_count"]
    }
    if any(counts.get(topic, 0) <= 0 for topic in required):
        raise RuntimeError(f"Required telemetry missing from finalized recording: {counts}")
    return {"path": "telemetry", "format": "mcap", "bytes": size, "topic_counts": counts}


class Recorder:
    def __init__(self, directory: Path, run_id: str, config: dict, use_sim_time: bool):
        self.directory = directory
        self.config = config
        self.name = f"recorder_{run_id}"
        self.use_sim_time = use_sim_time
        self.log = (directory / "recorder.log").open("w")
        qos = directory / "recording_qos.yaml"
        qos.write_text(yaml.safe_dump(config["qos"]))
        command = [
            "ros2",
            "bag",
            "record",
            "--storage",
            "mcap",
            "--output",
            str(directory / "telemetry"),
            "--node-name",
            self.name,
            "--disable-keyboard-controls",
            "--qos-profile-overrides-path",
            str(qos),
            "--max-cache-size",
            "8388608",
        ]
        if use_sim_time:
            command.append("--use-sim-time")
        command.extend(["--topics", *config["topics"]])
        try:
            self.process = subprocess.Popen(
                command, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True
            )
        except Exception:
            self.log.close()
            raise

    def check_alive(self) -> None:
        if self.process.poll() is not None:
            raise RuntimeError(f"Recorder exited unexpectedly ({self.process.returncode})")

    def startup_status(self, subscriptions, publishers, compatible) -> dict:
        """Read-only graph/storage capability check, never a coverage verdict.

        compatible must return True only for known-compatible offered/requested
        QoS (WARNING/unknown is not sufficient). No node creation or spinning here.
        """
        self.check_alive()
        text = (self.directory / "recorder.log").read_text()
        causes, topics = [], {}
        if "Recording..." not in text:
            causes.append("recorder.writer_not_started")
        if self.use_sim_time and "Sim time /clock found, starting recording." not in text:
            causes.append("recorder.clock_not_received")
        files = list((self.directory / "telemetry").glob("*.mcap"))
        opened = False
        for path in files:
            with path.open("rb") as stream:
                opened |= stream.read(8) == b"\x89MCAP0\r\n"
        if not opened:
            causes.append("recorder.storage_not_open")
        required = list(self.config.get("startup_topics", self.config["required_topics"]))
        if self.use_sim_time and "/clock" not in required:
            required.append("/clock")
        for topic in required:
            subs = [e for e in subscriptions(topic) if e.node_name == self.name]
            pubs = publishers(topic)
            flags = []
            if len(subs) != 1:
                flags.append("subscription_missing_or_ambiguous")
            if not pubs:
                flags.append("publisher_missing")
            if len(subs) == 1 and pubs:
                sub = subs[0]
                if any(p.topic_type != sub.topic_type for p in pubs):
                    flags.append("type_mismatch")
                if any(not compatible(p.qos_profile, sub.qos_profile) for p in pubs):
                    flags.append("qos_incompatible_or_unknown")
                # Durable histories require a durable reader, even if a volatile
                # reader is otherwise compatible with future publications.
                profile = self.config["qos"].get(topic, {})
                if (
                    profile.get("durability") == "transient_local"
                    and int(sub.qos_profile.durability) != 1
                ):
                    flags.append("durable_history_not_requested")

            def describe(e):
                return dict(
                    node=e.node_name,
                    type=e.topic_type,
                    reliability=int(getattr(e.qos_profile, "reliability", 0)),
                    durability=int(e.qos_profile.durability),
                    depth=getattr(e.qos_profile, "depth", None),
                )

            topics[topic] = dict(
                publishers=len(pubs),
                recorder_subscriptions=len(subs),
                causes=flags,
                offered=[describe(e) for e in pubs],
                requested=[describe(e) for e in subs],
            )
            causes.extend(f"recorder.{topic}.{f}" for f in flags)
        return dict(
            ready=not causes,
            causes=causes,
            topics=topics,
            storage_open=opened,
            coverage="NOT_YET_VERIFIED",
        )

    def stop(self, timeout: float = 10.0) -> dict:
        early_exit = self.process.poll() is not None
        forced = False
        try:
            if not early_exit:
                self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                forced = True
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if early_exit or forced or self.process.returncode != 0:
                raise RuntimeError(
                    f"Recorder failed: early_exit={early_exit}, forced={forced}, "
                    f"exit={self.process.returncode}; see recorder.log"
                )
            losses = re.findall(
                r"Number of messages lost on the transport layer: (\d+)",
                (self.directory / "recorder.log").read_text(),
            )
            if any(int(n) > 0 for n in losses):
                raise RuntimeError(
                    "Recorder transport loss; required-topic loss cannot be excluded"
                )
            return inspect_bag(self.directory / "telemetry", self.config["required_topics"])
        finally:
            self.log.close()
