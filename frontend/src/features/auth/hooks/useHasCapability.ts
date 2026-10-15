import { useAuth } from "./useAuth";
import type { RoleCapability } from "../types";

/*
 * The single copy of "may the signed-in caller do X": superuser bypass plus
 * the capability itself, exactly what RequireCapability enforces at the
 * route level. Components must use this rather than re-deriving the
 * predicate inline, so the two can never drift apart when the capability
 * model changes.
 */
export const useHasCapability = (capability: RoleCapability): boolean => {
  const { user } = useAuth();
  return user !== undefined && (user.is_superuser || user.capabilities.includes(capability));
};
