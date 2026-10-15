import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./msw/server";
// Imported for its side effect: i18n.init() runs on import, so components can
// call useTranslation without every test wrapping them in a provider.
import "@/config/i18n";

// The app reads the API base URL from the environment; tests need a stable origin
// so MSW handlers can match absolute URLs. Set before the api client is imported,
// since it reads the variable at module scope.
import.meta.env.VITE_BACKEND_API_URL = "http://api.test";

// Same auth wiring the app installs, so tests exercise the real 401 handling.
await import("@/app/plugins/setup-api-client");

/*
 * In the browser axios goes through XMLHttpRequest; under jsdom that path is intercepted by
 * msw's XHR interceptor, which is Node-version sensitive: multipart FormData bodies never get
 * their response delivered on Node 24, blob responses hang on Node 22. msw's fetch
 * interception has neither problem, and what the tests assert on — URL, headers, body,
 * status handling — is identical across adapters, so tests use the fetch adapter.
 */
const { apiClient } = await import("@/lib/api-client");
apiClient.defaults.adapter = "fetch";

/*
 * jsdom ships no ResizeObserver and never lays anything out, so the chat's stick-to-bottom
 * observer has nothing to observe. The stub keeps the component mountable; the scrolling
 * behaviour itself is not something jsdom could assert on.
 */
globalThis.ResizeObserver = class {
  observe() {
    return undefined;
  }
  unobserve() {
    return undefined;
  }
  disconnect() {
    return undefined;
  }
};

/*
 * jsdom has no matchMedia either. Its window is 1024px wide, so every min-width breakpoint the
 * app asks about is a desktop one — which is the layout the tests are written against.
 */
window.matchMedia = (query: string) =>
  ({
    matches: true,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
    addListener: () => undefined,
    removeListener: () => undefined,
  }) as MediaQueryList;

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  localStorage.clear();
});

afterAll(() => {
  server.close();
});
