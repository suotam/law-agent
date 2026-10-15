import { createBrowserRouter } from "react-router";
import { AppProvider } from "./provider";
import { AppLayout } from "./layouts/AppLayout";
import { RequireCapability } from "./middlewares/RequireCapability";
import { ProtectedRoute } from "./middlewares/ProtectedRoute";
import { PublicOnlyRoute } from "./middlewares/PublicOnlyRoute";
import { LoginPage } from "./routes/login";
import { NewChatPage } from "./routes/chat";
import { ChatThreadPage } from "./routes/chat.$id";
import { OrgFilesPage } from "./routes/admin.files";
import { UsersPage } from "./routes/users";
import { RolesPage } from "./routes/admin.roles";
import { GroupsPage } from "./routes/admin.groups";
import { GroupAccessPage } from "./routes/admin.groups.$id.access";
import { UserAccessPage } from "./routes/admin.users.$id.access";

export const router = createBrowserRouter([
  {
    element: <AppProvider />,
    children: [
      {
        element: <PublicOnlyRoute />,
        children: [{ path: "/login", element: <LoginPage /> }],
      },
      {
        element: <ProtectedRoute />,
        children: [
          {
            element: <AppLayout />,
            children: [
              { path: "/", element: <NewChatPage /> },
              { path: "/chat/:id", element: <ChatThreadPage /> },
              // Any authenticated member may reach the unified file browser: every action
              // inside it is independently gated per node via effective_permission /
              // is_structure_manager, so a member with zero grants simply sees an empty tree.
              { path: "/admin/files", element: <OrgFilesPage /> },
              {
                element: <RequireCapability capability="manage_users" />,
                children: [
                  { path: "/users", element: <UsersPage /> },
                  {
                    // Same reasoning as the group access route: granting
                    // access requires seeing the full org tree, which needs
                    // manage_org_files_structure on top of manage_users.
                    element: <RequireCapability capability="manage_org_files_structure" />,
                    children: [{ path: "/admin/users/:id/access", element: <UserAccessPage /> }],
                  },
                ],
              },
              {
                element: <RequireCapability capability="manage_groups" />,
                children: [
                  { path: "/admin/groups", element: <GroupsPage /> },
                  {
                    // Granting access to others requires seeing the FULL org tree, which
                    // /me/org-files/* only returns for a structure manager (or superuser).
                    // manage_groups alone is not enough — require both capabilities.
                    element: <RequireCapability capability="manage_org_files_structure" />,
                    children: [{ path: "/admin/groups/:id/access", element: <GroupAccessPage /> }],
                  },
                ],
              },
              {
                element: <RequireCapability superuser />,
                children: [{ path: "/admin/roles", element: <RolesPage /> }],
              },
            ],
          },
        ],
      },
    ],
  },
]);
