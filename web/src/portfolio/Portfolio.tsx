import { SiteFooter, SiteHeader } from "../site/SiteChrome";
import { BenchmarkCautions } from "../site/BenchmarkCautions";
import { StripChart } from "../site/StripChart";
import { REPOSITORY } from "../site/release";
import { CONFIGURATIONS, HEADLINE, LIMITS, SUMMARY, TRIALS, type Profile } from "./benchmark";
import { W01_ROUTE } from "./w01-route";

const PROFILES: Profile[] = ["navfn_rpp", "smac_dwb"];
const groups = (pick: (t: typeof TRIALS[number]) => number) => PROFILES.map(id => ({ id, label: CONFIGURATIONS[id].short, values: TRIALS.filter(t => t.profile === id).map(t => ({ id: t.id, value: pick(t) })) }));

// Warehouse v1 geometry from robot_simulation/worlds/warehouse_v1.sdf; route from the W01 dataset.
const RACKS = [2, 4, 6];
const GOALS: [number, number][] = [[3, 0], [3, 7], [5, 7], [5, 0]];
function RouteFigure() {
  return <figure className="route-figure">
    <div className="route-figure-top"><span className="eyebrow">Featured · Warehouse Navigation Benchmark v1</span><span className="route-tag">Recorded data</span></div>
    <svg viewBox="-2.3 -8.75 12.6 10.5" role="img" aria-labelledby="route-title route-desc">
      <title id="route-title">Trial W01 recorded route in the simulated warehouse</title>
      <desc id="route-desc">Top view of a walled warehouse with three racks and two 1.2 metre aisles. Goals sit at both ends of each aisle. The recorded route leaves the start, passes west of the first rack, crosses the north side and returns down the east side, never entering an aisle.</desc>
      <g transform="scale(1,-1)">
        <rect className="route-floor" x="-2" y="-1.5" width="12" height="10" />
        {RACKS.map(x => <rect key={x} className="route-rack" x={x - 0.4} y="1.5" width="0.8" height="4" />)}
        <polyline className="route-line" points={W01_ROUTE.map(([x, y]) => `${x},${y}`).join(" ")} />
        {GOALS.map(([x, y], i) => <circle key={i} className="route-goal" cx={x} cy={y} r="0.2" />)}
        <circle className="route-start" cx="0" cy="0" r="0.24" />
      </g>
      {[3, 5].map(x => <text key={x} className="route-aisle" x={x} y="-3.5" transform={`rotate(-90 ${x} -3.5)`}>1.2 m aisle</text>)}
      {GOALS.map(([x, y], i) => <text key={i} className="route-goal-label" x={x} y={-y + (y > 3 ? -0.42 : 0.72)}>{i + 1}</text>)}
      <text className="route-start-label" x="-0.4" y="0.86">Start / finish</text>
      {RACKS.map((x, i) => <text key={x} className="route-rack-label" x={x} y="-5.85">Rack {i + 1}</text>)}
    </svg>
    <div className="route-legend"><span><i className="route-key-line" />W01 recorded route · NavFn + RPP</span><span><i className="route-key-goal" />Goals 1–4, then home</span></div>
    <figcaption>Every goal sits at the end of an aisle, yet in all six trials both configurations drove around the racks instead of through the aisles. Route downsampled from the recorded W01 dataset.</figcaption>
  </figure>;
}

export function Portfolio() {
  return <div className="site-page portfolio"><a className="skip-link" href="#main">Skip to content</a>
    <SiteHeader current="home" />
    <main id="main">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow">ROS 2 · Nav2 · Gazebo · Open source</p>
          <h1 id="hero-title">Robotics,<br />with <em>evidence.</em></h1>
          <p className="hero-lead">RobotOps is a ROS 2 experimentation and evaluation platform. It runs controlled robot missions, checks the recorded evidence independently, and makes navigation performance explorable through interactive replay.</p>
          <div className="hero-actions"><a className="button-primary" href="/replay.html">Explore the Recorded Lab <span aria-hidden="true">→</span></a><a className="button-secondary" href="#benchmark">See the benchmark results</a></div>
          <ul className="hero-facts" aria-label="Benchmark v1 at a glance">
            <li><strong>{HEADLINE.trials}/{HEADLINE.trials}</strong> trials completed</li>
            <li><strong>{HEADLINE.goals}/{HEADLINE.goals}</strong> goals in every trial</li>
            <li><strong>2</strong> Nav2 configurations</li>
          </ul>
          <p className="hero-note">The lab runs in your browser from recorded data. No robot, simulator or account needed.</p>
        </div>
        <RouteFigure />
      </section>

      <section id="platform" className="band" aria-labelledby="platform-title">
        <div className="band-intro">
          <p className="eyebrow">What RobotOps does</p>
          <h2 id="platform-title" className="section-title">One good run is a demo. Repeatable, checked runs are evidence.</h2>
          <p className="section-lead">Robot navigation is often judged by watching a run or trusting a success flag. That leaves the engineering questions open: did the robot finish where it should, would it do the same again, and is the recording complete enough to check? RobotOps treats every mission as an experiment with a recorded, independently checked result.</p>
        </div>
        <ol className="pipeline">
          <li><span className="step">01</span><h3>Define</h3><p>A campaign fixes the world, saved map, mission goals, Nav2 configuration and number of trials.</p></li>
          <li><span className="step">02</span><h3>Run and record</h3><p>The backend starts a fresh Gazebo and Nav2 stack for each trial, localizes with AMCL, runs the mission and records ROS 2 telemetry to MCAP.</p></li>
          <li><span className="step">03</span><h3>Validate</h3><p>Separately from Nav2's own result, it checks the final pose against the goal, looks for simulated contact and hashes every artifact into a versioned report.</p></li>
          <li><span className="step">04</span><h3>Compare and replay</h3><p>Trials are compared across configurations, then exported as sanitized, hash-pinned datasets that anyone can replay in a browser.</p></li>
        </ol>
      </section>

      <section id="fit" className="band" aria-labelledby="fit-title">
        <div className="band-intro">
          <p className="eyebrow">Where it fits</p>
          <h2 id="fit-title" className="section-title">Built on the ROS 2 toolchain, not instead of it.</h2>
          <p className="section-lead">Gazebo, Nav2, RViz and Foxglove each do one job well. RobotOps drives them and adds the experiment layer around them: what was run, under which configuration, with what verified result.</p>
        </div>
        <dl className="toolchain">
          <div><dt>Gazebo</dt><dd>Simulates the robot, sensors and world.</dd><dd className="adds">RobotOps starts a fresh simulation for every trial and collects contact evidence from it.</dd></div>
          <div><dt>Nav2</dt><dd>Plans paths and drives the robot along them.</dd><dd className="adds">RobotOps runs the same mission under different Nav2 configurations and compares the outcomes.</dd></div>
          <div><dt>RViz</dt><dd>Live visualization for the engineer at the desk.</dd><dd className="adds">An optional companion. Results never depend on it, and campaigns run with it off.</dd></div>
          <div><dt>Foxglove</dt><dd>Deep inspection of recorded robot data.</dd><dd className="adds">RobotOps records standard rosbag2 MCAP and keeps the experiment context: trial, configuration and verdict.</dd></div>
          <div className="toolchain-self"><dt>RobotOps</dt><dd>Campaign orchestration, independent validation, versioned evidence and a public read-only replay lab.</dd></div>
        </dl>
      </section>

      <section id="benchmark" className="band benchmark" aria-labelledby="benchmark-title">
        <div className="band-intro">
          <p className="eyebrow">Featured result · October 2026</p>
          <h2 id="benchmark-title" className="section-title">Warehouse Navigation Benchmark v1</h2>
          <p className="section-lead">Two complete Nav2 setups ran the same five-goal warehouse mission, three times each, through RobotOps' normal campaign pipeline.</p>
        </div>
        <dl className="benchmark-setup">
          <div><dt>World</dt><dd>Simulated warehouse: three racks, two 1.2 m aisles</dd></div>
          <div><dt>Mission</dt><dd>Four goals at the aisle ends, then back to the start</dd></div>
          <div><dt>Configurations</dt><dd><i className="swatch navfn_rpp" />NavFn planner + Regulated Pure Pursuit controller<br /><i className="swatch smac_dwb" />Smac 2D planner + DWB controller</dd></div>
          <div><dt>Trials</dt><dd>3 per configuration, order AB/BA/AB, fresh stack each time</dd></div>
        </dl>
        <ul className="benchmark-stats">
          <li><strong>6/6</strong><span>trials completed</span></li>
          <li><strong>5/5</strong><span>goals reached in every trial</span></li>
          <li><strong>6/6</strong><span>final poses verified within {LIMITS.xy.toFixed(2)} m and {LIMITS.yaw.toFixed(2)} rad</span></li>
          <li><strong>0</strong><span>contacts observed on monitored collision bodies</span></li>
        </ul>
        <div className="config-cards">
          {PROFILES.map(p => <article key={p} className={`config-card ${p}`}>
            <h3><i className={`swatch ${p}`} />{CONFIGURATIONS[p].name}</h3>
            <dl>
              <div><dt>Mean mission time</dt><dd><strong>{SUMMARY[p].seconds.toFixed(2)} s</strong><span>range {SUMMARY[p].secondsMin.toFixed(2)}–{SUMMARY[p].secondsMax.toFixed(2)} s</span></dd></div>
              <div><dt>Mean final heading error</dt><dd><strong>{SUMMARY[p].yawDeg.toFixed(1)}°</strong><span>{SUMMARY[p].yawRad.toFixed(3)} rad</span></dd></div>
              <div><dt>Mean final position error</dt><dd><strong>{SUMMARY[p].xy.toFixed(3)} m</strong></dd></div>
              <div><dt>Mean path length</dt><dd><strong>{SUMMARY[p].path.toFixed(2)} m</strong><span>odometry</span></dd></div>
            </dl>
          </article>)}
        </div>
        <div className="benchmark-charts">
          <StripChart title="Mission time per trial, seconds" note="Axis starts at 131 s to separate the clusters" unit="s" digits={2} min={131} max={139} ticks={[131, 133, 135, 137, 139]} tickDigits={0} groups={groups(t => t.seconds)} />
          <StripChart title="Final heading error per trial, radians" note="Lower is closer to the goal heading" unit="rad" digits={3} min={0} max={0.3} ticks={[0, 0.1, 0.2, 0.3]} tickDigits={1} groups={groups(t => t.yaw)} references={[{ value: LIMITS.nav2Yaw, label: "Nav2 yaw goal tolerance" }, { value: LIMITS.yaw, label: "RobotOps validation limit" }]} />
        </div>
        <div className="findings">
          <h3>What the six trials show</h3>
          <ul>
            <li><strong>Smac 2D + DWB finished every trial sooner,</strong> {HEADLINE.faster} s ({HEADLINE.fasterPercent}%) faster on average, on a slightly shorter path.</li>
            <li><strong>NavFn + RPP stopped much closer to the goal heading,</strong> about {SUMMARY.navfn_rpp.yawDeg.toFixed(0)}° against {SUMMARY.smac_dwb.yawDeg.toFixed(0)}°. DWB's errors sit just under Nav2's {LIMITS.nav2Yaw.toFixed(2)} rad yaw tolerance, consistent with it stopping as soon as it is inside that tolerance.</li>
            <li><strong>Runs were repeatable:</strong> each configuration's three mission times fell within {HEADLINE.navfnSpread} s (NavFn + RPP) and {HEADLINE.smacSpread} s (Smac 2D + DWB).</li>
          </ul>
        </div>
        <BenchmarkCautions id="benchmark-caution" />
        <a className="button-primary benchmark-cta" href="/replay.html">Replay all six trials <span aria-hidden="true">→</span></a>
      </section>

      <section id="engineering" className="band" aria-labelledby="engineering-title">
        <div className="band-intro">
          <p className="eyebrow">What went into it</p>
          <h2 id="engineering-title" className="section-title">Robotics engineering and software engineering, in one system.</h2>
        </div>
        <div className="skill-columns">
          <article>
            <h3>Robotics</h3>
            <ul>
              <li>Differential-drive robot in URDF/Xacro with ros2_control, using mock and Gazebo Harmonic backends behind the same ROS 2 interfaces.</li>
              <li>Stamped velocity-command mux with a command guard and timeouts, so stale commands stop the robot.</li>
              <li>SLAM Toolbox mapping, saved maps and AMCL localization for repeatable navigation.</li>
              <li>Two Nav2 configurations and multi-waypoint missions through a custom ExecuteMission action.</li>
              <li>C++ nodes for Gazebo contact evidence, simulator lifecycle and sensor-freshness diagnostics.</li>
              <li>Custom simulated worlds, including the warehouse, built from original geometry.</li>
            </ul>
          </article>
          <article>
            <h3>Software</h3>
            <ul>
              <li>FastAPI campaign service with SQLite history, an exclusive runtime lease and crash recovery.</li>
              <li>Independent validation and versioned, integrity-hashed experiment reports.</li>
              <li>React and TypeScript operations dashboard with live map, LiDAR, teleoperation, readiness, campaigns and reports (local only).</li>
              <li>Python exporters that turn MCAP recordings into sanitized datasets, plus an audit that re-decodes each recording and compares every exported sample.</li>
              <li>This static Recorded Lab: React and Three.js, checking every file's SHA-256 before display and failing closed.</li>
              <li>GitHub Actions CI with lint, unit, web and headless Gazebo system tests.</li>
            </ul>
          </article>
        </div>
        <ul className="stack" aria-label="Technology used">
          {["ROS 2 Jazzy", "Nav2", "Gazebo Harmonic", "ros2_control", "SLAM Toolbox", "AMCL", "rosbag2 + MCAP", "URDF / Xacro", "C++", "Python", "FastAPI", "SQLite", "React", "TypeScript", "Three.js", "Vite", "GitHub Actions"].map(t => <li key={t}>{t}</li>)}
        </ul>
      </section>

      <section id="challenges" className="band" aria-labelledby="challenges-title">
        <div className="band-intro">
          <p className="eyebrow">Engineering challenges</p>
          <h2 id="challenges-title" className="section-title">Problems worth solving properly.</h2>
        </div>
        <div className="challenge-grid">
          <article><h3>"Succeeded" is not a verdict</h3><p>A successful Nav2 action means the action finished, not that the robot ended up in the right place. RobotOps keeps three separate verdicts (navigation result, final-pose check and contact evidence) and never lets one stand in for another.</p></article>
          <article><h3>A crash after a successful run</h3><p>In W03 the simulator crashed during shutdown, after the trial's evidence was safely written. Under load, the backend sometimes tracked a short-lived wrapper process, then fell back to a signal that reached every node twice (reproduced in 24 of 40 loaded starts). Cleanup now requires clean exit codes, and each trial records a shutdown report. The original result stays disclosed rather than quietly rerun.</p></article>
          <article><h3>A benchmark that found its own blind spot</h3><p>The goals were placed at the aisle ends to make the robot drive the 1.2 m aisles. Both configurations went around the racks instead. That is reported as the key finding rather than hidden, and a world that forces aisle driving is next on the roadmap.</p></article>
          <article><h3>Publishing evidence safely</h3><p>Raw recordings contain machine paths and far more data than a browser needs. Exporters produce downsampled, sanitized datasets pinned by SHA-256. The lab verifies every manifest and file before showing anything, and the public site is static, with no API or robot connection.</p></article>
        </div>
      </section>

      <section id="architecture" className="band" aria-labelledby="architecture-title">
        <div className="band-intro">
          <p className="eyebrow">Architecture</p>
          <h2 id="architecture-title" className="section-title">Shared interfaces. A hard boundary to the public site.</h2>
          <p className="section-lead">ROS remains the source of truth for live robot state, and ros2_control separates application code from simulated or physical hardware. The public site sits on the far side of an offline export: nothing on it can reach a robot.</p>
        </div>
        <div className="architecture-diagram" role="group" aria-label="Local engineering platform and public read-only lab">
          <div className="architecture-lane">
            <span className="lane-label">Local engineering platform</span>
            <div className="architecture-box">React + TypeScript dashboard<small>Operations · campaigns · reports</small></div>
            <span className="lane-arrow" aria-hidden="true">↓</span>
            <div className="architecture-box">FastAPI campaign service<small>Orchestration · validation · SQLite history</small></div>
            <span className="lane-arrow" aria-hidden="true">↓</span>
            <div className="architecture-box">ROS 2 Jazzy<small>Mission manager · Nav2 · AMCL · ros2_control</small></div>
            <span className="lane-arrow" aria-hidden="true">↓</span>
            <div className="architecture-box">Gazebo Harmonic or mock hardware<small>A physical robot is planned behind the same interfaces</small></div>
          </div>
          <div className="architecture-divider"><span>rosbag2 MCAP + reports</span><span aria-hidden="true">→</span><span>sanitize · downsample · hash</span></div>
          <div className="architecture-lane public-lane">
            <span className="lane-label">Public, read-only</span>
            <div className="architecture-box">Hash-pinned static datasets<small>Manifest · map · pose and LiDAR chunks</small></div>
            <span className="lane-arrow" aria-hidden="true">↓</span>
            <div className="architecture-box">Recorded Lab in the browser<small>React + Three.js · replay · comparison · visitor checks</small></div>
            <p>No connection to ROS, the backend or any robot. Served as static files.</p>
          </div>
        </div>
      </section>

      <section className="lab-invitation" aria-labelledby="lab-title">
        <div>
          <p className="eyebrow">Recorded Lab</p>
          <h2 id="lab-title" className="section-title">Watch the robot. Check the numbers.</h2>
          <p>Replay any of the six warehouse trials with synchronized map, LiDAR and 3D views, compare the two configurations, and test the original measurements against your own acceptance limits. Your checks never change the recorded results.</p>
        </div>
        <a className="button-primary" href="/replay.html">Open the Recorded Lab <span aria-hidden="true">→</span></a>
      </section>

      <section id="status" className="band status" aria-labelledby="status-title">
        <div className="band-intro">
          <p className="eyebrow">Project status</p>
          <h2 id="status-title" className="section-title">What's done, and what isn't yet.</h2>
        </div>
        <div className="status-columns">
          <article><h3>Working today, in simulation</h3><ul>
            <li>Mapping, saved-map localization and multi-goal Nav2 missions</li>
            <li>Backend campaigns with validation, contact evidence and reports</li>
            <li>Warehouse Navigation Benchmark v1 (exploratory)</li>
            <li>This read-only Recorded Lab</li>
          </ul></article>
          <article><h3>Not done yet</h3><ul>
            <li>A world that forces narrow-aisle driving, and an easy-to-extreme world ladder</li>
            <li>LiDAR fault injection inside campaigns (the fault relay exists but is not wired in)</li>
            <li>A physical robot through the same ROS 2 interfaces</li>
            <li>Machine-learning anomaly detection (not implemented)</li>
          </ul></article>
        </div>
        <p className="status-source">Known issues and the roadmap are tracked in the <a href={REPOSITORY} target="_blank" rel="noopener noreferrer">repository</a>.</p>
      </section>
    </main>
    <SiteFooter />
  </div>;
}
