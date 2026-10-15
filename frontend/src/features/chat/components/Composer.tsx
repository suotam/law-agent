import { useRef, useState } from "react";
import { Paperclip, SendHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AttachmentChips, FILE_INPUT_ACCEPT, type AttachmentUpload } from "@/features/attachments";

type ComposerProps = {
  onSubmit: (text: string) => void;
  onFiles: (files: File[]) => void;
  /** True when neither a source nor an attachment is present. */
  isRuleUnmet: boolean;
  isBusy: boolean;
  uploads: AttachmentUpload[];
  onDismissUpload: (localId: string) => void;
  onRetryUpload: (localId: string) => void;
};

export const Composer = ({
  onSubmit,
  onFiles,
  isRuleUnmet,
  isBusy,
  uploads,
  onDismissUpload,
  onRetryUpload,
}: ComposerProps) => {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    // Swallowing the text on a send the session would refuse anyway reads as a silent failure.
    // isBusy is checked here too: the disabled button does not cover the Enter key.
    if (text.trim().length === 0 || isRuleUnmet || isBusy) return;
    onSubmit(text);
    // Cleared optimistically: a queued send shows up as its own bubble in the list.
    setText("");
  };

  return (
    <div className="border-border bg-card mx-auto flex w-full max-w-3xl flex-col gap-2 rounded-xl border p-2 shadow-sm">
      {/* Cause and remedy, instead of a disabled button with no explanation. */}
      {isRuleUnmet && (
        <p className="text-warning-foreground bg-warning/20 rounded-md px-2 py-1 text-sm">
          {t("chat.sourceRule")}
        </p>
      )}

      <AttachmentChips
        uploads={uploads}
        onDismiss={onDismissUpload}
        onRetry={onRetryUpload}
      />

      <div className="flex items-end gap-2">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          // Narrows the picker only; a file that slips through is refused by the same rules.
          accept={FILE_INPUT_ACCEPT}
          className="hidden"
          onChange={(event) => {
            onFiles([...(event.target.files ?? [])]);
            event.target.value = "";
          }}
        />
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("attachments.addLabel")}
          onClick={() => fileInputRef.current?.click()}
        >
          <Paperclip aria-hidden="true" />
        </Button>

        <Textarea
          rows={1}
          value={text}
          placeholder={t("chat.placeholder")}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          className="max-h-48 min-h-9 flex-1 resize-none border-0 shadow-none focus-visible:ring-0"
        />

        {/* Stays enabled during uploads: the send is queued, not blocked. */}
        <Button
          aria-label={t("chat.send")}
          disabled={isBusy}
          onClick={submit}
        >
          <SendHorizontal aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
};
