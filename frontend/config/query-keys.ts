export const QUERY_KEYS = {
	systems: ["systems"] as const,
	snapshots: (systemId: string) => ["snapshots", systemId] as const,
	services: (snapshotId: string) => ["services", snapshotId] as const,
	endpoints: (snapshotId: string, serviceId: string) =>
		["endpoints", snapshotId, serviceId] as const,
	icfg: (snapshotId: string, endpointId: string) =>
		["icfg", snapshotId, endpointId] as const,
};
