import { Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useRoles } from "../api/list-roles";
import type { RoleResponse } from "../types";

type RoleTableProps = {
  onEdit?: (role: RoleResponse) => void;
  onDelete?: (role: RoleResponse) => void;
};

export const RoleTable = ({ onEdit, onDelete }: RoleTableProps) => {
  const { t } = useTranslation();
  const roles = useRoles();

  if (roles.isPending)
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );

  if (roles.isError) return <p className="text-destructive text-sm">{t("roles.loadError")}</p>;

  return (
    <ul className="border-border divide-border rounded-md border">
      {roles.data.map((role) => (
        <li
          key={role.id}
          className="border-border flex items-center gap-3 border-b px-3 py-2 text-sm last:border-b-0"
        >
          <span className="min-w-0 flex-1 truncate font-medium">{role.name}</span>

          {role.is_superuser && (
            <span className="bg-secondary text-secondary-foreground shrink-0 rounded-full px-2 py-0.5 text-xs">
              {t("roles.superuserBadge")}
            </span>
          )}

          <span className="text-muted-foreground flex flex-wrap justify-end gap-1 text-xs">
            {role.capabilities.map((capability) => (
              <span
                key={capability}
                className="bg-muted rounded-full px-2 py-0.5"
              >
                {t(`roles.capabilities.${capability}`)}
              </span>
            ))}
          </span>

          <div className="ml-auto flex shrink-0 items-center gap-1">
            {/* A superuser role is immutable and undeletable server-side; the
                actions are hidden so the UI agrees with what the API allows. */}
            {onEdit && !role.is_superuser && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("roles.editLabel", { name: role.name })}
                onClick={() => onEdit(role)}
              >
                <Pencil aria-hidden="true" />
              </Button>
            )}
            {onDelete && !role.is_superuser && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("roles.deleteLabel", { name: role.name })}
                onClick={() => onDelete(role)}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
};
