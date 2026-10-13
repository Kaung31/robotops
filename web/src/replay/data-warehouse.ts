import schemas from "./schema-warehouse-v1.json";
import { freeze, gunzip, parsePgm, readBounded, sha256, validate, type Dataset, type Manifest, type Pose, type Scan } from "./data";

// Exact private Warehouse Benchmark v1 exports. A manifest is accepted only by
// its pinned hash; chunk inventories are derived from the pinned sample counts.
export const PROFILE_LABELS = { navfn_rpp: "NavFn + Regulated Pure Pursuit", smac_dwb: "Smac 2D + DWB" } as const;
export const PROFILE_SHORT = { navfn_rpp: "NavFn + RPP", smac_dwb: "Smac 2D + DWB" } as const;
export type Profile = keyof typeof PROFILE_LABELS;
export const WAREHOUSE = {
  W01: { profile: "navfn_rpp", hash: "2c9007b91dd0d09c76d83e3f948303c678daf547a4b492860d6109d7106a7345", poses: 2357, scans: 707, trial: "7fcfc1078d3845e1ab9ce2a5cb68f238", run: "39fb7bf2ef7d4f5aa1e7561a2042dc6b" },
  W02: { profile: "smac_dwb", hash: "6cc4928691c9f6e5fa47cee749c60a8f8f354e05dac53db16002cd59a4481561", poses: 2283, scans: 685, trial: "13af9f02a5b847818ca5b75b3988be31", run: "a18d2c8c825b46bd95c7e37ad4762856" },
  W03: { profile: "smac_dwb", hash: "e1cce11951245ec85c9a7e00b3d5f5b48bc18c1fd87c820f81bb409d307b38ca", poses: 2269, scans: 681, trial: "10a260b7c3ca4aa3a40fdd15e8cdaa0e", run: "ca866526404648f5a57591a21406226b" },
  W04: { profile: "navfn_rpp", hash: "5804cbb05697b7ac6b06991f95f0fc92538e77841f99bbe7995f77d85da31313", poses: 2365, scans: 710, trial: "e51661a5d3114a0e9e185da86b24297d", run: "33bc3f4ebef941afb55c98fc47e3da43" },
  W05: { profile: "navfn_rpp", hash: "8a3e4b9c51686dc2bdb737cf6c4b842469f63ef5613568a52a2096c0d3066e4b", poses: 2363, scans: 709, trial: "807f99063d5e4d6e9c4d78d391361c1c", run: "552859aa1395479da67c61e65b07c204" },
  W06: { profile: "smac_dwb", hash: "efdfaab4b5a2b25da3c7cfe81d250c7b60d942850d3f8b3ea315aec9de65e4a7", poses: 2289, scans: 687, trial: "27d412204f4543839b7bbb0bce27e738", run: "cfdf627021f9490ea89ef9f21d4cc140" },
} as const satisfies Record<string, { profile: Profile; hash: string; poses: number; scans: number; trial: string; run: string }>;
export type WarehouseId = keyof typeof WAREHOUSE;
export const WAREHOUSE_IDS = Object.keys(WAREHOUSE) as WarehouseId[];
export function isWarehouseId(value: string): value is WarehouseId {
  return Object.hasOwn(WAREHOUSE, value);
}
export function warehouseId(value: string): WarehouseId {
  if (!isWarehouseId(value)) throw Error("Unapproved experiment identity");
  return value;
}
export function warehouseLabel(id: WarehouseId): string {
  return `${id} · ${PROFILE_SHORT[WAREHOUSE[id].profile]}`;
}
export interface WarehouseManifest extends Manifest {
  schema_version: 3; dataset_id: WarehouseId; source_trial_index: 0;
  time: Manifest["time"] & { result_finalized_ns: string; dispatch_ns: string; final_observation_ns: string };
  source_identity: { trial_id: string; run_id: string; campaign_id: string; report_id: string; profile: Profile; original_parameters_sha256: string; original_config_sha256: string };
  conditions: { classification: "EXPLORATORY_BENCHMARK_V1"; profile: Profile; environment: string; map_id: string; robot_model: string; waypoints: { x: number; y: number; yaw: number }[]; parameters_sha256: string; map_yaml_sha256: string; map_image_sha256: string; requested_start: { x: number; y: number; yaw: number }; measured_runner_start: { x: number; y: number; yaw: number } };
  benchmark: { id: string; slot: WarehouseId; pair: number; profile_trial: number; order: string; matrix_sha256: string; adoption: string; execution_path: string; qualification: "NOT_QUALIFIED" };
  teardown: { status: "NO_CHILD_FAILURE_LOGGED" | "CRASHED_AFTER_EVIDENCE_FINALIZED"; detail: string | null; original_campaign_cleanup_confirmed: true; original_cleanup_check_included_exit_status: false; evidence_finalized_before_teardown: true };
  recorder_loss: { accounting_complete: true; transport_lost_messages: 0; loss_reports: 0 };
  original_report_limitations: string[];
  original_validation: Manifest["original_validation"] & { pose_policy: { xy_tolerance_m: number; yaw_tolerance_rad: number }; action_status: number | null; action_status_reason: string; mission_action:{ action_type: string; action_name: string; scope: string; owner: string; observer: string; quality: string; pointer: string; event_time_ns: null; recorded_action_stream: false } };
}
export interface WarehouseDataset extends Dataset { manifest: WarehouseManifest }
export function assetNames(id: WarehouseId): string[] {
  const chunks = (kind: string, samples: number) => Array.from({ length: Math.ceil(samples / 100) }, (_, i) => `${kind}-${String(i).padStart(3, "0")}.json.gz`);
  return ["map.pgm.gz", ...chunks("poses", WAREHOUSE[id].poses), ...chunks("scans", WAREHOUSE[id].scans)];
}
async function get(id: WarehouseId, name: string, limit: number, fetcher: typeof fetch, signal?: AbortSignal) {
  if (name !== "manifest.json" && !assetNames(id).includes(name)) throw Error("Unapproved asset path");
  const response = await fetcher(`/__local_v2/${id.toLowerCase()}/${name}`, { cache: "no-store", redirect: "error", signal });
  if (!response.ok || !response.body) throw Error(`Approved ${id} asset unavailable: ${name}`);
  return readBounded(response.body, limit);
}
export async function loadWarehouseManifest(value: string, fetcher: typeof fetch = fetch, signal?: AbortSignal): Promise<WarehouseManifest> {
  const id = warehouseId(value), pin = WAREHOUSE[id];
  const bytes = await get(id, "manifest.json", 250 * 1024, fetcher, signal);
  if (await sha256(bytes) !== pin.hash) throw Error("Unapproved or corrupt warehouse manifest");
  const raw: unknown = JSON.parse(new TextDecoder().decode(bytes));
  validate(raw, schemas.WarehouseManifest);
  const m = raw as WarehouseManifest;
  if (m.schema_version !== 3 || m.dataset_id !== id || m.benchmark.slot !== id || m.source_identity.trial_id !== pin.trial || m.source_identity.run_id !== pin.run || m.source_identity.profile !== pin.profile || m.publication_review !== "PRIVATE_NOT_APPROVED_FOR_UPLOAD") throw Error("Dataset/version/provenance conflict");
  const names = assetNames(id);
  if (m.assets.length !== names.length || m.assets.some((a, i) => a.path !== names[i] || a.schema_version !== 1)) throw Error("Unexpected asset inventory");
  if ((m.teardown.status === "CRASHED_AFTER_EVIDENCE_FINALIZED") !== m.limitations.includes("TEARDOWN_CRASH_AFTER_FINALIZATION")) throw Error("Teardown disclosure conflict");
  return freeze(m);
}
export async function loadWarehouseDataset(value: string, fetcher: typeof fetch = fetch, signal?: AbortSignal): Promise<WarehouseDataset> {
  const id = warehouseId(value), manifest = await loadWarehouseManifest(id, fetcher, signal);
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
  if (!pixels || poses.length !== WAREHOUSE[id].poses || scans.length !== WAREHOUSE[id].scans) throw Error("Incomplete approved dataset");
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
