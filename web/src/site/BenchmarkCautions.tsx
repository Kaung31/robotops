// The Warehouse Navigation Benchmark v1 disclosures, worded once for both pages.
export function BenchmarkCautions({ id }: { id: string }) {
  return <aside className="caution" aria-labelledby={id}>
    <h3 id={id}>Read these results with care</h3>
    <ul>
      <li className="route-note"><strong>No narrow-aisle claim.</strong> Both configurations drove around the rack block on the perimeter and never entered the 1.2 m aisles, so v1 does not show narrow-aisle navigation.</li>
      <li><strong>Exploratory.</strong> Three trials per configuration in one simulated environment show repeatability, not statistical significance or general superiority.</li>
      <li><strong>Bundles, not single algorithms.</strong> The planner and the controller both differ between the configurations, so no difference can be attributed to either alone.</li>
      <li><strong>Not formally qualified.</strong> The trials ran as normal backend campaigns, not through the stricter W3/W4 qualification process, which was not completed.</li>
      <li><strong>Localization, not ground truth.</strong> Final errors compare the robot's own AMCL localization with the goal; simulator ground truth was not recorded for these runs.</li>
      <li className="teardown-note"><strong>W03 teardown crash.</strong> Navigation succeeded and the evidence was finalized, then Gazebo crashed while the stack shut down. Its results are unchanged and disclosed; the shutdown bug has since been fixed.</li>
    </ul>
  </aside>;
}
