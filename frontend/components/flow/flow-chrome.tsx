"use client"

// Shared canvas chrome: the node shell (handles + selection ring) and the
// actions context. Actions are STABLE callbacks reading refs — node
// components never receive closures through React Flow `data`, so selection
// and hover changes re-render only the nodes that subscribe to them.
import { createContext, memo, useContext } from "react"
import { Handle, Position } from "@xyflow/react"

import { cn } from "@/lib/utils"
import { useWorkspaceStore } from "@/components/endpoint/workspace-store"

export interface FlowActions {
  selectNode: (id: string) => void
  toggleMethod: (methodId: string) => void
  expandRun: (runId: string) => void
  focusMethod: (methodId: string) => void
  revealSource: (file: string, line: number) => void
}

export const FlowActionsContext = createContext<FlowActions | null>(null)

export function useFlowActions(): FlowActions {
  const actions = useContext(FlowActionsContext)
  if (!actions) throw new Error("useFlowActions requires FlowActionsContext")
  return actions
}

const HIDDEN_HANDLE = {
  opacity: 0,
  width: 1,
  height: 1,
  minWidth: 0,
  minHeight: 0,
}

/** Invisible anchor handles: top/bottom for intra-method flow, left for the
 * call gutter, right for the ghost rail and back-edge loops. */
function NodeAnchors() {
  return (
    <>
      <Handle
        id="t-top"
        type="target"
        position={Position.Top}
        style={HIDDEN_HANDLE}
      />
      <Handle
        id="s-bottom"
        type="source"
        position={Position.Bottom}
        style={HIDDEN_HANDLE}
      />
      <Handle
        id="t-left"
        type="target"
        position={Position.Left}
        style={HIDDEN_HANDLE}
      />
      <Handle
        id="s-left"
        type="source"
        position={Position.Left}
        style={HIDDEN_HANDLE}
      />
      <Handle
        id="t-right"
        type="target"
        position={Position.Right}
        style={HIDDEN_HANDLE}
      />
      <Handle
        id="s-right"
        type="source"
        position={Position.Right}
        style={HIDDEN_HANDLE}
      />
    </>
  )
}

export const NodeShell = memo(function NodeShell({
  id,
  className,
  children,
  trace,
  onClick,
}: {
  id: string
  className?: string
  children: React.ReactNode
  trace?: "hot" | "dim" | null
  onClick?: () => void
}) {
  const selected = useWorkspaceStore((s) => s.selectedNodeId === id)
  return (
    // No `role="button"`: the shell wraps real <button> children (expand,
    // focus, drill-in), and an interactive control inside a role=button is
    // invalid ARIA. Keyboard reaches nodes through the canvas keymap; what the
    // shell owes assistive tech is its SELECTED state, which the ring alone
    // conveys only visually.
    <div
      aria-current={selected ? "true" : undefined}
      onClick={onClick}
      className={cn(
        "relative rounded-md border bg-card text-card-foreground transition-[box-shadow,opacity]",
        selected && "ring-2 ring-ring",
        trace === "dim" && "opacity-25",
        trace === "hot" && "border-foreground/40",
        className
      )}
    >
      <NodeAnchors />
      {children}
    </div>
  )
})
