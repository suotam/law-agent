import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { renderWithProviders } from "@/test/render";
import { Loading } from "@/components/Loading";

test("the test harness renders a component with providers", () => {
  renderWithProviders(<Loading />);

  expect(screen.getByRole("status")).toBeInTheDocument();
});
