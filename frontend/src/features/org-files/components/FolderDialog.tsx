import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import type { ParseKeys } from "i18next";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { translateError } from "@/lib/errors";
import { useCreateFolder } from "../api/create-folder";
import { useUpdateFolder } from "../api/update-folder";
import type { FolderItem } from "../types";

const folderSchema = z.object({
  name: z.string().trim().min(1, "orgFiles.nameRequired").max(255, "orgFiles.nameTooLong"),
});

type FolderValues = z.input<typeof folderSchema>;

/** Zod carries messages as plain strings, but every one of them is an i18n key by construction. */
const asMessageKey = (message: string) => message as ParseKeys;

type FolderDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `null` creates a folder in `parentId`; otherwise this folder is renamed. */
  folder: FolderItem | null;
  parentId: string | null;
};

export const FolderDialog = ({ open, onOpenChange, folder, parentId }: FolderDialogProps) => {
  const { t } = useTranslation();
  const create = useCreateFolder();
  const update = useUpdateFolder();

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FolderValues>({
    resolver: zodResolver(folderSchema),
    defaultValues: { name: "" },
  });

  useEffect(() => {
    // Reopening for a different row must not show the previous row's name or error.
    if (open) reset({ name: folder?.name ?? "" });
  }, [open, folder, reset]);

  const onSubmit = handleSubmit(async ({ name }) => {
    try {
      if (folder === null) await create.mutateAsync({ name: name.trim(), parent_id: parentId });
      else await update.mutateAsync({ id: folder.id, name: name.trim() });

      onOpenChange(false);
    } catch (error) {
      const translated = translateError(error);

      // 409 is a sibling of the same name — the only server error the field itself can explain.
      setError("name", {
        message: translated.status === 409 ? "orgFiles.nameTaken" : translated.messageKey,
      });
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent>
        <form
          onSubmit={(event) => void onSubmit(event)}
          className="flex flex-col gap-4"
        >
          <DialogHeader>
            <DialogTitle>
              {t(folder === null ? "orgFiles.createTitle" : "orgFiles.renameTitle")}
            </DialogTitle>
            <DialogDescription className="sr-only">{t("orgFiles.nameLabel")}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            <Label htmlFor="folder-name">{t("orgFiles.nameLabel")}</Label>
            <Input
              id="folder-name"
              autoFocus
              {...register("name")}
            />
            {errors.name?.message && (
              <p className="text-destructive text-sm">{t(asMessageKey(errors.name.message))}</p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting}
            >
              {t(folder === null ? "orgFiles.createConfirm" : "orgFiles.renameConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
