import type { ReactNode } from "react";
import { LoaderCircle, MoreHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export type RowAction = {
  key: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  isBusy?: boolean;
};

type RowActionsProps = {
  items: RowAction[];
};

export const RowActions = ({ items }: RowActionsProps) => {
  const { t } = useTranslation();

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t("orgFiles.itemActions")}
          >
            <MoreHorizontal aria-hidden="true" />
          </Button>
        }
      />
      <PopoverContent
        align="end"
        className="w-48 gap-0 p-1"
      >
        <div role="menu">
          {items.map((item) => (
            <Button
              key={item.key}
              role="menuitem"
              variant="ghost"
              disabled={item.isBusy}
              onClick={item.onSelect}
              className="w-full justify-start"
            >
              {item.isBusy ? (
                <LoaderCircle
                  aria-hidden="true"
                  className="animate-spin"
                />
              ) : (
                item.icon
              )}
              {item.label}
            </Button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
};
