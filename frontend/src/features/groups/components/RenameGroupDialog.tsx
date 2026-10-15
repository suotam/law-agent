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
import { useRenameGroup } from "../api/rename-group";
import type { GroupResponse } from "../types";

const groupSchema = z.object({
  name: z.string().trim().min(1, "groups.nameRequired").max(255, "groups.nameTooLong"),
});

type GroupValues = z.input<typeof groupSchema>;

const asMessageKey = (message: string) => message as ParseKeys;

type RenameGroupDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  group: GroupResponse | null;
};

export const RenameGroupDialog = ({ open, onOpenChange, group }: RenameGroupDialogProps) => {
  const { t } = useTranslation();
  const rename = useRenameGroup();

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<GroupValues>({
    resolver: zodResolver(groupSchema),
    defaultValues: { name: "" },
  });

  useEffect(() => {
    if (open) reset({ name: group?.name ?? "" });
  }, [open, group, reset]);

  const onSubmit = handleSubmit(async ({ name }) => {
    if (group === null) return;
    try {
      await rename.mutateAsync({ id: group.id, name: name.trim() });
      onOpenChange(false);
    } catch (error) {
      const translated = translateError(error);
      setError("name", {
        message: translated.status === 409 ? "groups.nameTaken" : translated.messageKey,
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
            <DialogTitle>{t("groups.renameTitle")}</DialogTitle>
            <DialogDescription className="sr-only">{t("groups.nameLabel")}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            <Label htmlFor="group-rename">{t("groups.nameLabel")}</Label>
            <Input
              id="group-rename"
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
              {t("groups.renameConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
