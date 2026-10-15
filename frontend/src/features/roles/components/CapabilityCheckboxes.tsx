import { useTranslation } from "react-i18next";
import type { RoleCapability } from "@/features/auth";
import { ROLE_CAPABILITIES } from "../types";

type CapabilityCheckboxesProps = {
  selected: RoleCapability[];
  onToggle: (capability: RoleCapability) => void;
};

export const CapabilityCheckboxes = ({ selected, onToggle }: CapabilityCheckboxesProps) => {
  const { t } = useTranslation();

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm font-medium">{t("roles.capabilitiesLabel")}</legend>
      {ROLE_CAPABILITIES.map((capability) => (
        <label
          key={capability}
          className="flex items-center gap-2 text-sm"
        >
          <input
            type="checkbox"
            checked={selected.includes(capability)}
            onChange={() => onToggle(capability)}
          />
          {t(`roles.capabilities.${capability}`)}
        </label>
      ))}
    </fieldset>
  );
};
