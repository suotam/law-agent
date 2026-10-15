import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ScopeValue } from "@/features/conversations";
import { SCOPE_LABEL_KEYS } from "./SourceChips";
import { useSourceScopeStore } from "../source-scope-store";

type FrozenScopeBadgesProps = {
  scope: ScopeValue[];
};

export const FrozenScopeBadges = ({ scope }: FrozenScopeBadgesProps) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const reset = useSourceScopeStore((state) => state.reset);

  // Prefills the new-chat screen with this thread's selection, unlocked.
  const startNewChatWithSameSources = () => {
    reset(scope);
    void navigate("/");
  };

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("sources.openFrozenInfo")}
          >
            {scope.length === 0
              ? t("sources.frozenNone")
              : scope.map((value) => t(SCOPE_LABEL_KEYS[value])).join(" · ")}
          </Button>
        }
      />
      <PopoverContent
        align="end"
        className="flex w-72 flex-col gap-3"
      >
        <p className="text-sm">{t("sources.frozenTitle")}</p>
        <Button
          size="sm"
          onClick={startNewChatWithSameSources}
        >
          {t("sources.newChatWithSources")}
        </Button>
      </PopoverContent>
    </Popover>
  );
};
