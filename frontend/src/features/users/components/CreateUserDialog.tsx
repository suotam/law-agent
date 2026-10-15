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
import { useRoles } from "@/features/roles";
import { useAuth } from "@/features/auth";
import { useCreateUser } from "../api/create-user";

const createUserSchema = z.object({
  email: z.string().min(1, "users.emailRequired").pipe(z.email("users.emailInvalid")),
  password: z.string().min(8, "users.passwordTooShort"),
  role_id: z.string().min(1, "users.roleRequired"),
});

type CreateUserValues = z.input<typeof createUserSchema>;

const asMessageKey = (message: string) => message as ParseKeys;

type CreateUserDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export const CreateUserDialog = ({ open, onOpenChange }: CreateUserDialogProps) => {
  const { t } = useTranslation();
  const roles = useRoles();
  const create = useCreateUser();
  const { user } = useAuth();
  // Same rule the backend enforces: the superuser role is handed out by
  // superusers only, so a manager never sees it as a choice.
  const selectableRoles = (roles.data ?? []).filter(
    (role) => user?.is_superuser === true || !role.is_superuser,
  );

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CreateUserValues>({
    resolver: zodResolver(createUserSchema),
    defaultValues: { email: "", password: "", role_id: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await create.mutateAsync(values);
      reset({ email: "", password: "", role_id: "" });
      onOpenChange(false);
    } catch (error) {
      const translated = translateError(error);
      setError("email", {
        message: translated.status === 409 ? "users.emailTaken" : translated.messageKey,
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
            <DialogTitle>{t("users.createTitle")}</DialogTitle>
            <DialogDescription className="sr-only">{t("users.createTitle")}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            <Label htmlFor="user-email">{t("users.emailLabel")}</Label>
            <Input
              id="user-email"
              type="email"
              autoFocus
              {...register("email")}
            />
            {errors.email?.message && (
              <p className="text-destructive text-sm">{t(asMessageKey(errors.email.message))}</p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="user-password">{t("users.passwordLabel")}</Label>
            <Input
              id="user-password"
              type="password"
              {...register("password")}
            />
            {errors.password?.message && (
              <p className="text-destructive text-sm">{t(asMessageKey(errors.password.message))}</p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="user-role">{t("users.roleFieldLabel")}</Label>
            <select
              id="user-role"
              {...register("role_id")}
              className="border-input h-9 w-full rounded-md border bg-transparent px-2.5 text-sm shadow-xs"
            >
              <option value="">{t("users.rolePlaceholder")}</option>
              {selectableRoles.map((role) => (
                <option
                  key={role.id}
                  value={role.id}
                >
                  {role.name}
                </option>
              ))}
            </select>
            {errors.role_id?.message && (
              <p className="text-destructive text-sm">{t(asMessageKey(errors.role_id.message))}</p>
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
              {t("users.createConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
