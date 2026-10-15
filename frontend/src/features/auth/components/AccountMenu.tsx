import { FolderCog, KeyRound, LogOut, ShieldCheck, Users, UsersRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ChangePasswordDialog } from "./ChangePasswordDialog";
import { useAuth } from "../hooks/useAuth";
import { useHasCapability } from "../hooks/useHasCapability";
import { useLogout } from "../hooks/useLogout";

export const AccountMenu = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const hasManageUsers = useHasCapability("manage_users");
  const hasManageGroups = useHasCapability("manage_groups");
  const { logout } = useLogout();
  const [isPasswordOpen, setIsPasswordOpen] = useState(false);

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            aria-label={t("auth.account.menuLabel")}
            className="text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground w-full justify-start truncate"
          >
            <span className="truncate">{user?.email}</span>
          </Button>
        }
      />
      <PopoverContent
        align="start"
        className="w-56 p-1"
      >
        {/*
         * Open to any authenticated user: every action inside the file browser is
         * independently permission-gated per node, and a member with no grants just
         * sees an empty tree — there is no capability that should hide the entry point.
         */}
        <Button
          variant="ghost"
          render={<Link to="/admin/files" />}
          className="w-full justify-start"
        >
          <FolderCog aria-hidden="true" />
          {t("auth.account.orgFiles")}
        </Button>

        {hasManageUsers && (
          <Button
            variant="ghost"
            render={<Link to="/users" />}
            className="w-full justify-start"
          >
            <Users aria-hidden="true" />
            {t("auth.account.users")}
          </Button>
        )}

        {hasManageGroups && (
          <Button
            variant="ghost"
            render={<Link to="/admin/groups" />}
            className="w-full justify-start"
          >
            <UsersRound aria-hidden="true" />
            {t("auth.account.groups")}
          </Button>
        )}

        {user?.is_superuser === true && (
          <Button
            variant="ghost"
            render={<Link to="/admin/roles" />}
            className="w-full justify-start"
          >
            <ShieldCheck aria-hidden="true" />
            {t("auth.account.roles")}
          </Button>
        )}

        <Button
          variant="ghost"
          className="w-full justify-start"
          onClick={() => setIsPasswordOpen(true)}
        >
          <KeyRound aria-hidden="true" />
          {t("auth.account.changePassword")}
        </Button>

        <Button
          variant="ghost"
          className="w-full justify-start"
          onClick={logout}
        >
          <LogOut aria-hidden="true" />
          {t("auth.account.logout")}
        </Button>
      </PopoverContent>

      <ChangePasswordDialog
        open={isPasswordOpen}
        onOpenChange={setIsPasswordOpen}
      />
    </Popover>
  );
};
