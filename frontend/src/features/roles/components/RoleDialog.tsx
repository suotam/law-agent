import { useEffect, useRef, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import type { ParseKeys } from "i18next";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { translateError } from "@/lib/errors";
import type { RoleCapability } from "@/features/auth";
import { useCreateRole } from "../api/create-role";
import { useRenameRole } from "../api/rename-role";
import { useUpdateRoleCapabilities } from "../api/update-role-capabilities";
import type { RoleResponse } from "../types";
import { CapabilityCheckboxes } from "./CapabilityCheckboxes";

const roleSchema = z.object({
  name: z.string().trim().min(1, "roles.nameRequired").max(255, "roles.nameTooLong"),
});

type RoleValues = z.input<typeof roleSchema>;

const asMessageKey = (message: string) => message as ParseKeys;

type RoleDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  role: RoleResponse | null;
};

export const RoleDialog = ({ open, onOpenChange, role }: RoleDialogProps) => {
  const { t } = useTranslation();
  const create = useCreateRole();
  const rename = useRenameRole();
  const updateCapabilities = useUpdateRoleCapabilities();

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RoleValues>({
    resolver: zodResolver(roleSchema),
    defaultValues: { name: "" },
  });

  // Capability edits are staged here and only PUT on submit -- Cancel must
  // discard them, so a per-click mutate() (the previous behaviour) is wrong.
  const [pendingCapabilities, setPendingCapabilities] = useState<RoleCapability[]>([]);

  // Reset the form and the staged capabilities once per dialog-open session
  // for a given role, not on every render where `role` happens to get a new
  // object reference (e.g. a background refetch of the roles list while the
  // dialog is still open) -- that would silently wipe unsaved edits.
  const initializedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!open) {
      initializedFor.current = null;
      return;
    }
    const sessionKey = role?.id ?? "__create__";
    if (initializedFor.current === sessionKey) return;
    initializedFor.current = sessionKey;
    reset({ name: role?.name ?? "" });
    setPendingCapabilities(role?.capabilities ?? []);
  }, [open, role, reset]);

  const onSubmit = handleSubmit(async ({ name }) => {
    try {
      if (role === null) {
        await create.mutateAsync({ name: name.trim() });
      } else {
        await rename.mutateAsync({ id: role.id, name: name.trim() });
        const capabilitiesChanged =
          pendingCapabilities.length !== role.capabilities.length ||
          !pendingCapabilities.every((capability) => role.capabilities.includes(capability));
        if (capabilitiesChanged) {
          await updateCapabilities.mutateAsync({ id: role.id, capabilities: pendingCapabilities });
        }
      }

      onOpenChange(false);
    } catch (error) {
      const translated = translateError(error);
      setError("name", {
        message: translated.status === 409 ? "roles.nameTaken" : translated.messageKey,
      });
    }
  });

  const toggleCapability = (capability: RoleCapability) => {
    setPendingCapabilities((current) =>
      current.includes(capability)
        ? current.filter((entry) => entry !== capability)
        : [...current, capability],
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent>
        <form
          onSubmit={(event) => void onSubmit(event)}
          className="flex flex-col gap-4"
        >
          <DialogHeader>
            <DialogTitle>{t(role === null ? "roles.createTitle" : "roles.editTitle")}</DialogTitle>
            <DialogDescription className="sr-only">{t("roles.nameLabel")}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            <Label htmlFor="role-name">{t("roles.nameLabel")}</Label>
            <Input
              id="role-name"
              autoFocus
              {...register("name")}
            />
            {errors.name?.message && (
              <p className="text-destructive text-sm">{t(asMessageKey(errors.name.message))}</p>
            )}
          </div>

          {role !== null && (
            <CapabilityCheckboxes
              selected={pendingCapabilities}
              onToggle={toggleCapability}
            />
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting}
            >
              {t(role === null ? "roles.createConfirm" : "roles.saveConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
