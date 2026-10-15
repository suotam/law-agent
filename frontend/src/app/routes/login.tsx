import { useTranslation } from "react-i18next";
import { LoginForm } from "@/features/auth";

export const LoginPage = () => {
  const { t } = useTranslation();

  return (
    <main className="bg-muted flex min-h-svh items-center justify-center p-6">
      <div className="bg-card flex w-full max-w-sm flex-col gap-6 rounded-xl border p-8 shadow-sm">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">{t("auth.login.heading")}</h1>
          <p className="text-muted-foreground text-sm">{t("auth.login.subheading")}</p>
        </div>
        <LoginForm />
      </div>
    </main>
  );
};
