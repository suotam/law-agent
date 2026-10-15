import { useEffect } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useFolderLevel } from "../api/get-folders";

type SegmentProps = {
  parentId: string | null;
  folderId: string;
  level: number;
  isLast: boolean;
  onNavigate: (level: number) => void;
  onMissing: (level: number) => void;
};

/*
 * One component per level rather than a loop of hooks: the name of a level is only obtainable
 * from its parent's children list, which is a separate query per level.
 */
const BreadcrumbSegment = ({
  parentId,
  folderId,
  level,
  isLast,
  onNavigate,
  onMissing,
}: SegmentProps) => {
  const { data, isSuccess } = useFolderLevel(parentId);
  const folder = data?.folders.find((item) => item.id === folderId);

  useEffect(() => {
    // An id the parent does not list is a folder deleted meanwhile; the path stops being valid here.
    if (isSuccess && folder === undefined) onMissing(level);
  }, [isSuccess, folder, level, onMissing]);

  if (folder === undefined) return null;

  return (
    <>
      <ChevronRight
        aria-hidden="true"
        className="text-muted-foreground size-4 shrink-0"
      />
      {isLast ? (
        <span className="truncate font-medium">{folder.name}</span>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onNavigate(level + 1)}
        >
          {folder.name}
        </Button>
      )}
    </>
  );
};

type BreadcrumbProps = {
  pathIds: string[];
  onNavigate: (level: number) => void;
  onMissing: (level: number) => void;
};

export const Breadcrumb = ({ pathIds, onNavigate, onMissing }: BreadcrumbProps) => {
  const { t } = useTranslation();

  return (
    <nav
      aria-label={t("orgFiles.breadcrumbLabel")}
      className="flex min-w-0 items-center gap-1 text-sm"
    >
      {pathIds.length === 0 ? (
        <span className="truncate font-medium">{t("orgFiles.rootLabel")}</span>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onNavigate(0)}
        >
          {t("orgFiles.rootLabel")}
        </Button>
      )}

      {pathIds.map((folderId, index) => (
        <BreadcrumbSegment
          key={folderId}
          parentId={index === 0 ? null : pathIds[index - 1]}
          folderId={folderId}
          level={index}
          isLast={index === pathIds.length - 1}
          onNavigate={onNavigate}
          onMissing={onMissing}
        />
      ))}
    </nav>
  );
};
