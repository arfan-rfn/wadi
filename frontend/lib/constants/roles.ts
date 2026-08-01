/**
 * Centralized role definitions and access control groups
 * This is the single source of truth for all role-based access control
 */

/**
 * All available roles in the system
 * Add new roles here as your application grows
 */
export const ROLES = {
	USER: 'user',
	MODERATOR: 'moderator',
	ADMIN: 'admin',
	// Future roles can be added here:
	// SUPER_ADMIN: 'super-admin',
	// SUPPORT: 'support',
	// EDITOR: 'editor',
} as const

/**
 * Role groups define which roles have access to specific features
 * To add a new role to admin panel access, just add it to this array
 */
export const ROLE_GROUPS = {
	/**
	 * Roles that can access the admin panel
	 * Add new privileged roles here to grant admin panel access
	 */
	ADMIN_PANEL_ACCESS: [ROLES.ADMIN, ROLES.MODERATOR] as const,

	// Future role groups:
	// USER_MANAGEMENT: [ROLES.ADMIN, ROLES.SUPER_ADMIN] as const,
	// CONTENT_MODERATION: [ROLES.ADMIN, ROLES.MODERATOR, ROLES.SUPPORT] as const,
} as const

/**
 * TypeScript types for type-safe role checking
 */
export type Role = typeof ROLES[keyof typeof ROLES]
export type AdminPanelRole = typeof ROLE_GROUPS.ADMIN_PANEL_ACCESS[number]

/**
 * Role hierarchy for privilege comparison
 * Lower number = higher privilege (can do more actions)
 *
 * This mirrors the backend ROLE_HIERARCHY configuration exactly.
 * Used to prevent privilege escalation during impersonation.
 *
 * @example
 * admin (1) > moderator (2) > user (3)
 * admin can impersonate moderator and user ✅
 * moderator can impersonate user only ✅
 * moderator CANNOT impersonate admin or moderator ❌
 */
export const ROLE_HIERARCHY = {
	admin: 1,
	moderator: 2,
	user: 3,
} as const

/**
 * Helper function to check if a user has one of the allowed roles
 *
 * @param userRole - The user's current role (from session)
 * @param allowedRoles - Array of roles that are allowed
 * @returns true if user has one of the allowed roles
 *
 * @example
 * hasRole(session.user.role, ROLE_GROUPS.ADMIN_PANEL_ACCESS)
 * hasRole(session.user.role, [ROLES.ADMIN])
 */
export function hasRole(
	userRole: string | null | undefined,
	allowedRoles: readonly string[]
): boolean {
	return !!userRole && allowedRoles.includes(userRole)
}

/**
 * Check if a user can perform administrative actions on a target user based on role hierarchy
 *
 * This is the core security function that prevents privilege escalation across ALL admin actions
 * including: edit, delete, ban, unban, set role, impersonate, etc.
 *
 * Rule: You can only perform admin actions on users with LOWER privileges (higher hierarchy number) than yourself.
 *
 * @param currentUserRole - The role of the user attempting the action (defaults to 'user' if null/undefined)
 * @param targetUserRole - The role of the user being acted upon (defaults to 'user' if null/undefined)
 * @returns true if action is allowed based on role hierarchy
 *
 * @example
 * // Admin (1) can act on Moderator (2) - allowed
 * canPerformActionOnUser('admin', 'moderator') // true
 *
 * @example
 * // Moderator (2) cannot act on Admin (1) - blocked (privilege escalation)
 * canPerformActionOnUser('moderator', 'admin') // false
 *
 * @example
 * // Moderator (2) cannot act on another Moderator (2) - blocked (same privilege level)
 * canPerformActionOnUser('moderator', 'moderator') // false
 *
 * @example
 * // Null roles default to 'user' - users cannot act on each other
 * canPerformActionOnUser(null, null) // false (both treated as user role)
 */
export function canPerformActionOnUser(
	currentUserRole: string | null | undefined,
	targetUserRole: string | null | undefined
): boolean {
	// Default to 'user' role if null/undefined (safest default - lowest privilege)
	const current = currentUserRole || ROLES.USER
	const target = targetUserRole || ROLES.USER

	const currentLevel = ROLE_HIERARCHY[current as keyof typeof ROLE_HIERARCHY]
	const targetLevel = ROLE_HIERARCHY[target as keyof typeof ROLE_HIERARCHY]

	// Reject if either role is not in hierarchy (unknown role)
	if (currentLevel === undefined || targetLevel === undefined) return false

	// Allow only if current user has higher privilege (lower number) than target
	// admin (1) < moderator (2) ✅ (admin can act on moderator)
	// moderator (2) < admin (1) ❌ (moderator cannot act on admin - privilege escalation)
	// moderator (2) < moderator (2) ❌ (moderator cannot act on same level)
	// null → user (3) < user (3) ❌ (users cannot act on each other)
	return currentLevel < targetLevel
}
