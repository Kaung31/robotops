import type { ReactNode } from "react";
import { BenchmarkCautions } from "../site/BenchmarkCautions";
import type { DatasetId } from "./data-v2";

// Page structure of the Recorded Lab: understand -> results -> watch -> compare -> inspect.
export const JOURNEY = [["experiment", "The experiment"], ["results", "Results"], ["replay", "Watch the robot"], ["compare", "Compare configurations"], ["evidence", "Inspect the evidence"]] as const;

export function SectionHeading({ id, step, eyebrow, title, children, aside }: { id: string; step?: number; eyebrow: string; title: ReactNode; children?: ReactNode; aside?: ReactNode }) {
  return <div className="lab-section-heading"><div>
    <p className="eyebrow">{step && <span className="step-number">{String(step).padStart(2, "0")}</span>}{eyebrow}</p>
    <h2 id={id} className="section-title" tabIndex={-1}>{title}</h2>
    {children && <p className="section-lead">{children}</p>}
  </div>{aside}</div>;
}

export function LabIntro({ status, overview }: { status: string; overview: boolean }) {
  return <section className="lab-intro" aria-labelledby="lab-title">
    <div className="lab-intro-copy">
      <p className="eyebrow">RobotOps Recorded Lab</p>
      <h1 id="lab-title">Watch the robot. <em>Check the evidence.</em></h1>
      <p className="section-lead">Replay six recorded trials from Warehouse Navigation Benchmark v1, see their original results, compare the two Nav2 configurations and test the measurements against your own limits.</p>
      <ul className="lab-facts"><li>Recorded simulation data</li><li>Read-only: no robot, simulator or server connected</li><li>Every file hash-checked before display</li></ul>
      <p className="lab-status">{status}{overview && <> · <a href="/">New to RobotOps? Read the project overview</a></>}</p>
    </div>
    <nav className="lab-journey" aria-label="Lab sections"><ol>
      {JOURNEY.map(([id, label], i) => <li key={id}><a href={`#${id}`}><span>{i + 1}</span>{label}</a></li>)}
    </ol><a className="journey-extra" href="#baselines">Earlier baseline experiments</a></nav>
  </section>;
}

export function ExperimentSection() {
  return <section id="experiment" className="lab-section" aria-labelledby="experiment-title">
    <SectionHeading id="experiment-title" step={1} eyebrow="The experiment" title="Same mission, two Nav2 configurations">
      A simulated differential-drive robot leaves its start point, visits four goals at the ends of the two 1.2 m aisles between three warehouse racks, then returns to the start. A mission succeeds only when all five goals are reached.
    </SectionHeading>
    <div className="experiment-grid">
      <div className="experiment-explainer">
        <h3>What was compared</h3>
        <dl className="config-explainer">
          <div><dt><i className="swatch navfn_rpp" />NavFn + Regulated Pure Pursuit</dt><dd>NavFn plans a route across the map; Regulated Pure Pursuit steers along it, slowing for tight turns and nearby obstacles.</dd></div>
          <div><dt><i className="swatch smac_dwb" />Smac 2D + DWB</dt><dd>Smac 2D plans the route; DWB tries many candidate velocities each control cycle and picks the one that best follows the route while avoiding obstacles.</dd></div>
        </dl>
        <h3>How each trial ran</h3>
        <ul>
          <li>Three trials per configuration, in the order AB/BA/AB, each on a fresh Gazebo and Nav2 stack.</li>
          <li>The robot localized on a saved map with AMCL, and its ROS 2 telemetry was recorded to MCAP.</li>
          <li>After each mission, RobotOps checked the result independently of Nav2: final position and heading against the goal (limits 0.20 m and 0.25 rad) and simulated contact between the robot and the world.</li>
        </ul>
      </div>
      <BenchmarkCautions id="lab-caution" />
    </div>
  </section>;
}

export function BaselineBanner({ id }: { id: DatasetId }) {
  return <section className="benchmark-note baseline-note" aria-label="Baseline context and disclosures">
    <p><strong>Earlier baseline {id}</strong> · NavFn + Regulated Pure Pursuit · two-goal round trip in the smaller mapping_lab world</p>
    <ul className="benchmark-disclosures">
      <li>Not part of Warehouse Navigation Benchmark v1. N0 and N2 repeat one configuration; they are not an algorithm comparison.</li>
      <li>Partial recording: part of the mission was not captured. Gaps are shown on the timeline, never filled in.</li>
    </ul>
  </section>;
}

export function BaselinesSection({ selected, onReplay, children }: { selected: string; onReplay: (id: DatasetId) => void; children: ReactNode }) {
  return <section id="baselines" className="lab-section baselines" aria-labelledby="baselines-title">
    <SectionHeading id="baselines-title" eyebrow="Earlier baseline experiments" title="N0 and N2: one configuration, run twice">
      Before the warehouse benchmark, the robot ran a short two-goal round trip in a smaller test world. N0 and N2 are two recorded repetitions with the same NavFn + RPP configuration. They show run-to-run variation, not an algorithm comparison.
    </SectionHeading>
    <p className="coverage-warning"><strong>Partial recordings.</strong> Part of each mission was not captured, so these replays have gaps. The gaps are shown rather than filled in.</p>
    <div className="baseline-actions">{(["N0", "N2"] as const).map(id => <button key={id} type="button" className="replay-button" onClick={() => onReplay(id)} aria-label={`Replay ${id} in the player`}>{selected === id ? `Showing ${id}` : `Replay ${id}`}</button>)}</div>
    {children}
  </section>;
}
