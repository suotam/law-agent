import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

const PATH_PARAM = "path";

/*
 * The whole ancestor chain lives in the URL, not just the open folder: the API has no
 * `GET /folders/{id}`, so the breadcrumb can only be rebuilt from the ids of the levels above.
 */
export const parsePath = (raw: string | null): string[] =>
  (raw ?? "").split("/").filter((segment) => segment.length > 0);

export const serializePath = (ids: string[]): string => ids.join("/");

type FolderPath = {
  pathIds: string[];
  /** The open folder, or null at the root. */
  folderId: string | null;
  open: (id: string) => void;
  /** `0` is the root; `n` opens the folder at index `n - 1` of the chain. */
  goToLevel: (level: number) => void;
};

export const useFolderPath = (): FolderPath => {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get(PATH_PARAM);
  const pathIds = useMemo(() => parsePath(raw), [raw]);

  const setPath = useCallback(
    (ids: string[]) =>
      setSearchParams(ids.length === 0 ? {} : { [PATH_PARAM]: serializePath(ids) }),
    [setSearchParams],
  );

  return {
    pathIds,
    folderId: pathIds.at(-1) ?? null,
    open: (id) => setPath([...pathIds, id]),
    goToLevel: (level) => setPath(pathIds.slice(0, level)),
  };
};
