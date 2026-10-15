import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { FileBrowser } from "../components/FileBrowser";
import type { OrgFileResponse } from "../types";
import { level, orgFilesHandlers, root } from "./fixtures";

const listing = (files: OrgFileResponse[] = []) =>
  orgFilesHandlers([root("f1", "Smlouvy", { permission: "write" })], {
    // The array is read on every request, so an upload's effect shows up in the refresh.
    f1: level([], files),
  });

const pdf = (name: string, sizeBytes = 10) =>
  new File([new Uint8Array(sizeBytes)], name, { type: "application/pdf" });

const pickFile = async (user: ReturnType<typeof userEvent.setup>, file: File) => {
  const input = await screen.findByLabelText("Nahrát soubor");
  await user.upload(input, file);
};

describe("uploads", () => {
  it("uploads a picked file into the open folder and refreshes the listing", async () => {
    const user = userEvent.setup();
    const uploaded = vi.fn();
    const stored: OrgFileResponse[] = [];
    const document: OrgFileResponse = {
      id: "d1",
      filename: "smlouva.pdf",
      mime: "application/pdf",
      byte_size: 10,
      status: "indexed",
      effective_permission: "write",
      is_structure_manager: false,
    };
    server.use(
      ...listing(stored),
      /*
       * The body is not parsed here: axios sets multipart/form-data without a boundary under
       * jsdom, which the request parser cannot read. The route and the row's fate are the point.
       */
      http.post("http://api.test/me/org-files/folders/f1/documents", () => {
        uploaded();
        stored.push(document);
        return HttpResponse.json(document, { status: 201 });
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });
    await pickFile(user, pdf("smlouva.pdf"));

    await waitFor(() => expect(uploaded).toHaveBeenCalledTimes(1));
    // The pending row gives way to the file the refreshed listing returns.
    expect(await screen.findByText("smlouva.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Nahrávám…")).not.toBeInTheDocument();
  });

  it("refuses an unsupported file without a request", async () => {
    const uploaded = vi.fn();
    server.use(
      ...listing(),
      http.post("http://api.test/me/org-files/folders/f1/documents", () => {
        uploaded();
        return new HttpResponse(null, { status: 201 });
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    /*
     * Dropped rather than picked: the file input carries an accept list, so userEvent discards a
     * refused file before the component ever sees it — a drop is the path that reaches the guard.
     */
    fireEvent.drop(await screen.findByText("Složka je prázdná."), {
      dataTransfer: { files: [new File(["x"], "video.mp4", { type: "video/mp4" })] },
    });

    expect(await screen.findByText("Nepodporovaný typ souboru.")).toBeInTheDocument();
    expect(uploaded).not.toHaveBeenCalled();
  });

  it("offers a retry after a failed upload", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    server.use(
      ...listing(),
      http.post("http://api.test/me/org-files/folders/f1/documents", () => {
        attempts += 1;
        return new HttpResponse(null, { status: 500 });
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });
    await pickFile(user, pdf("smlouva.pdf"));

    expect(await screen.findByText("Soubor se nepodařilo nahrát.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zkusit znovu" }));

    await waitFor(() => expect(attempts).toBe(2));
  });

  it("names a duplicate and offers no retry", async () => {
    const user = userEvent.setup();
    server.use(
      ...listing(),
      http.post("http://api.test/me/org-files/folders/f1/documents", () =>
        HttpResponse.json({ detail: "duplicate" }, { status: 409 }),
      ),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });
    await pickFile(user, pdf("smlouva.pdf"));

    expect(await screen.findByText("Stejný soubor už je v této složce.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zkusit znovu" })).not.toBeInTheDocument();
  });

  it("cannot upload at the root", async () => {
    server.use(...listing());

    renderWithProviders(<FileBrowser />, { route: "/admin/files" });

    expect(await screen.findByRole("button", { name: "Nahrát soubor" })).toBeDisabled();
  });
});
