import type { ParseKeys } from "i18next";

/*
 * Mirrors the backend's allowed formats and size limit, so the frontend rejects early instead of
 * letting the server do it after an upload.
 */
export const MAX_FILE_MB = 50;

const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

const ACCEPTED_EXTENSIONS: readonly string[] = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".html",
  ".htm",
  ".xhtml",
  ".md",
  ".markdown",
  ".adoc",
  ".asciidoc",
  ".csv",
  // Scanned documents: OCR extracts their text.
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
  ".bmp",
  ".webp",
];

/** Narrows the system file picker; the check below is what actually enforces the rule. */
export const FILE_INPUT_ACCEPT = ACCEPTED_EXTENSIONS.join(",");

const extensionOf = (filename: string): string => {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot).toLowerCase();
};

/**
 * The i18n key of the reason a file cannot be uploaded, or null when it can. Matched on the
 * extension rather than on `file.type`, which browsers leave empty for plenty of real files.
 */
export const rejectionKeyFor = (file: File): ParseKeys | null => {
  if (!ACCEPTED_EXTENSIONS.includes(extensionOf(file.name))) return "attachments.rejectedType";
  if (file.size > MAX_FILE_BYTES) return "attachments.rejectedSize";
  return null;
};
