// The canvas must stay clickable. React Flow stamps `pointer-events: none` on
// the wrapper of any node that is neither selectable nor draggable when no node
// mouse handler is registered (NodeWrapper's `hasPointerEvents`) — and that is
// EVERY node the flow canvas draws, because selection is the workspace store's
// job, not React Flow's. Without an explicit opt-in on the node shell, clicks
// fall through the card into the pan surface and every in-node control (expand,
// drill-in, select) is dead to the mouse while still looking interactive.
//
// This pins both halves: React Flow really does turn pointer events off, and
// every node type really does turn them back on.
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { ReactFlow, ReactFlowProvider, type Node } from "@xyflow/react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"

import { parseWorkspaceParams } from "@/lib/wadi/routes"
import {
  createWorkspaceStore,
  WorkspaceStoreContext,
} from "@/components/endpoint/workspace-store"
import {
  FlowActionsContext,
  type FlowActions,
} from "@/components/flow/flow-chrome"
import { CondensedNode } from "@/components/flow/nodes/condensed-node"
import { GhostNode } from "@/components/flow/nodes/ghost-node"
import { LaneNode, MethodNode } from "@/components/flow/nodes/method-lane"
import { StatementNode } from "@/components/flow/nodes/statement-node"

// jsdom ships neither of these; React Flow measures nodes with the first and
// reads transforms with the second. Stubs are enough — the assertions below are
// about markup and handlers, never about measured geometry.
beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  globalThis.DOMMatrixReadOnly ??= class {
    m22 = 1
  } as unknown as typeof DOMMatrixReadOnly
})

// vitest runs without `globals`, so testing-library's auto-cleanup is off and
// mounted canvases would otherwise pile up across cases.
afterEach(cleanup)

const nodeTypes = {
  method: MethodNode,
  lane: LaneNode,
  statement: StatementNode,
  condensed: CondensedNode,
  ghost: GhostNode,
}

function noopActions(overrides: Partial<FlowActions> = {}): FlowActions {
  return {
    selectNode: vi.fn(),
    toggleMethod: vi.fn(),
    expandRun: vi.fn(),
    focusMethod: vi.fn(),
    revealSource: vi.fn(),
    ...overrides,
  }
}

/** Mount nodes on a real ReactFlow canvas configured exactly as the workspace
 * configures it — non-selectable, non-draggable, no node mouse handlers. */
function renderCanvas(nodes: Node[], actions: FlowActions = noopActions()) {
  const store = createWorkspaceStore(
    parseWorkspaceParams(new URLSearchParams())
  )
  return render(
    <WorkspaceStoreContext.Provider value={store}>
      <FlowActionsContext.Provider value={actions}>
        <ReactFlowProvider>
          <div style={{ width: 800, height: 600 }}>
            <ReactFlow
              nodes={nodes}
              edges={[]}
              nodeTypes={nodeTypes}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable={false}
            />
          </div>
        </ReactFlowProvider>
      </FlowActionsContext.Provider>
    </WorkspaceStoreContext.Provider>
  )
}

const BASE = { position: { x: 0, y: 0 }, selectable: false, draggable: false }

const METHOD_NODE: Node = {
  ...BASE,
  id: "method:m_1",
  type: "method",
  data: {
    methodId: "m_1",
    signature: "PetService.getPet(String)",
    isRoot: false,
    statementCount: 3,
    branchCount: 1,
    loopCount: 0,
    sinks: [],
    badges: [],
  },
}

const STATEMENT_NODE: Node = {
  ...BASE,
  id: "stmt:n_1",
  type: "statement",
  data: {
    icfgNodeId: "n_1",
    methodId: "m_1",
    sourceText: "return repo.findById(id);",
    file: "PetService.java",
    line: 42,
    kind: "call",
    constructKind: null,
    conditionExpression: null,
    sink: null,
    unopenableReason: null,
    exitArms: [],
    hasRemote: false,
    conditions: [],
  },
}

const CONDENSED_NODE: Node = {
  ...BASE,
  id: "run:r_1",
  type: "condensed",
  data: {
    runId: "r_1",
    methodId: "m_1",
    count: 4,
    file: "PetService.java",
    startLine: 10,
    endLine: 13,
  },
}

const GHOST_NODE: Node = {
  ...BASE,
  id: "ghost:g_1",
  type: "ghost",
  data: {
    label: "order-service",
    targetKind: "service",
    confidence: "high",
    verbs: ["GET"],
    conditions: [],
  },
}

const ALL_NODES = [METHOD_NODE, STATEMENT_NODE, CONDENSED_NODE, GHOST_NODE]

describe("canvas nodes stay reachable by the mouse", () => {
  it("React Flow disables pointer events on the wrapper (the defect's cause)", () => {
    const { container } = renderCanvas(ALL_NODES)
    const wrappers =
      container.querySelectorAll<HTMLElement>(".react-flow__node")
    expect(wrappers.length).toBe(ALL_NODES.length)
    // If this ever flips to "all", React Flow changed its rule and the opt-in
    // below is merely redundant — not wrong. The assertion below is the one
    // that must hold either way.
    for (const wrapper of wrappers) {
      expect(wrapper.style.pointerEvents).toBe("none")
    }
  })

  it("every node type opts its shell back in", () => {
    const { container } = renderCanvas(ALL_NODES)
    const wrappers =
      container.querySelectorAll<HTMLElement>(".react-flow__node")
    for (const wrapper of wrappers) {
      const shell = wrapper.firstElementChild
      expect(shell, `${wrapper.className} rendered no shell`).not.toBeNull()
      expect(
        shell?.classList.contains("pointer-events-auto"),
        `${wrapper.className} shell does not re-enable pointer events`
      ).toBe(true)
    }
  })

  it("keeps the expanded lane header clickable too", () => {
    const { container } = renderCanvas([
      {
        ...BASE,
        id: "lane:m_1",
        type: "lane",
        data: {
          methodId: "m_1",
          signature: "PetService.getPet(String)",
          isRoot: true,
          width: 300,
          height: 200,
        },
      },
    ])
    const header = container.querySelector(".react-flow__node > div > div")
    expect(header?.classList.contains("pointer-events-auto")).toBe(true)
  })
})

// These dispatch events directly, so they prove the WIRING, not hittability —
// jsdom does no hit-testing and would pass even with pointer events off. The
// `pointer-events-auto` assertion above is what guards the click actually
// landing; keep both.
describe("per-method expansion is wired to the node's own control", () => {
  it("expands just that method when its chevron is clicked", () => {
    const toggleMethod = vi.fn()
    renderCanvas([METHOD_NODE], noopActions({ toggleMethod }))
    fireEvent.click(screen.getByTitle("Expand into statements"))
    expect(toggleMethod).toHaveBeenCalledWith("m_1")
  })

  it("collapses just that method when the lane chevron is clicked", () => {
    const toggleMethod = vi.fn()
    renderCanvas(
      [
        {
          ...BASE,
          id: "lane:m_1",
          type: "lane",
          data: {
            methodId: "m_1",
            signature: "PetService.getPet(String)",
            isRoot: true,
            width: 300,
            height: 200,
          },
        },
      ],
      noopActions({ toggleMethod })
    )
    fireEvent.click(screen.getByTitle("Collapse to a method card"))
    expect(toggleMethod).toHaveBeenCalledWith("m_1")
  })

  it("toggling one method leaves the rest of the expanded set alone", () => {
    const store = createWorkspaceStore(
      parseWorkspaceParams(new URLSearchParams("expand=m_1,m_2"))
    )
    const resolved = new Set(["m_1", "m_2"])
    store.getState().toggleMethod("m_3", resolved)
    const after = store.getState().expand
    expect(after.mode).toBe("explicit")
    expect(after.mode === "explicit" ? [...after.ids].sort() : []).toEqual([
      "m_1",
      "m_2",
      "m_3",
    ])

    store.getState().toggleMethod("m_1", new Set(["m_1", "m_2", "m_3"]))
    const collapsed = store.getState().expand
    expect(
      collapsed.mode === "explicit" ? [...collapsed.ids].sort() : []
    ).toEqual(["m_2", "m_3"])
  })
})
