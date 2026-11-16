import { describe, expect, test } from "vitest"

import {
  parseWorkspaceParams,
  serializeWorkspaceParams,
} from "@/lib/wadi/routes"
import {
  createWorkspaceStore,
  expandToParams,
  workspaceParamsOf,
} from "@/components/endpoint/workspace-store"

describe("workspace store (§11 Phase 2.8)", () => {
  test("hydrates from URL params and mirrors back", () => {
    const params = parseWorkspaceParams(
      new URLSearchParams("node=stmt:n1&focus=m_2&expand=m_1,m_2")
    )
    const store = createWorkspaceStore(params)
    const state = store.getState()
    expect(state.selectedNodeId).toBe("stmt:n1")
    expect(state.focusMethodId).toBe("m_2")
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

  test("revealSource points the panel at a line and bumps the token every time", () => {
    // Source is always on screen now, so "open in source" points the panel at
    // a line rather than swapping the graph out from under the reader.
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store.getState().revealSource("src/A.java", 42)
    const first = store.getState()
    expect(first.sourceTarget).toMatchObject({ file: "src/A.java", line: 42 })
    store.getState().revealSource("src/A.java", 42)
    expect(store.getState().sourceTarget?.token).toBe(
      (first.sourceTarget?.token ?? 0) + 1
    )
  })

  test("selecting a node records exactly what was selected", () => {
    // §5.2.9 UI: the workspace has no tab strip to steer any more. The source
    // panel highlights the selection and its header states what the selection
    // means, so selection is now just an id — no panel policy rides on it.
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store.getState().selectNode("stmt:n9")
    expect(store.getState().selectedNodeId).toBe("stmt:n9")
    store.getState().selectNode("ghost:svc_orders")
    expect(store.getState().selectedNodeId).toBe("ghost:svc_orders")
    store.getState().selectNode(null)
    expect(store.getState().selectedNodeId).toBeNull()
  })

  test("applyUrlParams moves the UI on back/forward, not just the URL", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store.getState().selectNode("stmt:n9")
    store.getState().setFocus("m_7")
    // Simulate popstate back to the entry URL.
    store.getState().applyUrlParams(parseWorkspaceParams(new URLSearchParams()))
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
        parseWorkspaceParams(new URLSearchParams("file=src/A.java"))
      )
    expect(store.getState().sourceTarget?.line).toBe(42)
  })

  test("a ?file deep link seeds the source target", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams("file=src/A.java"))
    )
    expect(store.getState().sourceTarget?.file).toBe("src/A.java")
  })

  test("the Data pane and its selected entity hydrate from the URL", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(
        new URLSearchParams("pane=data&entity=com.acme.pets.Pet")
      )
    )
    expect(store.getState().pane).toBe("data")
    expect(store.getState().selectedEntity).toBe("com.acme.pets.Pet")
  })

  test("selecting an entity opens the Data pane; leaving it clears the entity", () => {
    // The highlight belongs to the Data list (R1-26): back on the call tree
    // there is no row to say what the lit nodes mean.
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    expect(store.getState().pane).toBe("calls")
    store.getState().selectEntity("com.acme.pets.Pet")
    expect(store.getState().pane).toBe("data")
    expect(store.getState().selectedEntity).toBe("com.acme.pets.Pet")
    store.getState().setPane("calls")
    expect(store.getState().selectedEntity).toBeNull()
  })

  test("applyUrlParams restores the pane and entity on back/forward", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store
      .getState()
      .applyUrlParams(
        parseWorkspaceParams(
          new URLSearchParams("pane=data&entity=%7Eundetermined")
        )
      )
    expect(store.getState().pane).toBe("data")
    expect(store.getState().selectedEntity).toBe("~undetermined")
    store.getState().applyUrlParams(parseWorkspaceParams(new URLSearchParams()))
    expect(store.getState().pane).toBe("calls")
    expect(store.getState().selectedEntity).toBeNull()
  })

  test("the store mirrors pane and entity back to the URL form", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams())
    )
    store.getState().selectEntity("com.acme.pets.Pet")
    expect(
      serializeWorkspaceParams(workspaceParamsOf(store.getState())).toString()
    ).toBe("pane=data&entity=com.acme.pets.Pet")
  })
})
