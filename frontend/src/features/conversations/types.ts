export type ScopeValue = "laws" | "org_files";

export type ConversationResponse = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = ConversationResponse & {
  scope: ScopeValue[];
  /** Server-side RAG tuning parameter. Read but never sent and never displayed. */
  limit: number;
};

export type CreateConversationRequest = {
  scope: ScopeValue[];
  /** Truncated to 30 characters server-side; there is no endpoint to change it afterwards. */
  title: string;
  /** Narrows `org_files` retrieval within the server-enforced ceiling. Narrowing
   * is one decision about the whole selection: once either field is sent, the
   * other must be sent too (`[]` when nothing was checked on that side) --
   * omitting just one would leave unrelated direct grants searchable next to
   * the checked folder/document. Both omitted means "no narrowing". */
  org_files_folder_ids?: string[];
  org_files_document_ids?: string[];
};
