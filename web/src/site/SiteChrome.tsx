import { RELEASE, REPOSITORY } from "./release";

// Shared header and footer for the static website. Page links only: no live
// state, no operational routes.
export function SiteHeader({ current }: { current: "home" | "lab" }) {
  return <header className="site-header">
    <a className="site-brand" href="/" aria-label="RobotOps overview"><span className="site-brand-mark" aria-hidden="true">R</span>RobotOps</a>
    <nav className="site-nav" aria-label="Site">
      <a className="site-nav-section" href="/#platform">Platform</a>
      <a className="site-nav-section" href="/#benchmark">Benchmark</a>
      <a className="site-nav-section" href="/#engineering">Engineering</a>
      {current === "lab" && <a className="site-nav-overview" href="/">Overview</a>}
      <a className="site-nav-lab" href="/replay.html" aria-current={current === "lab" ? "page" : undefined}>Recorded Lab</a>
      <a className="site-nav-source" href={REPOSITORY} target="_blank" rel="noopener noreferrer">GitHub<span aria-hidden="true"> ↗</span></a>
    </nav>
  </header>;
}

export function SiteFooter() {
  const licence = RELEASE.datasetLicence;
  return <footer className="site-footer">
    <div className="site-footer-brand"><a className="site-brand" href="/"><span className="site-brand-mark" aria-hidden="true">R</span>RobotOps</a><p>Robotics, with evidence. A ROS 2 experimentation and evaluation platform.</p></div>
    <nav className="site-footer-links" aria-label="Footer">
      <a href="/">Project overview</a>
      <a href="/replay.html">Recorded Lab</a>
      <a href={REPOSITORY} target="_blank" rel="noopener noreferrer">Source on GitHub<span aria-hidden="true"> ↗</span></a>
      {licence && <a href={licence.href}>Dataset licence</a>}
      <a href="/THIRD_PARTY_NOTICES.txt">Third-party notices</a>
    </nav>
    <p className="site-release">{RELEASE.status}</p>
  </footer>;
}
