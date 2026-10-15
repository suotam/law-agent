import { isAxiosError } from "axios";

export type ApiFieldError = {
  /** Last addressable segment of FastAPI's `loc`, e.g. "question" for ["body", "question"]. */
  field: string;
  messageKey: string;
  /** FastAPI's raw English message. Kept for logging; never rendered. */
  detail: string;
};

export type TranslatedError = {
  status?: number;
  messageKey: string;
  fieldErrors: ApiFieldError[];
};

/** Thrown by the chat transport, which streams over fetch and so never produces an AxiosError. */
export class ChatHttpError extends Error {
  readonly status: number;

  constructor(status: number, message = `chat request failed with ${status}`) {
    super(message);
    this.name = "ChatHttpError";
    this.status = status;
  }
}

const STATUS_KEYS: Record<number, string> = {
  401: "errors.unauthorized",
  403: "errors.forbidden",
  404: "errors.notFound",
  409: "errors.conflict",
  422: "errors.validation",
  500: "errors.server",
};

const keyForStatus = (status: number): string => STATUS_KEYS[status] ?? "errors.unknown";

type FastApiValidationItem = { loc?: unknown[]; msg?: unknown };

const isValidationItem = (value: unknown): value is FastApiValidationItem =>
  typeof value === "object" && value !== null;

const toFieldErrors = (detail: unknown): ApiFieldError[] => {
  if (!Array.isArray(detail)) return [];

  return detail.flatMap((item: unknown) => {
    if (!isValidationItem(item) || !Array.isArray(item.loc)) return [];

    // loc is ["body", "<field>"] or ["body", "<field>", <index>]; the leading
    // location kind alone identifies no field, so such entries are dropped.
    const segments = item.loc.filter((part): part is string => typeof part === "string").slice(1);
    const field = segments.at(-1);
    if (!field) return [];

    return [
      {
        field,
        messageKey: "errors.validation",
        detail: typeof item.msg === "string" ? item.msg : "",
      },
    ];
  });
};

const detailOf = (data: unknown): unknown =>
  typeof data === "object" && data !== null && "detail" in data ? data.detail : undefined;

export const translateError = (error: unknown): TranslatedError => {
  if (error instanceof ChatHttpError) {
    return { status: error.status, messageKey: keyForStatus(error.status), fieldErrors: [] };
  }

  if (isAxiosError(error)) {
    const status = error.response?.status;
    if (status === undefined) {
      return { status: undefined, messageKey: "errors.network", fieldErrors: [] };
    }

    return {
      status,
      messageKey: keyForStatus(status),
      fieldErrors: status === 422 ? toFieldErrors(detailOf(error.response?.data)) : [],
    };
  }

  return { status: undefined, messageKey: "errors.unknown", fieldErrors: [] };
};
