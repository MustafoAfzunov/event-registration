import "@fontsource-variable/inter";
import "@fontsource-variable/plus-jakarta-sans";
import "@fontsource-variable/material-symbols-outlined/fill.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing from index.html");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
