export const QUERY_KEYS = {
  systems: ["systems"] as const,
  snapshots: (systemId: string) => ["snapshots", systemId] as const,
  snapshot: (snapshotId: string) => ["snapshot", snapshotId] as const,
  services: (snapshotId: string) => ["services", snapshotId] as const,
  endpoints: (snapshotId: string, serviceId: string) =>
    ["endpoints", snapshotId, serviceId] as const,
  icfg: (snapshotId: string, endpointId: string) =>
    ["icfg", snapshotId, endpointId] as const,
  endpointDetail: (snapshotId: string, endpointId: string) =>
    ["endpoint-detail", snapshotId, endpointId] as const,
  coverage: (snapshotId: string) => ["coverage", snapshotId] as const,
  remoteEdges: (snapshotId: string, serviceId: string) =>
    ["remote-edges", snapshotId, serviceId] as const,
  systemGraph: (snapshotId: string) => ["system-graph", snapshotId] as const,
  systemAuth: (snapshotId: string) => ["system-auth", snapshotId] as const,
  endpointDependencies: (snapshotId: string, serviceId: string) =>
    ["endpoint-dependencies", snapshotId, serviceId] as const,
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
