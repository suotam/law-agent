import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";
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
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ConversationResponse } from "../types";
import { useDeleteConversation } from "../hooks/useDeleteConversation";

type ConversationListItemProps = {
  conversation: ConversationResponse;
};

export const ConversationListItem = ({ conversation }: ConversationListItemProps) => {
  const { t } = useTranslation();
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const deleteMutation = useDeleteConversation();

  // The backend may return a thread with no title yet; it must not render as a blank row.
  const title = conversation.title || t("conversations.untitled");

  const confirmDelete = () => {
    deleteMutation.mutate(conversation.id);
    // AlertDialogAction is a plain button in this style — it does not close on its own.
    setIsConfirmOpen(false);
  };

  return (
    <li className="group/item relative">
      <NavLink
        to={`/chat/${conversation.id}`}
        title={title}
        className={({ isActive }) =>
          cn(
            "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground block truncate rounded-md px-2 py-1.5 pr-8 text-sm",
            isActive && "bg-sidebar-accent text-sidebar-accent-foreground",
          )
        }
      >
        {title}
      </NavLink>

      <Button
        variant="ghost"
        size="icon-xs"
        aria-label={t("conversations.deleteLabel")}
        onClick={() => setIsConfirmOpen(true)}
        className="text-sidebar-foreground hover:bg-sidebar-accent absolute top-1.5 right-1 opacity-0 group-hover/item:opacity-100 focus-visible:opacity-100"
      >
        <Trash2 aria-hidden="true" />
      </Button>

      <AlertDialog
        open={isConfirmOpen}
        onOpenChange={setIsConfirmOpen}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("conversations.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("conversations.deleteDescription")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            {/* Soft delete server-side, but the frontend has no way to undo it. */}
            <AlertDialogAction onClick={confirmDelete}>
              {t("conversations.deleteConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
};
