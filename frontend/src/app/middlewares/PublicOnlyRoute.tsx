import { Navigate, Outlet, useLocation } from "react-router";
import { Loading } from "@/components/Loading";
import { useAuth } from "@/features/auth";

type LocationState = { from?: string } | null;

export const PublicOnlyRoute = () => {
  const { isAuthenticated, isLoadingAuth } = useAuth();
  const location = useLocation();

  if (isLoadingAuth)
    return (
      <Loading
        fullScreen
        delayMs={200}
      />
    );

  if (isAuthenticated) {
    const state = location.state as LocationState;
    return (
      <Navigate
        to={state?.from ?? "/"}
        replace
      />
    );
  }

  return <Outlet />;
};
