import { describe, expect, test } from "vitest"

import { parseWorkspaceParams } from "@/lib/wadi/routes"
import {
  createWorkspaceStore,
  expandToParams,
} from "@/components/endpoint/workspace-store"

describe("workspace store (§11 Phase 2.8)", () => {
  test("hydrates from URL params and mirrors back", () => {
    const params = parseWorkspaceParams(
      new URLSearchParams("node=stmt:n1&focus=m_2&expand=m_1,m_2&lens=source")
    )
    const store = createWorkspaceStore(params)
    const state = store.getState()
    expect(state.selectedNodeId).toBe("stmt:n1")
    expect(state.focusMethodId).toBe("m_2")
    expect(state.lens).toBe("source")
    expect(expandToParams(state.expand)).toEqual(["m_1", "m_2"])
  })

  test("toggleMethod snapshots the resolved set into an explicit state", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    expect(store.getState().expand.mode).toBe("default")
    store.getState().toggleMethod("m_2", new Set(["m_1"]))
    expect(expandToParams(store.getState().expand)).toEqual(
      expect.arrayContaining(["m_1", "m_2"])
    )
    store.getState().toggleMethod("m_1", new Set(["m_1", "m_2"]))
    expect(expandToParams(store.getState().expand)).toEqual(["m_2"])
  })

  test("expand-all / collapse-all round-trip as sentinels", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store.getState().expandAll()
    expect(expandToParams(store.getState().expand)).toBe("all")
    store.getState().collapseAll()
    expect(expandToParams(store.getState().expand)).toBe("none")
    expect(store.getState().expandedRuns.size).toBe(0)
  })

  test("revealSource opens the Source tab and bumps the token every time", () => {
    // Source is always on screen now, so "open in source" points the panel at
    // a line rather than swapping the graph out from under the reader.
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store.getState().revealSource("src/A.java", 42)
    const first = store.getState()
    expect(first.inspectorTab).toBe("source")
    expect(first.lens).toBe("graph")
    expect(first.sourceTarget).toMatchObject({ file: "src/A.java", line: 42 })
    store.getState().revealSource("src/A.java", 42)
    expect(store.getState().sourceTarget?.token).toBe(
      (first.sourceTarget?.token ?? 0) + 1
    )
  })

  test("applyUrlParams moves the UI on back/forward, not just the URL", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store.getState().setLens("source")
    store.getState().selectNode("stmt:n9")
    expect(store.getState().lens).toBe("source")
    // Simulate popstate back to the entry URL.
    store.getState().applyUrlParams(parseWorkspaceParams(new URLSearchParams()))
    expect(store.getState().lens).toBe("graph")
    expect(store.getState().selectedNodeId).toBeNull()
    expect(store.getState().focusMethodId).toBeNull()
    expect(store.getState().expand.mode).toBe("default")
  })

  test("applyUrlParams keeps the source line when the file is unchanged", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store.getState().revealSource("src/A.java", 42)
    store
      .getState()
      .applyUrlParams(
        parseWorkspaceParams(new URLSearchParams("lens=source&file=src/A.java"))
      )
    expect(store.getState().sourceTarget?.line).toBe(42)
  })

  test("a ?file deep link seeds the source target", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams("lens=source&file=src/A.java"))
    )
    expect(store.getState().sourceTarget?.file).toBe("src/A.java")
  })
})
