import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import { parsePath, serializePath, useFolderPath } from "../path";

const Probe = () => {
  const { pathIds, folderId, open, goToLevel } = useFolderPath();

  return (
    <div>
      <p data-testid="path">{serializePath(pathIds)}</p>
      <p data-testid="folder">{folderId ?? "root"}</p>
      <button onClick={() => open("c")}>open c</button>
      <button onClick={() => goToLevel(1)}>go to level 1</button>
      <button onClick={() => goToLevel(0)}>go to root</button>
    </div>
  );
};

describe("parsePath", () => {
  it("reads an id chain and ignores empty segments", () => {
    expect(parsePath("a/b/c")).toEqual(["a", "b", "c"]);
    expect(parsePath("/a//b/")).toEqual(["a", "b"]);
  });

  it("treats a missing parameter as the root", () => {
    expect(parsePath(null)).toEqual([]);
    expect(parsePath("")).toEqual([]);
  });
});

describe("useFolderPath", () => {
  it("opens the last id in the chain", () => {
    renderWithProviders(<Probe />, { route: "/admin/files?path=a/b" });

    expect(screen.getByTestId("folder")).toHaveTextContent("b");
  });

  it("is at the root with no parameter", () => {
    renderWithProviders(<Probe />, { route: "/admin/files" });

    expect(screen.getByTestId("folder")).toHaveTextContent("root");
  });

  it("appends a folder when opening one and truncates when going up", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Probe />, { route: "/admin/files?path=a/b" });

    await user.click(screen.getByRole("button", { name: "open c" }));
    expect(screen.getByTestId("path")).toHaveTextContent("a/b/c");

    await user.click(screen.getByRole("button", { name: "go to level 1" }));
    expect(screen.getByTestId("path")).toHaveTextContent("a");

    await user.click(screen.getByRole("button", { name: "go to root" }));
    expect(screen.getByTestId("path")).toBeEmptyDOMElement();
  });
});
