import { useParams } from "react-router";
import { AccessBrowser } from "@/features/groups";
import { useUserAcl, useUsers } from "@/features/users";

export const UserAccessPage = () => {
  const { id } = useParams<{ id: string }>();
  const acl = useUserAcl(id ?? "");
  const users = useUsers();

  if (id === undefined) return null;

  const principalName = users.data?.find((user) => user.id === id)?.email ?? "";

  return (
    <AccessBrowser
      principalType="user"
      principalId={id}
      principalName={principalName}
      acl={acl}
    />
  );
};
