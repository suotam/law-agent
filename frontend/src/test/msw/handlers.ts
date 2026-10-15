import type { RequestHandler } from "msw";

// Per-test handlers are registered with server.use(); this baseline stays empty
// so an unhandled request fails loudly instead of silently returning nothing.
export const handlers: RequestHandler[] = [];
