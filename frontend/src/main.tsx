import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ToastProvider } from "./components/toast";
import { I18nProvider, systemLang } from "./i18n";
import { StoreProvider } from "./lib/store";
import "./styles.css";

// Prevent the WebView's default context menu / file drop from navigating away.
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider initial={systemLang()}>
      <StoreProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </StoreProvider>
    </I18nProvider>
  </StrictMode>,
);
