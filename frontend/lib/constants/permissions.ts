/**
 * Permission constants for Better Auth admin plugin
 * These permissions MUST match your backend Better Auth configuration exactly
 *
 * Backend permission statement:
 * {
 *   user: ['create', 'list', 'update', 'delete', 'set-role', 'set-password', 'ban', 'unban', 'impersonate'],
 *   session: ['list', 'revoke', 'revoke-all']
 * }
 */

/**
 * User management permissions
 * These match the backend 'user' namespace exactly
 */
export const USER_PERMISSIONS = {
	CREATE: ['user', 'create'] as const,
	LIST: ['user', 'list'] as const,
	UPDATE: ['user', 'update'] as const,
	DELETE: ['user', 'delete'] as const,
	SET_ROLE: ['user', 'set-role'] as const,
	SET_PASSWORD: ['user', 'set-password'] as const,
	BAN: ['user', 'ban'] as const,
	UNBAN: ['user', 'unban'] as const,
	IMPERSONATE: ['user', 'impersonate'] as const,
} as const

/**
 * Session management permissions
 * These match the backend 'session' namespace exactly
 */
export const SESSION_PERMISSIONS = {
	LIST: ['session', 'list'] as const,
	REVOKE: ['session', 'revoke'] as const,
	REVOKE_ALL: ['session', 'revoke-all'] as const,
} as const


/**
 * All permissions grouped by category
 */
export const PERMISSIONS = {
	USER: USER_PERMISSIONS,
	SESSION: SESSION_PERMISSIONS,
} as const

/**
 * Common permission sets for preloading
 * These are loaded in the admin layout to avoid loading states
 */
export const COMMON_ADMIN_PERMISSIONS = [
	USER_PERMISSIONS.CREATE,
	USER_PERMISSIONS.UPDATE,
	USER_PERMISSIONS.DELETE,
	USER_PERMISSIONS.SET_ROLE,
	USER_PERMISSIONS.BAN,
	USER_PERMISSIONS.UNBAN,
	USER_PERMISSIONS.IMPERSONATE,
	SESSION_PERMISSIONS.LIST,
	SESSION_PERMISSIONS.REVOKE,
	SESSION_PERMISSIONS.REVOKE_ALL,
] as const

/**
 * Type helper for permission tuples
 */
export type PermissionTuple = readonly [string, string]
