import type { ReactElement } from "react";
import { render, type RenderResult } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";

type RenderOptions = {
  route?: string;
};

export const renderWithProviders = (
  ui: ReactElement,
  options: RenderOptions = {},
): RenderResult => {
  // A fresh client per test keeps cached queries from leaking between cases.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[options.route ?? "/"]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};
