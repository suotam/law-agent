import { Navigate, Outlet, useLocation } from "react-router";
import { Loading } from "@/components/Loading";
import { useAuth } from "@/features/auth";

export const ProtectedRoute = () => {
  const { isAuthenticated, isLoadingAuth } = useAuth();
  const location = useLocation();

  if (isLoadingAuth)
    return (
      <Loading
        fullScreen
        delayMs={200}
      />
    );

  if (!isAuthenticated)
    return (
      <Navigate
        to="/login"
        replace
        // Remembered so an expired token returns the user where they were.
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );

  return <Outlet />;
};
