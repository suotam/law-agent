import { useState } from "react";
import { UserPlus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { CreateUserDialog } from "./CreateUserDialog";
import { UserTable } from "./UserTable";

export const UsersScreen = () => {
  const { t } = useTranslation();
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{t("users.heading")}</h1>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setIsCreateOpen(true)}
        >
          <UserPlus aria-hidden="true" />
          {t("users.createTitle")}
        </Button>
      </div>

      <UserTable />

      <CreateUserDialog
        open={isCreateOpen}
        onOpenChange={setIsCreateOpen}
      />
    </div>
  );
};
