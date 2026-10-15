import { Navigate, Outlet } from "react-router";
import { Loading } from "@/components/Loading";
import { useAuth } from "@/features/auth";
import type { RoleCapability } from "@/features/auth";

type RequireCapabilityProps =
  { capability: RoleCapability; superuser?: never } | { capability?: never; superuser: true };

/*
 * A user lacking the capability is redirected rather than shown a 403 screen: nothing in
 * the app links here for them, so the section is simply not part of their app. The server's
 * own 403 stays the real authority — this only decides what is rendered.
 */
export const RequireCapability = (props: RequireCapabilityProps) => {
  const { user, isLoadingAuth } = useAuth();

  if (isLoadingAuth)
    return (
      <Loading
        fullScreen
        delayMs={200}
      />
    );

  const isAuthorized =
    user !== undefined &&
    (user.is_superuser ||
      (props.capability !== undefined && user.capabilities.includes(props.capability)));

  if (!isAuthorized)
    return (
      <Navigate
        to="/"
        replace
      />
    );

  return <Outlet />;
};
