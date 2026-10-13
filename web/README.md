# RobotOps web

React/TypeScript Milestone 7 dashboard. The Vite development server proxies `/api`
to the local FastAPI service.

```bash
npm install
npm run typecheck
npm run dev
```

The browser is presentation/command-request state only; ROS remains authoritative.

## Static website

`npm run build:site` builds the public homepage (`portfolio.html` → `index.html`)
and the read-only Recorded Lab (`replay.html`) into `dist/site`, with no proxy,
API client or recordings. Shared header, footer, disclosures and charts live in
`src/site/`. Structure and data sources: `docs/plans/website-experience.md`.
