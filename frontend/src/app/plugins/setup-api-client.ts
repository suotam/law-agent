import { clearSession, getToken } from "@/features/auth";
import { setupApiClientInterceptor } from "@/lib/api-client";

/*
 * Installed once on import rather than from a provider effect: the chat transport reads
 * the same two functions outside React, so there is nothing to re-bind on render. Both
 * the app entry point and the test setup import this module, so the two agree by
 * construction instead of by duplicated wiring.
 */
setupApiClientInterceptor(getToken, clearSession);
