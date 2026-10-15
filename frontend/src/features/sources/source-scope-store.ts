import { create } from "zustand";
import type { ScopeValue } from "@/features/conversations";

export const SCOPE_VALUES: readonly ScopeValue[] = ["laws", "org_files"];

type SourceScopeState = {
  scope: ScopeValue[];
  /** True once a conversation exists: its scope is frozen server-side and cannot be changed. */
  isLocked: boolean;
  toggle: (value: ScopeValue) => void;
  lock: () => void;
  reset: (scope?: ScopeValue[]) => void;
};

// Kept in SCOPE_VALUES order so the request body is stable and tests can assert on it.
const sortScope = (scope: ScopeValue[]): ScopeValue[] =>
  SCOPE_VALUES.filter((value) => scope.includes(value));

export const useSourceScopeStore = create<SourceScopeState>()((set) => ({
  scope: [],
  isLocked: false,
  toggle: (value) =>
    set((state) => {
      if (state.isLocked) return state;

      const next = state.scope.includes(value)
        ? state.scope.filter((entry) => entry !== value)
        : [...state.scope, value];

      return { scope: sortScope(next) };
    }),
  lock: () => set({ isLocked: true }),
  reset: (scope = []) => set({ scope: sortScope(scope), isLocked: false }),
}));

export const getScope = (): ScopeValue[] => useSourceScopeStore.getState().scope;

export const lockScope = (): void => useSourceScopeStore.getState().lock();
