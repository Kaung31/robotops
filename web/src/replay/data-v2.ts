import schemas from "./schema-v2.json";
import { freeze, gunzip, parsePgm, readBounded, sha256, validate, type Dataset, type Manifest, type Pose, type Scan } from "./data";

export const DATASETS = {
  N0: { label: "Baseline N0", hash: "670ccd62c5b5d0e74fc379c2ce9e478534995fd6af2571fc9933fc377d1f85f8", poses: 327, scans: 98, trial: "e48a6c6adc394d0393b433d0add4f98c", run: "0e618a992f084033b1b7d817ae226b55" },
  N2: { label: "Repeated Baseline N2", hash: "a4d2c77a28e74d7124429ccc7f8c56010f81802898315bcc1d3de097912028d4", poses: 330, scans: 99, trial: "7928c75e7c88480fa6d6901550fac26c", run: "b67b76d9ddfe4779b151704e71119c16" },
} as const;
export type DatasetId = keyof typeof DATASETS;
export function datasetId(value: string): DatasetId {
  if (value !== "N0" && value !== "N2") throw Error("Unapproved experiment identity");
  return value;
}
export interface Conditions {
  classification: "OBSERVATIONAL_REPEATED_BASELINES";
  robot_model: string; environment: string; map_id: string; profile: string;
  parameters_sha256: string; map_yaml_sha256: string; map_image_sha256: string;
  waypoints: { x: number; y: number; yaw: number }[];
  requested_start: { x: number; y: number; yaw: number };
  measured_runner_start: { x: number; y: number; yaw: number };
  campaign_repetitions: 1 | 2; software_revision: null; random_seed: null;
  exact_localization_initial_state: "UNPROVEN"; host_resource_conditions: "NOT_ESTABLISHED";
}
export interface ManifestV2 extends Manifest {
  schema_version: 2; dataset_id: DatasetId; source_trial_index: 0;
  source_identity: { trial_id: string; run_id: string; original_parameters_sha256: string; original_config_sha256: string; campaign_id: string };
  conditions: Conditions;
  original_validation: Manifest["original_validation"] & {
    action_status: number | null; action_status_reason: string;
    mission_action: { action_type: string; action_name: string; scope: string; owner: string; observer: string; quality: string; pointer: string; event_time_ns: null; recorded_action_stream: false };
  };
}
export interface DatasetV2 extends Dataset { manifest: ManifestV2 }
const names = new Set(["map.pgm.gz", "poses-000.json.gz", "poses-001.json.gz", "poses-002.json.gz", "poses-003.json.gz", "scans-000.json.gz"]);
async function get(id: DatasetId, name: string, limit: number, fetcher: typeof fetch, signal?: AbortSignal) {
  if (name !== "manifest.json" && !names.has(name)) throw Error("Unapproved asset path");
  const response = await fetcher(`/__local_v2/${id.toLowerCase()}/${name}`, { cache: "no-store", redirect: "error", signal });
  if (!response.ok || !response.body) throw Error(`Approved ${id} asset unavailable: ${name}`);
  return readBounded(response.body, limit);
}
export async function loadManifestV2(value: string, fetcher: typeof fetch = fetch, signal?: AbortSignal): Promise<ManifestV2> {
  const id = datasetId(value), pin = DATASETS[id];
  const bytes = await get(id, "manifest.json", 250 * 1024, fetcher, signal);
  if (await sha256(bytes) !== pin.hash) throw Error("Unapproved or corrupt v2 manifest");
  const raw: unknown = JSON.parse(new TextDecoder().decode(bytes));
  validate(raw, schemas.ManifestV2);
  const m = raw as ManifestV2;
  if (m.schema_version !== 2 || m.dataset_id !== id || m.source_trial_index !== 0 || m.source_identity.trial_id !== pin.trial || m.source_identity.run_id !== pin.run || m.publication_review !== "PRIVATE_NOT_APPROVED_FOR_UPLOAD") throw Error("Dataset/version/provenance conflict");
  if (m.assets.length !== names.size || new Set(m.assets.map(a => a.path)).size !== names.size || m.assets.some(a => !names.has(a.path) || a.schema_version !== 1)) throw Error("Unexpected asset inventory");
  return freeze(m);
}
export async function loadDatasetV2(value: string, fetcher: typeof fetch = fetch, signal?: AbortSignal): Promise<DatasetV2> {
  const id = datasetId(value), manifest = await loadManifestV2(id, fetcher, signal);
  const poses: Pose[] = [], scans: Scan[] = []; let pixels: Uint8Array | null = null;
  for (const asset of manifest.assets) {
    const compressed = await get(id, asset.path, asset.bytes, fetcher, signal);
    if (compressed.length !== asset.bytes || await sha256(compressed) !== asset.sha256) throw Error(`Corrupt asset: ${asset.path}`);
    const decoded = await gunzip(compressed);
    if (asset.kind === "map") pixels = parsePgm(decoded, manifest.scene.width, manifest.scene.height);
    else {
      const chunk: unknown = JSON.parse(new TextDecoder().decode(decoded));
      validate(chunk, asset.kind === "poses" ? schemas.PoseChunk : schemas.ScanChunk);
      const samples = (chunk as { samples: (Pose | Scan)[] }).samples;
      if (asset.kind === "poses") poses.push(...samples as Pose[]); else scans.push(...samples as Scan[]);
    }
  }
  if (!pixels || poses.length !== DATASETS[id].poses || scans.length !== DATASETS[id].scans) throw Error("Incomplete approved dataset");
  for (const samples of [poses, scans]) {
    let previous = -1n;
    for (const sample of samples) {
      const t = BigInt(sample.ros_ns);
      if (t <= previous || t < BigInt(manifest.time.recorded_start_ns) || t > BigInt(manifest.time.recorded_end_ns) || Number((t - BigInt(manifest.time.offset_origin_ns)) / 1000n) !== sample.offset_us) throw Error("Invalid playback timestamp");
      previous = t;
      if (sample.segment_id !== null) {
        const segment = manifest.segments.find(s => s.id === sample.segment_id);
        if (!segment || t < BigInt(segment.start_ros_ns) || t > BigInt(segment.end_ros_ns)) throw Error("Invalid playback segment");
      }
    }
  }
  for (const tf of [...poses.map(p => p.transform), ...scans.flatMap(s => [s.map_base, s.base_lidar])]) {
    if (tf && Math.abs(Math.hypot(...tf.quaternion) - 1) > 1e-6) throw Error("Invalid recorded rotation");
  }
  return freeze({ manifest, poses, scans, pixels, trusted: true });
}
