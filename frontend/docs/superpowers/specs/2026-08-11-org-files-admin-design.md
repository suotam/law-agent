# Org files admin — design

Admin-only file manager for the organisation's document library: browse folders, create and
rename folders, upload, download and delete files. Backed by the `/folders`, `/folders/{id}/files`
and `/org-files/{id}` endpoints described in `2026-08-09-backend-api-fe-notes.md`.

## Scope

In scope: browsing one folder at a time, creating and renaming folders, deleting empty folders,
uploading files into the current folder, downloading and deleting files.

Out of scope, deliberately: moving folders (`PATCH /folders/{id}` accepts `parent_id`, but nothing
asks for it yet), search across the tree, multi-select bulk actions, and any client-side cascade
delete.

## Route, guard, entry point

`AdminRoute` (`src/app/middlewares/AdminRoute.tsx`) nests inside `ProtectedRoute`, reads
`useAuth()` and redirects to `/` with `<Navigate replace>` when `user.role !== "admin"`. It is a
redirect rather than a 403 screen: a member never sees a link to the section and does not need to
learn it exists.

The page lives at `/admin/files` inside `AppLayout`, so the sidebar stays available and an admin
returns to the chat in one click:

```
ProtectedRoute → AppLayout → { "/", "/chat/:id", AdminRoute → "/admin/files" }
```

The entry point is an item in `AccountMenu`, above logout, rendered only when
`user.role === "admin"`. The route guard remains the real authority; the menu only decides what is
drawn.

## Feature structure

New feature `src/features/org-files/`, following the existing feature layout except that each
endpoint owns one file holding both its call and its hook:

```
org-files/
  api/
    query-keys.ts         orgFileQueryKeys
    get-folders.ts        listFolders + useFolders(parentId)
    create-folder.ts      createFolder + useCreateFolder()
    update-folder.ts      updateFolder + useUpdateFolder()
    delete-folder.ts      deleteFolder + useDeleteFolder()
    get-org-files.ts      listOrgFiles + useOrgFiles(folderId)
    upload-org-file.ts    uploadOrgFile + useUploadOrgFile()
    delete-org-file.ts    deleteOrgFile + useDeleteOrgFile()
    download-org-file.ts  downloadOrgFile + useDownloadOrgFile()
  components/
    FileBrowser.tsx       page body: header, list, upload wiring
    Breadcrumb.tsx
    ItemList.tsx
    FolderRow.tsx
    FileRow.tsx
    FolderDialog.tsx      create and rename share one dialog
    UploadDropzone.tsx
  path.ts                 ?path= encoding, decoding and ancestor chain
  types.ts
  index.ts                barrel export
```

Query keys live in their own file because `create-folder` has to invalidate a key owned by
`get-folders`; keeping them separate avoids imports pointing both ways between endpoint files.

`src/components/ui/dialog.tsx` is added from shadcn — the project currently has only
`alert-dialog`, and the folder dialog is not a confirmation.

## Data layer and the path in the URL

```ts
orgFileQueryKeys = {
  folders: (parentId: string | null) => ["org-folders", parentId],
  files: (folderId: string) => ["org-files", folderId],
};
```

`parentId === null` means the root, i.e. `GET /folders` with no parameter.

The current location is `?path=id1/id2/id3`, the last id being the open folder; the root is the
absent or empty parameter. `path.ts` reads and writes it through `useSearchParams`.

The API exposes no `GET /folders/{id}` and no whole-tree endpoint, so a breadcrumb cannot be built
from a bare folder id. It is resolved instead from the children lists: the name of level `i` is
found by looking up `path[i]` in the already-fetched `folders(path[i - 1])`. Walking down populates
exactly those queries anyway, and a deep link fills them top to bottom. When an id is missing from
its parent's list — deleted meanwhile — the breadcrumb truncates at the last valid level and the
view navigates there.

## Screen

**Header**, sticky above the list: the breadcrumb `Dokumenty / Smlouvy / 2026`, where every ancestor
is a button jumping to its level and the last segment is plain text. On the right, `Nová složka` and
`Nahrát soubor`, both always acting on the folder currently open.

**The root holds folders only.** Both `GET /folders/{id}/files` and `POST /folders/{id}/files` are
scoped to a folder and the API offers no equivalent outside one, so at the root the file query is
not issued at all, `Nahrát soubor` is disabled with the hint "Soubory lze nahrát jen do složky" and
dropping files there does nothing.

**List**: a single `<ul>` with folders first (sorted by name) and files below (sorted by name). A
folder row is a button that appends its id to `?path=`; a file row is not interactive. Every row
carries a `…` menu (`Popover`, as in `AccountMenu`) — folder: rename, delete; file: download, delete.
A file row shows filename, size and type.

**States**: `Skeleton` rows while loading; an empty folder shows "Složka je prázdná" plus the same
two actions; a failed load shows the message from `translateError` and a retry button.

## Uploads

`UploadDropzone` wraps the list, so a drop anywhere in the area uploads into the current folder and
the area highlights its border while dragging. `Nahrát soubor` opens `<input type="file" multiple>`
with `FILE_INPUT_ACCEPT`.

Every file goes in its own request (`useUploadOrgFile`, `timeout: 0` like chat attachments, since
the upload blocks until the document is parsed and indexed) and lives as a record in the screen's
local state: `{ localId, folderId, filename, status, error? }`. Pending rows render among the
finished files with a spinner; on `201` the record is dropped and the real file arrives from the
invalidated `useOrgFiles`.

A file refused by `rejectionKeyFor` (wrong type, over 25 MB) never reaches the network — its row
states the reason and offers dismissal, not retry, because the same file would fail identically.
A failed request offers retry; `409` (the same blob already in this folder) gets its own message and
no retry.

Changing folders mid-upload cancels nothing: a pending record belongs to the folder it was uploaded
into and reappears when the user returns there.

## Download, delete, errors

Download cannot be a plain `<a href>` — the endpoint needs the `Authorization` header.
`downloadOrgFile` requests it with `responseType: "blob"` and `timeout: 0`, wraps the blob in
`URL.createObjectURL`, clicks a hidden anchor with `download={filename}` (the name is known from the
list, so `Content-Disposition` needs no parsing) and revokes the URL immediately. While a download
runs, its menu item shows a spinner so a double click cannot fire two requests.

Deleting a file or a folder is confirmed by `AlertDialog`, following `ConversationListItem`. For a
folder, a `409` keeps the dialog open and shows "Složku nelze smazat, obsahuje soubory nebo
podsložky" — the API deletes only empty folders and there is no move endpoint for files, so cleaning
up is the admin's job and the UI invents no operation the API lacks.

`FolderDialog` serves both creation and renaming, differing only in title and default value.
Validation is `react-hook-form` + `zod` (non-empty after trim, bounded length). A `409` maps to a
field error — "Složka s tímto jménem už tady je" — and leaves the dialog open with focus in the
field.

Everything else goes through `translateError`. A `403` barely reaches this screen because of the
guard, and a `401` is handled by the axios interceptor ending the session.

All copy is added under a new `orgFiles` section in `src/assets/locales/cs.json`; no strings are
hard-coded in components.

## Tests

Vitest and MSW, in `features/org-files/tests/`:

- `path.test.ts` — encoding and decoding of `?path=`, truncation at the last valid level.
- `FileBrowser.test.tsx` — folders render above files; clicking a folder extends `?path=`, clicking a
  breadcrumb segment shortens it; an empty folder shows the empty state.
- `folder-actions.test.tsx` — create (invalidates the listing), rename, `409` on either keeps the
  dialog open; deleting a non-empty folder shows its message.
- `upload.test.tsx` — an oversized file is refused without a request, a successful upload replaces
  its pending row, a failed one offers retry.

## Frontend changes

Everything here is frontend-only; no backend change is required.

Added:

- `src/app/middlewares/AdminRoute.tsx`
- `src/app/routes/admin.files.tsx`
- `src/features/org-files/**` (see the structure above)
- `src/components/ui/dialog.tsx`

Modified:

- `src/app/router.tsx` — the `/admin/files` route behind `AdminRoute`
- `src/features/auth/components/AccountMenu.tsx` — the admin-only link
- `src/assets/locales/cs.json` — the `orgFiles` section
