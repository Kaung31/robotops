import { createRoot } from "react-dom/client";
import { Portfolio } from "./Portfolio";
import "../site/site.css";
import "./portfolio.css";
createRoot(document.getElementById("root")!).render(<Portfolio />);
