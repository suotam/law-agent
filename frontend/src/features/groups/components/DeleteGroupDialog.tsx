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

type DeleteGroupDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  errorMessage: string | null;
  isPending: boolean;
  onConfirm: () => void;
};

export const DeleteGroupDialog = ({
  open,
  onOpenChange,
  errorMessage,
  isPending,
  onConfirm,
}: DeleteGroupDialogProps) => {
  const { t } = useTranslation();

  return (
    <AlertDialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("groups.deleteTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t("groups.deleteDescription")}</AlertDialogDescription>
        </AlertDialogHeader>

        {errorMessage !== null && <p className="text-destructive text-sm">{errorMessage}</p>}

        <AlertDialogFooter>
          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction
            disabled={isPending}
            onClick={onConfirm}
          >
            {t("groups.deleteConfirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
