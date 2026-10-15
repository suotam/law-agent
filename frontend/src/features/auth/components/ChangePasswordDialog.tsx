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
import { isAxiosError } from "axios";
import { changeOwnPassword } from "../api/change-own-password";

const changePasswordSchema = z.object({
  current_password: z.string().min(1, "auth.changePassword.currentRequired"),
  new_password: z.string().min(8, "users.passwordTooShort"),
});

type ChangePasswordValues = z.input<typeof changePasswordSchema>;

const asMessageKey = (message: string) => message as ParseKeys;

type ChangePasswordDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export const ChangePasswordDialog = ({ open, onOpenChange }: ChangePasswordDialogProps) => {
  const { t } = useTranslation();
  const {
    register,
    handleSubmit,
    reset: resetForm,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: "", new_password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await changeOwnPassword(values);
      resetForm({ current_password: "", new_password: "" });
      onOpenChange(false);
    } catch (error) {
      // A 403 here means the current password did not check out -- the
      // endpoint's one failure. Anything else is reported generically.
      const wrongCurrent = isAxiosError(error) && error.response?.status === 403;
      setError("current_password", {
        message: wrongCurrent ? "auth.changePassword.currentIncorrect" : "errors.unknown",
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
            <DialogTitle>{t("auth.changePassword.title")}</DialogTitle>
            <DialogDescription className="sr-only">
              {t("auth.changePassword.title")}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            <Label htmlFor="current-password">{t("auth.changePassword.currentLabel")}</Label>
            <Input
              id="current-password"
              type="password"
              autoFocus
              {...register("current_password")}
            />
            {errors.current_password?.message && (
              <p className="text-destructive text-sm">
                {t(asMessageKey(errors.current_password.message))}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="new-password">{t("auth.changePassword.newLabel")}</Label>
            <Input
              id="new-password"
              type="password"
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
              {t("auth.changePassword.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
