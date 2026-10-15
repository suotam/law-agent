import { useState } from "react";
import { Menu, PanelLeftClose, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, Outlet } from "react-router";
import { Button } from "@/components/ui/button";
import { AccountMenu } from "@/features/auth";
import { ChatSessionProvider } from "@/features/chat";
import { ConversationList } from "@/features/conversations";
import { cn } from "@/lib/utils";

/** Tailwind's `md`, below which the sidebar is a drawer over the thread rather than a column. */
const DESKTOP_QUERY = "(min-width: 48rem)";

export const AppLayout = () => {
  const { t } = useTranslation();
  // Open by default only where it costs nothing: on a phone it would cover the chat itself.
  const [isOpen, setIsOpen] = useState(() => window.matchMedia(DESKTOP_QUERY).matches);

  return (
    <ChatSessionProvider>
      {/* The shell owns the viewport: the sidebar stays put and only the thread scrolls. */}
      <div className="bg-background flex h-svh overflow-hidden">
        {/* Backdrop only exists below md, where the sidebar is a drawer. */}
        {isOpen && (
          <button
            type="button"
            aria-label={t("shell.closeSidebar")}
            onClick={() => setIsOpen(false)}
            className="fixed inset-0 z-10 bg-black/40 md:hidden"
          />
        )}

        <aside
          className={cn(
            "bg-sidebar text-sidebar-foreground fixed inset-y-0 left-0 z-20 flex w-64 flex-col gap-3 p-3 transition-transform md:static md:translate-x-0",
            isOpen ? "translate-x-0" : "-translate-x-full md:hidden",
          )}
        >
          <div className="flex items-center justify-between">
            <span className="px-1 text-sm font-semibold tracking-tight">{t("shell.appName")}</span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("shell.closeSidebar")}
              onClick={() => setIsOpen(false)}
              className="text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            >
              <PanelLeftClose aria-hidden="true" />
            </Button>
          </div>

          <Button
            variant="secondary"
            render={<Link to="/" />}
            className="justify-start"
          >
            <Plus aria-hidden="true" />
            {t("shell.newChat")}
          </Button>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <ConversationList />
          </div>

          <div className="border-sidebar-border border-t pt-2">
            <AccountMenu />
          </div>
        </aside>

        <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* Floats over the content: reopening the sidebar must not reflow the screen. */}
          {!isOpen && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("shell.openSidebar")}
              onClick={() => setIsOpen(true)}
              className="absolute top-2 left-2 z-10"
            >
              <Menu aria-hidden="true" />
            </Button>
          )}
          <Outlet />
        </div>
      </div>
    </ChatSessionProvider>
  );
};
