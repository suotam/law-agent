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

type DeleteDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  /** Why the server refused, e.g. a folder that still holds documents. */
  errorMessage: string | null;
  isPending: boolean;
  onConfirm: () => void;
};

export const DeleteDialog = ({
  open,
  onOpenChange,
  title,
  description,
  errorMessage,
  isPending,
  onConfirm,
}: DeleteDialogProps) => {
  const { t } = useTranslation();

  return (
    <AlertDialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>

        {errorMessage !== null && <p className="text-destructive text-sm">{errorMessage}</p>}

        <AlertDialogFooter>
          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
          {/* AlertDialogAction is a plain button in this style — it does not close on its own. */}
          <AlertDialogAction
            disabled={isPending}
            onClick={onConfirm}
          >
            {t("orgFiles.deleteConfirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
