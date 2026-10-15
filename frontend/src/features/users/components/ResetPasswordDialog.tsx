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
import { useResetUserPassword } from "../api/reset-user-password";

const resetPasswordSchema = z.object({
  new_password: z.string().min(8, "users.passwordTooShort"),
});

type ResetPasswordValues = z.input<typeof resetPasswordSchema>;

const asMessageKey = (message: string) => message as ParseKeys;

type ResetPasswordDialogProps = {
  userId: string;
  email: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export const ResetPasswordDialog = ({
  userId,
  email,
  open,
  onOpenChange,
}: ResetPasswordDialogProps) => {
  const { t } = useTranslation();
  const reset = useResetUserPassword();

  const {
    register,
    handleSubmit,
    reset: resetForm,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await reset.mutateAsync({ id: userId, new_password: values.new_password });
      resetForm({ new_password: "" });
      onOpenChange(false);
    } catch (error) {
      const translated = translateError(error);
      setError("new_password", { message: translated.messageKey });
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
            <DialogTitle>{t("users.resetPasswordTitle")}</DialogTitle>
            <DialogDescription className="sr-only">
              {t("users.resetPasswordTitle")}
            </DialogDescription>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">{email}</p>

          <div className="flex flex-col gap-2">
            <Label htmlFor="reset-password">{t("users.newPasswordLabel")}</Label>
            <Input
              id="reset-password"
              type="password"
              autoFocus
              {...register("new_password")}
            />
            {errors.new_password?.message && (
              <p className="text-destructive text-sm">
                {t(asMessageKey(errors.new_password.message))}
              </p>
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
              {t("users.resetConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
