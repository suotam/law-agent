import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import "./assets/styles/globals.css";
import "@/config/i18n";
import "@/app/plugins/setup-api-client";
import { router } from "@/app/router";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
