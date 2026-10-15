import { useTranslation } from "react-i18next";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

type DeleteRoleDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  errorMessage: string | null;
  isPending: boolean;
  onConfirm: () => void;
};

export const DeleteRoleDialog = ({
  open,
  onOpenChange,
  errorMessage,
  isPending,
  onConfirm,
}: DeleteRoleDialogProps) => {
  const { t } = useTranslation();

  return (
    <AlertDialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("roles.deleteTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t("roles.deleteDescription")}</AlertDialogDescription>
        </AlertDialogHeader>

        {errorMessage !== null && <p className="text-destructive text-sm">{errorMessage}</p>}

        <AlertDialogFooter>
          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction
            disabled={isPending}
            onClick={onConfirm}
          >
            {t("roles.deleteConfirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
