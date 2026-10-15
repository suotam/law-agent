import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { useAttachmentUploads } from "@/features/attachments";

/** The new-chat case: nothing to claim the upload for yet. */
const noConversation = () => null;

const fileNamed = (name: string) => new File(["content"], name, { type: "application/pdf" });

/*
 * The multipart body is read as text rather than through request.formData(): jsdom's File is
 * not Node's File, so undici's multipart parser rejects it. jsdom also drops the filename to
 * "blob" on the wire, so only field names and plain values are worth asserting.
 */
const fieldNames = (body: string): string[] =>
  // The leading separator keeps the file part's own filename="blob" out of the list.
  [...body.matchAll(/[;\s]name="(?<field>[^"]+)"/g)].map((match) => match.groups?.field ?? "?");

const fieldValue = (body: string, name: string): string | null =>
  new RegExp(`name="${name}"\\r?\\n\\r?\\n(?<value>[^\\r\\n]*)`).exec(body)?.groups?.value ?? null;

const uploadResponse = (id: string) =>
  HttpResponse.json(
    { id, filename: "f.pdf", mime: "application/pdf", byte_size: 7, status: "indexed" },
    { status: 201 },
  );

/** The assertions here are about which files a turn carries, so the ids are enough. */
const readyIds = async (
  waitForReadyAttachments: () => Promise<{ id: string }[]>,
): Promise<string[]> => (await waitForReadyAttachments()).map(({ id }) => id);

describe("useAttachmentUploads", () => {
  it("uploads one request per file and exposes the resolved ids", async () => {
    const seen: string[][] = [];
    server.use(
      http.post("http://api.test/attachments", async ({ request }) => {
        seen.push(fieldNames(await request.text()));
        return uploadResponse(`a-${seen.length}`);
      }),
    );

    const { result } = renderHook(() => useAttachmentUploads(noConversation));

    act(() => {
      result.current.addFiles([fileNamed("a.pdf"), fileNamed("b.pdf")]);
    });

    await waitFor(() => expect(result.current.hasPendingUploads).toBe(false));
    // One request per file, and the multipart field is named "file".
    expect(seen).toEqual([["file"], ["file"]]);
    await expect(readyIds(result.current.waitForReadyAttachments)).resolves.toEqual(["a-1", "a-2"]);
  });

  it("uploads without a conversation id before the thread exists", async () => {
    let body = "";
    server.use(
      http.post("http://api.test/attachments", async ({ request }) => {
        body = await request.text();
        return uploadResponse("a-1");
      }),
    );

    const { result } = renderHook(() => useAttachmentUploads(noConversation));

    act(() => {
      result.current.addFiles([fileNamed("a.pdf")]);
    });

    await waitFor(() => expect(result.current.hasPendingUploads).toBe(false));
    // An empty conversation_id would be a conversation the server cannot find.
    expect(fieldNames(body)).toEqual(["file"]);
  });

  it("claims the upload right away when the thread already exists", async () => {
    let body = "";
    server.use(
      http.post("http://api.test/attachments", async ({ request }) => {
        body = await request.text();
        return uploadResponse("a-1");
      }),
    );

    const { result } = renderHook(() => useAttachmentUploads(() => "c1"));

    act(() => {
      result.current.addFiles([fileNamed("a.pdf")]);
    });

    await waitFor(() => expect(result.current.hasPendingUploads).toBe(false));
    expect(fieldValue(body, "conversation_id")).toBe("c1");
  });

  it("reads the conversation id per request, so a thread created mid-upload is used", async () => {
    const bodies: string[] = [];
    server.use(
      http.post("http://api.test/attachments", async ({ request }) => {
        bodies.push(await request.text());
        return uploadResponse(`a-${bodies.length}`);
      }),
    );

    let conversationId: string | null = null;
    const { result } = renderHook(() => useAttachmentUploads(() => conversationId));

    act(() => {
      result.current.addFiles([fileNamed("a.pdf")]);
    });
    await waitFor(() => expect(bodies).toHaveLength(1));

    conversationId = "c1";
    act(() => {
      result.current.addFiles([fileNamed("b.pdf")]);
    });

    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(fieldValue(bodies[0], "conversation_id")).toBeNull();
    expect(fieldValue(bodies[1], "conversation_id")).toBe("c1");
  });

  it("deletes an uploaded file by its own id, with no conversation in the path", async () => {
    const deleted: string[] = [];
    server.use(
      http.post("http://api.test/attachments", () => uploadResponse("a-1")),
      http.delete("http://api.test/attachments/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const { result } = renderHook(() => useAttachmentUploads(noConversation));

    act(() => {
      result.current.addFiles([fileNamed("a.pdf")]);
    });
    await waitFor(() => expect(result.current.uploads[0]?.status).toBe("ready"));

    await act(async () => {
      await result.current.remove(result.current.uploads[0].localId);
    });

    expect(deleted).toEqual(["a-1"]);
    expect(result.current.uploads).toEqual([]);
  });

  it("waits for an in-flight upload before resolving ids", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post("http://api.test/attachments", async () => {
        await gate;
        return uploadResponse("a-1");
      }),
    );

    const { result } = renderHook(() => useAttachmentUploads(noConversation));

    act(() => {
      result.current.addFiles([fileNamed("a.pdf")]);
    });
    await waitFor(() => expect(result.current.hasPendingUploads).toBe(true));

    let resolved: string[] | null = null;
    void readyIds(result.current.waitForReadyAttachments).then((ids) => {
      resolved = ids;
    });

    expect(resolved).toBeNull();
    act(() => release());

    await waitFor(() => expect(resolved).toEqual(["a-1"]));
  });

  it("refuses a file the rules reject without ever making a request", async () => {
    // No handler is registered: an upload attempt would fail the run as an unhandled request.
    const { result } = renderHook(() => useAttachmentUploads(noConversation));

    act(() => {
      result.current.addFiles([new File(["x"], "zaznam.mp4", { type: "video/mp4" })]);
    });

    expect(result.current.uploads).toEqual([
      expect.objectContaining({ status: "error", rejectionKey: "attachments.rejectedType" }),
    ]);
    await expect(readyIds(result.current.waitForReadyAttachments)).resolves.toEqual([]);
  });

  it("refuses a file over the size limit", () => {
    const oversized = fileNamed("velky.pdf");
    // Cheaper than allocating 50 MB, and File.size is what the rule actually reads.
    Object.defineProperty(oversized, "size", { value: 51 * 1024 * 1024 });

    const { result } = renderHook(() => useAttachmentUploads(noConversation));

    act(() => {
      result.current.addFiles([oversized]);
    });

    expect(result.current.uploads[0]).toMatchObject({
      status: "error",
      rejectionKey: "attachments.rejectedSize",
    });
  });

  it("aborts an in-flight upload on clear, so its id cannot reach the next turn", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    server.use(
      http.post("http://api.test/attachments", async () => {
        await gate;
        return uploadResponse("a-1");
      }),
    );

    const { result } = renderHook(() => useAttachmentUploads(noConversation));

    act(() => {
      result.current.addFiles([fileNamed("a.pdf")]);
    });
    await waitFor(() => expect(result.current.hasPendingUploads).toBe(true));

    // What the 404 recovery path does while an upload the user started is still running.
    act(() => result.current.clear());
    act(() => release());
    await new Promise((resolve) => setTimeout(resolve, 50));

    // An upload merely forgotten would have resolved by now and left "a-1" behind.
    await expect(readyIds(result.current.waitForReadyAttachments)).resolves.toEqual([]);
    expect(result.current.uploads).toEqual([]);
  });

  it("marks a 500 as an error chip and keeps the other ids", async () => {
    let calls = 0;
    server.use(
      http.post("http://api.test/attachments", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ detail: "internal server error" }, { status: 500 })
          : uploadResponse("a-2");
      }),
    );

    const { result } = renderHook(() => useAttachmentUploads(noConversation));

    act(() => {
      result.current.addFiles([fileNamed("a.pdf"), fileNamed("b.pdf")]);
    });

    await waitFor(() => expect(result.current.hasPendingUploads).toBe(false));
    expect(result.current.uploads.map((upload) => upload.status)).toEqual(["error", "ready"]);
    await expect(readyIds(result.current.waitForReadyAttachments)).resolves.toEqual(["a-2"]);
  });
});
