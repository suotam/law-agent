import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";
import { ChatHttpError, translateError } from "@/lib/errors";

const axiosErrorWith = (status: number, data: unknown): AxiosError => {
  const error = new AxiosError("request failed");
  error.response = {
    status,
    statusText: "",
    data,
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return error;
};

describe("translateError", () => {
  it("maps a 422 array detail to per-field errors", () => {
    const result = translateError(
      axiosErrorWith(422, {
        detail: [
          {
            type: "string_too_short",
            loc: ["body", "question"],
            msg: "String should have at least 1 character",
            input: "",
          },
        ],
      }),
    );

    expect(result.status).toBe(422);
    expect(result.messageKey).toBe("errors.validation");
    expect(result.fieldErrors).toEqual([
      {
        field: "question",
        messageKey: "errors.validation",
        detail: "String should have at least 1 character",
      },
    ]);
  });

  it("maps a string detail to a status key without field errors", () => {
    const result = translateError(axiosErrorWith(401, { detail: "invalid email or password" }));

    expect(result).toEqual({ status: 401, messageKey: "errors.unauthorized", fieldErrors: [] });
  });

  it("maps an empty body to the status key", () => {
    const result = translateError(axiosErrorWith(500, undefined));

    expect(result).toEqual({ status: 500, messageKey: "errors.server", fieldErrors: [] });
  });

  it("maps a request that never got a response to a network error", () => {
    const error = new AxiosError("Network Error");

    expect(translateError(error)).toEqual({
      status: undefined,
      messageKey: "errors.network",
      fieldErrors: [],
    });
  });

  it("maps a ChatHttpError by its status", () => {
    expect(translateError(new ChatHttpError(404)).messageKey).toBe("errors.notFound");
  });

  it("falls back to an unknown error for anything else", () => {
    expect(translateError(new Error("boom")).messageKey).toBe("errors.unknown");
  });

  it("ignores a 422 entry whose loc is not addressable", () => {
    const result = translateError(axiosErrorWith(422, { detail: [{ loc: ["body"], msg: "bad" }] }));

    expect(result.fieldErrors).toEqual([]);
  });
});
