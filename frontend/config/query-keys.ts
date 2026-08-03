export const QUERY_KEYS = {
  systems: ["systems"] as const,
  snapshots: (systemId: string) => ["snapshots", systemId] as const,
  services: (snapshotId: string) => ["services", snapshotId] as const,
  endpoints: (snapshotId: string, serviceId: string) =>
    ["endpoints", snapshotId, serviceId] as const,
  icfg: (snapshotId: string, endpointId: string) =>
    ["icfg", snapshotId, endpointId] as const,
  coverage: (snapshotId: string) => ["coverage", snapshotId] as const,
  remoteEdges: (snapshotId: string, serviceId: string) =>
    ["remote-edges", snapshotId, serviceId] as const,
  systemGraph: (snapshotId: string) => ["system-graph", snapshotId] as const,
  sourceFile: (
    snapshotId: string,
    serviceId: string,
    file: string,
    startLine: number
  ) => ["source-file", snapshotId, serviceId, file, startLine] as const,
  source: (
    snapshotId: string,
    serviceId: string,
    file: string,
    startLine: number,
    endLine: number
  ) => ["source", snapshotId, serviceId, file, startLine, endLine] as const,
}
