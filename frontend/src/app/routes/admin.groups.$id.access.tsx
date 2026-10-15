import { useParams } from "react-router";
import { AccessBrowser, useGroupAcl, useGroups } from "@/features/groups";

export const GroupAccessPage = () => {
  const { id } = useParams<{ id: string }>();
  const acl = useGroupAcl(id ?? "");
  const groups = useGroups();

  if (id === undefined) return null;

  const principalName = groups.data?.find((group) => group.id === id)?.name ?? "";

  return (
    <AccessBrowser
      principalType="group"
      principalId={id}
      principalName={principalName}
      acl={acl}
    />
  );
};
