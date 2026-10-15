import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { FileBrowser } from "../components/FileBrowser";
import { file, level, orgFilesHandlers, root } from "./fixtures";

const listing = orgFilesHandlers([root("f1", "Smlouvy", { permission: "read" })], {
  f1: level([], [file("d1", "smlouva.pdf", { permission: "read" })]),
});

describe("download", () => {
  const createObjectURL = vi.fn(() => "blob:mock");
  const revokeObjectURL = vi.fn();

  beforeEach(() => {
    // jsdom implements neither of these; the click itself is what the test asserts on.
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
  });

  afterEach(() => vi.restoreAllMocks());

  it("fetches the bytes and hands them to a download anchor", async () => {
    const user = userEvent.setup();
    const clicked = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clicked);
    server.use(
      ...listing,
      http.get("http://api.test/me/org-files/documents/d1/download", () =>
        HttpResponse.arrayBuffer(new ArrayBuffer(8), {
          headers: { "Content-Type": "application/pdf" },
        }),
      ),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    await user.click(await screen.findByRole("button", { name: "Akce položky" }));
    await user.click(await screen.findByRole("menuitem", { name: "Stáhnout" }));

    await waitFor(() => expect(clicked).toHaveBeenCalledTimes(1));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock");
  });

  it("reports a failed download", async () => {
    const user = userEvent.setup();
    server.use(
      ...listing,
      http.get(
        "http://api.test/me/org-files/documents/d1/download",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    await user.click(await screen.findByRole("button", { name: "Akce položky" }));
    await user.click(await screen.findByRole("menuitem", { name: "Stáhnout" }));

    expect(await screen.findByText("Soubor se nepodařilo stáhnout.")).toBeInTheDocument();
  });
});
