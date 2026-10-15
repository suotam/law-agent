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
import { useCreateGroup } from "../api/create-group";

const groupSchema = z.object({
  name: z.string().trim().min(1, "groups.nameRequired").max(255, "groups.nameTooLong"),
});

type GroupValues = z.input<typeof groupSchema>;

const asMessageKey = (message: string) => message as ParseKeys;

type CreateGroupDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export const CreateGroupDialog = ({ open, onOpenChange }: CreateGroupDialogProps) => {
  const { t } = useTranslation();
  const create = useCreateGroup();

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

  const onSubmit = handleSubmit(async ({ name }) => {
    try {
      await create.mutateAsync({ name: name.trim() });
      reset({ name: "" });
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
            <DialogTitle>{t("groups.createTitle")}</DialogTitle>
            <DialogDescription className="sr-only">{t("groups.nameLabel")}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            <Label htmlFor="group-name">{t("groups.nameLabel")}</Label>
            <Input
              id="group-name"
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
              {t("groups.createConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
