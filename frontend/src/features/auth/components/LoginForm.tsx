import { zodResolver } from "@hookform/resolvers/zod";
import type { ParseKeys } from "i18next";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { translateError } from "@/lib/errors";
import { useLogin } from "../hooks/useLogin";

/*
 * Messages are i18n keys, not literals: the schema has no access to the t function.
 * The email is validated client-side because a malformed one returns FastAPI's 422
 * array shape rather than the 401 the user expects.
 */
const loginSchema = z.object({
  email: z.string().min(1, "auth.errors.emailRequired").pipe(z.email("auth.errors.emailInvalid")),
  password: z.string().min(1, "auth.errors.passwordRequired"),
});

type LoginValues = z.input<typeof loginSchema>;

/*
 * Zod and the error translator both carry messages as plain strings, but every one of
 * them is an i18n key by construction. t() is typed against the resource tree, so the
 * widening has to be undone at the single point where the two meet.
 */
const asMessageKey = (message: string) => message as ParseKeys;

export const LoginForm = () => {
  const { t } = useTranslation();
  const login = useLogin();

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await login.mutateAsync(values);
    } catch (error) {
      const translated = translateError(error);

      // A wrong password and an unknown account return identical responses by design,
      // so there is exactly one message for the whole 401 case.
      setError("root", {
        message:
          translated.status === 401 ? "auth.errors.invalidCredentials" : translated.messageKey,
      });
    }
  });

  return (
    <form
      onSubmit={(event) => void onSubmit(event)}
      noValidate
      className="flex w-full max-w-sm flex-col gap-5"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="email">{t("auth.login.email")}</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          placeholder={t("auth.login.emailPlaceholder")}
          aria-invalid={errors.email !== undefined}
          aria-describedby={errors.email ? "email-error" : undefined}
          {...register("email")}
        />
        {errors.email?.message && (
          <p
            id="email-error"
            className="text-destructive text-sm"
          >
            {t(asMessageKey(errors.email.message))}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password">{t("auth.login.password")}</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          aria-invalid={errors.password !== undefined}
          aria-describedby={errors.password ? "password-error" : undefined}
          {...register("password")}
        />
        {errors.password?.message && (
          <p
            id="password-error"
            className="text-destructive text-sm"
          >
            {t(asMessageKey(errors.password.message))}
          </p>
        )}
      </div>

      {errors.root?.message && (
        <p
          role="alert"
          className="text-destructive text-sm"
        >
          {t(asMessageKey(errors.root.message))}
        </p>
      )}

      <Button
        type="submit"
        disabled={isSubmitting}
      >
        {isSubmitting ? t("auth.login.submitting") : t("auth.login.submit")}
      </Button>
    </form>
  );
};
