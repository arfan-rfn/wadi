# Admin Integration Documentation

This document provides comprehensive information about the admin functionality integrated into the Next.js frontend, which connects to the Better Auth admin plugin on your API server.

## Overview

The admin integration allows users with admin roles to:
- View and manage all system users
- Create, edit, and delete user accounts
- Assign and change user roles
- Ban and unban users with reasons and expiration dates
- View and manage user sessions
- Impersonate users to test their experience
- Revoke user sessions for security purposes

## Architecture

### Backend
- API server uses Better Auth with the admin plugin configured
- All admin operations are validated server-side
- Role-based access control is enforced at the API level

### Frontend
- Better Auth client with `adminClient` plugin
- React Query for data fetching and state management
- Protected admin routes using `AdminGuard` component
- Admin panel at `/admin` route

## Making a User an Admin

Since the admin plugin is configured on your API server, you need to update a user's role on the backend. There are several ways to do this:

### Method 1: Using Better Auth API
If you have access to your API server, you can use the Better Auth admin API:

```typescript
await auth.api.setRole({
  userId: "user_id_here",
  role: "admin"
})
```

### Method 2: Environment Configuration
You can configure admin users by ID in your Better Auth server configuration:

```typescript
admin({
  adminUserIds: ["user_id_1", "user_id_2"]
})
```

## Available Admin Operations

### User Management

#### List Users
```typescript
// Simple search - automatically detects email vs name
const { data, isLoading } = useListUsers({
  search: "john",          // Searches by name
  limit: 100,
  sortBy: "createdAt",
  sortDirection: "desc",
  role: "admin",
  banned: false
})

// Search by email (auto-detected when search contains @)
const { data } = useListUsers({
  search: "user@example.com"  // Automatically searches by email field
})

// Advanced search with explicit Better Auth parameters
const { data } = useListUsers({
  searchValue: "john",
  searchField: "name",                        // 'email' or 'name'
  searchOperator: "contains",                 // 'contains', 'starts_with', 'ends_with'
  filterField: "role",
  filterValue: "admin",
  filterOperator: "eq"                        // 'eq', 'ne', 'lt', 'lte', 'gt', 'gte'
})
```

**Search Features:**
- **Smart detection**: If search contains `@`, searches by email, otherwise by name
- **Contains matching**: Searches use `contains` operator by default
- **Advanced control**: Use `searchField` and `searchOperator` for fine-grained control
- **Pagination**: Uses `offset` and `limit` for efficient data loading (20 users per page)
- All search parameters follow Better Auth API specification

**Case Sensitivity Note:**
The frontend converts search queries to lowercase, but true case-insensitive search requires backend support. Consult your backend database documentation for implementing case-insensitive search in Better Auth queries.

#### Create User
```typescript
const { mutate: createUser } = useCreateUser()

createUser({
  name: "John Doe",
  email: "john@example.com",
  password: "securePassword123",
  role: "user"
})
```

#### Update User
```typescript
const { mutate: updateUser } = useUpdateUser()

updateUser({
  userId: "user_id",
  data: {
    name: "Jane Doe",
    email: "jane@example.com"
  }
})
```

#### Set User Role
```typescript
const { mutate: setRole } = useSetUserRole()

setRole({
  userId: "user_id",
  role: "admin"
})
```

#### Delete User
```typescript
const { mutate: removeUser } = useRemoveUser()

removeUser({ userId: "user_id" })
```

### Ban Management

#### Ban User
```typescript
const { mutate: banUser } = useBanUser()

banUser({
  userId: "user_id",
  reason: "Violation of terms",
  expiresAt: new Date("2025-12-31")
})
```

#### Unban User
```typescript
const { mutate: unbanUser } = useUnbanUser()

unbanUser({ userId: "user_id" })
```

### Session Management

#### List User Sessions
```typescript
const { data } = useListUserSessions({
  userId: "user_id"
})
```

#### Revoke Single Session
```typescript
const { mutate: revokeSession } = useRevokeSession()

revokeSession({ sessionId: "session_id" })
```

#### Revoke All User Sessions
```typescript
const { mutate: revokeSessions } = useRevokeUserSessions()

revokeSessions({ userId: "user_id" })
```

### Impersonation

#### Impersonate User
```typescript
const { mutate: impersonate } = useImpersonateUser()

impersonate({ userId: "user_id" })
// Page will reload and you'll be logged in as that user
```

#### Stop Impersonating
```typescript
const { mutate: stopImpersonating } = useStopImpersonating()

stopImpersonating()
// Returns you to your admin session
```

## Using Admin Components

### Protecting Admin Routes

Wrap your admin pages with the `AdminGuard` component:

```tsx
import { AdminGuard } from "@/components/admin/admin-guard"

export default function AdminPage() {
  return (
    <AdminGuard>
      <div>Admin content here</div>
    </AdminGuard>
  )
}
```

### Checking Admin Access

The recommended way to check admin panel access is using semantic, intent-based functions:

```tsx
import { useCanAccessAdmin, useIsAdmin, useHasRole } from "@/hooks/use-admin"
import { ROLES } from "@/lib/constants/roles"

function MyComponent() {
  // ✅ Recommended: Check if user can access admin panel
  const { canAccess, isLoading } = useCanAccessAdmin()

  if (canAccess) {
    return <AdminFeature />
  }

  return <RegularFeature />
}

// Check strictly for admin role only (not moderator)
function StrictAdminComponent() {
  const { isAdmin } = useIsAdmin()

  if (isAdmin) {
    return <SuperAdminFeature />
  }

  return <RegularFeature />
}

// Check for custom role combinations
function CustomRoleComponent() {
  const { hasRole } = useHasRole([ROLES.ADMIN, ROLES.MODERATOR, ROLES.SUPPORT])

  if (hasRole) {
    return <CustomFeature />
  }

  return <RegularFeature />
}
```

**Why semantic naming matters:**
- `useCanAccessAdmin()` describes **intent** (what user can do) not **implementation** (what roles they have)
- Future-proof: Add new roles by updating `ROLE_GROUPS.ADMIN_PANEL_ACCESS` array only
- More intuitive: `if (canAccess)` reads better than checking specific role combinations
- Maintainable: Single source of truth in `lib/constants/roles.ts`

## Role Management

The system uses a centralized role configuration for maintainability and future-proofing.

### Centralized Role Definitions

All roles are defined in `lib/constants/roles.ts`:

```typescript
export const ROLES = {
  USER: 'user',
  MODERATOR: 'moderator',
  ADMIN: 'admin',
  // Add future roles here:
  // SUPER_ADMIN: 'super-admin',
  // SUPPORT: 'support',
}

export const ROLE_GROUPS = {
  ADMIN_PANEL_ACCESS: [ROLES.ADMIN, ROLES.MODERATOR],
  // Add future role groups:
  // USER_MANAGEMENT: [ROLES.ADMIN, ROLES.SUPER_ADMIN],
  // CONTENT_MODERATION: [ROLES.ADMIN, ROLES.MODERATOR, ROLES.SUPPORT],
}
```

### Adding a New Role

To add a new role with admin panel access:

1. **Add role to constants:**
```typescript
// lib/constants/roles.ts
export const ROLES = {
  USER: 'user',
  MODERATOR: 'moderator',
  ADMIN: 'admin',
  SUPPORT: 'support',  // ← New role
}
```

2. **Add to appropriate role group:**
```typescript
export const ROLE_GROUPS = {
  ADMIN_PANEL_ACCESS: [ROLES.ADMIN, ROLES.MODERATOR, ROLES.SUPPORT],  // ← Add here
}
```

3. **Configure permissions on backend:**
```typescript
// Backend Better Auth config
const support = ac.newRole({
  user: ['list', 'get'],     // Can view users
  session: ['list'],          // Can view sessions
  ui: ['admin-dashboard'],    // Can access admin panel
})
```

That's it! No need to update components - they all use `useCanAccessAdmin()` which reads from `ROLE_GROUPS.ADMIN_PANEL_ACCESS`.

### Role vs Permission: When to Use Which

| Use Case | Solution | Example |
|----------|----------|---------|
| Check if user can access admin panel | **Role** with `useCanAccessAdmin()` | Navigation menu, route guards |
| Check if user can perform specific action | **Permission** with `usePermission()` | Create user button, delete button |
| Check for specific role combination | **Role** with `useHasRole()` | Features for admin+moderator only |
| UI that differs by permission level | **Permission** with multiple checks | Advanced vs basic admin features |

**Best Practice:** Use roles for coarse-grained access (sections), permissions for fine-grained actions (buttons).

## Permission System

The admin integration uses a granular permission system powered by Better Auth's access control. This allows fine-grained control over what each admin/moderator can do.

### How It Works

1. **Roles for broad access**: `admin` and `moderator` roles determine if users can access the admin panel
2. **Permissions for specific actions**: Each action (create user, ban user, etc.) requires a specific permission
3. **Lazy loading + caching**: Permissions are checked when needed and cached for 5 minutes
4. **React Query powered**: Automatic caching, deduplication, and background updates

### Checking Permissions

Use the `usePermission` hook to check if the current user has a specific permission:

```tsx
import { usePermission } from "@/hooks/use-permission"
import { PERMISSIONS } from "@/lib/constants/permissions"

function UserActionsMenu({ user }) {
  // Check if user can set roles
  const { data: canSetRole = false, isLoading } = usePermission(...PERMISSIONS.USER.SET_ROLE)
  const { data: canBan = false } = usePermission(...PERMISSIONS.USER.BAN)

  return (
    <DropdownMenu>
      {canSetRole && <MenuItem>Change Role</MenuItem>}
      {canBan && <MenuItem>Ban User</MenuItem>}
    </DropdownMenu>
  )
}
```

### Available Permissions

All permissions are defined in `lib/constants/permissions.ts`:

**User Permissions (synced with backend):**
- `USER.CREATE` - Create new users
- `USER.LIST` - View user list
- `USER.UPDATE` - Edit user information
- `USER.DELETE` - Delete users
- `USER.SET_ROLE` - Change user roles
- `USER.SET_PASSWORD` - Reset passwords
- `USER.BAN` - Ban users
- `USER.UNBAN` - Unban users
- `USER.IMPERSONATE` - Impersonate users

**Session Permissions (synced with backend):**
- `SESSION.LIST` - View user sessions
- `SESSION.REVOKE` - Revoke specific sessions
- `SESSION.REVOKE_ALL` - Revoke all user sessions

**UI Permissions (Custom):**
- `UI.ADMIN_DASHBOARD` - Access admin dashboard
- `UI.USER_MANAGEMENT` - Access user management
- `UI.SETTINGS` - Access admin settings

### Permission Preloading

Common permissions are preloaded in the admin layout to avoid loading states:

```tsx
// app/(app)/admin/layout.tsx
import { usePreloadPermissions } from "@/hooks/use-permission"
import { COMMON_ADMIN_PERMISSIONS } from "@/lib/constants/permissions"

export default function AdminLayout({ children }) {
  // Preload permissions - they'll be cached before user clicks anything
  usePreloadPermissions(COMMON_ADMIN_PERMISSIONS)

  return <>{children}</>
}
```

### Multiple Permission Check

To check if user has ALL permissions at once:

```tsx
import { usePermissions } from "@/hooks/use-permission"

function MyComponent() {
  // Returns true ONLY if user has all these permissions
  const { data: hasAll = false } = usePermissions({
    user: ['create', 'delete'],
    session: ['list']
  })

  if (hasAll) {
    return <AdvancedFeature />
  }
}
```

### Example: Moderator vs Admin

Configure permissions on your backend to differentiate roles:

```typescript
// Backend configuration
const moderator = ac.newRole({
  user: ["list", "get", "ban"],     // Can view and ban users
  session: ["list"],                 // Can view sessions
  ui: ["admin-dashboard"]            // Can access admin panel
})

const admin = ac.newRole({
  user: ["*"],                       // All user permissions
  session: ["*"],                    // All session permissions
  ui: ["*"]                          // All UI permissions
})
```

With this setup:
- **Moderators** can see the admin panel and ban users, but **cannot** change roles or delete users
- **Admins** have full permissions

The frontend automatically adapts the UI based on each user's permissions.

### Adding New Permissions

1. **Define permission in constants:**
```typescript
// lib/constants/permissions.ts
export const CUSTOM_PERMISSIONS = {
  EXPORT_DATA: ['reports', 'export'] as const,
}
```

2. **Use in component:**
```typescript
const { data: canExport } = usePermission('reports', 'export')
```

3. **Configure on backend:**
```typescript
// Backend Better Auth config
const admin = ac.newRole({
  reports: ["export"]
})
```

### Permission Caching

- Permissions are cached for **5 minutes** after first check
- Cache is automatically invalidated when:
  - User logs out
  - User role changes
  - Manual refresh via React Query
- No API calls are made during cache lifetime

### Displaying User Roles

```tsx
import { RoleBadge } from "@/components/admin/role-badge"

function UserCard({ user }) {
  return (
    <div>
      <p>{user.name}</p>
      <RoleBadge role={user.role} />
    </div>
  )
}
```

### User List Component

```tsx
import { UserList } from "@/components/admin/user-management/user-list"

export default function UsersPage() {
  return (
    <div>
      <h1>Users</h1>
      <UserList />
    </div>
  )
}
```

## Role Hierarchy Security

To prevent privilege escalation attacks, the system enforces a role hierarchy across **ALL admin actions**. This ensures that users can only perform administrative actions on users with lower privileges than themselves.

### The Problem

Without role hierarchy enforcement, a moderator with admin permissions could:
1. **Edit** an admin's profile
2. **Change role** of an admin to a regular user
3. **Ban** an admin account
4. **Delete** an admin user
5. **Impersonate** an admin and gain full admin privileges

This is a **critical security vulnerability** that allows privilege escalation and must be prevented.

### The Solution

The system implements a numeric role hierarchy where lower numbers represent higher privileges:

```typescript
// lib/constants/roles.ts
export const ROLE_HIERARCHY = {
  admin: 1,        // Highest privilege
  moderator: 2,    // Mid-level privilege
  user: 3,         // Lowest privilege
} as const
```

### Privilege Rules

The `canPerformActionOnUser()` helper function enforces these rules across **ALL admin actions**:

| Admin Role | Can Act On | Cannot Act On |
|------------|-----------|--------------|
| **Admin (1)** | Moderator (2), User (3) | Other Admins (1) |
| **Moderator (2)** | User (3) only | Admin (1), Other Moderators (2) |
| **User (3)** | No one | Everyone |

**Protected Actions:**
- Edit user profile
- Change user role
- Ban/Unban user
- Delete user
- Impersonate user

### Implementation

The role hierarchy check is implemented at the UI level in the user actions menu for ALL admin actions:

```tsx
// components/admin/user-management/user-actions-menu.tsx
import { canPerformActionOnUser } from "@/lib/constants/roles"
import { useSession } from "@/lib/auth"

// Get current user's role from session
const { data: session } = useSession()
const currentUserRole = session?.user?.role

// Permission checks
const { data: canUpdatePerm = false } = usePermission(...PERMISSIONS.USER.UPDATE)
const { data: canBanPerm = false } = usePermission(...PERMISSIONS.USER.BAN)
const { data: canImpersonatePerm = false } = usePermission(...PERMISSIONS.USER.IMPERSONATE)

// Role hierarchy check - applies to ALL actions
const canActOnUser = canPerformActionOnUser(currentUserRole, user.role)

// Combine permission AND hierarchy for each action
const canUpdate = canUpdatePerm && canActOnUser
const canBan = canBanPerm && canActOnUser
const canImpersonate = canImpersonatePerm && canActOnUser

// Actions only show if BOTH permission AND hierarchy checks pass
{canUpdate && <MenuItem>Edit User</MenuItem>}
{canBan && <MenuItem>Ban User</MenuItem>}
{canImpersonate && <MenuItem>Impersonate</MenuItem>}
```

### Examples

#### ✅ Allowed Scenarios

```typescript
// Admin can act on moderator (edit, ban, delete, impersonate, etc.)
canPerformActionOnUser('admin', 'moderator')  // true
// Admin has privilege level 1, moderator has 2 → 1 < 2 ✅

// Admin can act on regular user
canPerformActionOnUser('admin', 'user')  // true
// Admin has privilege level 1, user has 3 → 1 < 3 ✅

// Moderator can act on regular user
canPerformActionOnUser('moderator', 'user')  // true
// Moderator has privilege level 2, user has 3 → 2 < 3 ✅
```

**Real-world examples:**
- Admin can **ban** a moderator ✅
- Admin can **delete** a moderator ✅
- Admin can **edit** a moderator's profile ✅
- Moderator can **impersonate** a regular user ✅

#### ❌ Blocked Scenarios

```typescript
// Moderator trying to act on admin (privilege escalation!)
canPerformActionOnUser('moderator', 'admin')  // false
// Moderator has privilege level 2, admin has 1 → 2 < 1 ❌

// Moderator trying to act on another moderator
canPerformActionOnUser('moderator', 'moderator')  // false
// Same privilege level → 2 < 2 ❌

// User trying to act on anyone
canPerformActionOnUser('user', 'user')  // false
// Same privilege level → 3 < 3 ❌
```

**Real-world examples:**
- Moderator **cannot ban** an admin ❌ (privilege escalation blocked)
- Moderator **cannot delete** another moderator ❌ (lateral movement blocked)
- Moderator **cannot change role** of an admin ❌ (privilege escalation blocked)
- Moderator **cannot edit** an admin's profile ❌ (information tampering blocked)

### Adding New Roles to Hierarchy

When adding a new role, you must add it to the hierarchy to enable proper privilege checks for ALL admin actions:

```typescript
// lib/constants/roles.ts
export const ROLE_HIERARCHY = {
  admin: 1,
  moderator: 2,
  support: 2,      // ← Same level as moderator
  user: 3,
} as const
```

**Rules for assigning hierarchy levels:**
- **Lower number = higher privilege** (can do more actions)
- Roles at the **same level cannot impersonate each other**
- Each role can **only impersonate roles with higher numbers** (lower privileges)

### Backend + Frontend Defense

The role hierarchy is enforced on **both** the backend and frontend:

**Backend (Primary Security):**
```typescript
// Your API server's Better Auth config
export const ROLE_HIERARCHY = {
  admin: 1,
  moderator: 2,
  user: 3,
}
// Backend validates and throws error if hierarchy violation detected
```

**Frontend (UX Enhancement):**
```typescript
// lib/constants/roles.ts - mirrors backend exactly
export const ROLE_HIERARCHY = {
  admin: 1,
  moderator: 2,
  user: 3,
}
// Frontend hides impersonate button to prevent confusion and wasted API calls
```

This **defense-in-depth** approach ensures:
- Backend enforces security (prevents attacks)
- Frontend provides better UX (prevents confusion)
- Moderators don't see impersonate button for admins/moderators
- Clicking the button (if exposed) still fails on backend

### The canPerformActionOnUser() Function

This is the core security function that protects ALL admin actions from privilege escalation:

```typescript
export function canPerformActionOnUser(
  currentUserRole: string | null | undefined,
  targetUserRole: string | null | undefined
): boolean {
  // 1. Default to 'user' role if null/undefined (safest default - lowest privilege)
  const current = currentUserRole || ROLES.USER
  const target = targetUserRole || ROLES.USER

  // 2. Get hierarchy levels
  const currentLevel = ROLE_HIERARCHY[current as keyof typeof ROLE_HIERARCHY]
  const targetLevel = ROLE_HIERARCHY[target as keyof typeof ROLE_HIERARCHY]

  // 3. Reject if either role is not in hierarchy (unknown role)
  if (currentLevel === undefined || targetLevel === undefined) return false

  // 4. Allow only if current user has higher privilege (lower number) than target
  // admin (1) < moderator (2) ✅ (admin can act on moderator)
  // moderator (2) < admin (1) ❌ (moderator cannot act on admin)
  // moderator (2) < moderator (2) ❌ (moderator cannot act on same level)
  // null → user (3) < user (3) ❌ (users cannot act on each other)
  return currentLevel < targetLevel
}
```

**Safe Default Behavior:**
- If a user has no role set (`null` or `undefined`), they are treated as a regular **'user'** (lowest privilege)
- This ensures security even for users without explicit role assignments
- Prevents privilege escalation if role data is missing or corrupted

### Impersonation Banner

When an admin successfully impersonates a user, a warning banner appears at the top of all pages:

```tsx
import { ImpersonationBanner } from "@/components/admin/impersonation-banner"

// Shows automatically when impersonating
<ImpersonationBanner />
```

The banner:
- Uses destructive theme colors for high visibility
- Shows the impersonated user's name/email
- Provides "Stop Impersonating" button to exit
- Fixed position at top of page with proper spacing

To detect impersonation status:

```tsx
import { useIsImpersonating } from "@/hooks/use-admin"

const { isImpersonating, impersonatedBy } = useIsImpersonating()

if (isImpersonating) {
  console.log('Being impersonated by admin:', impersonatedBy)
}
```

**Important:** Better Auth stores impersonation data at `session.session.impersonatedBy`, not `session.impersonatedBy`.

## Security Considerations

### Important Security Notes

1. **Client-side checks are for UI only** - Never rely on `useCanAccessAdmin()`, `useIsAdmin()`, or `canPerformActionOnUser()` for security. All admin operations are validated on the server.

2. **Server-side validation** - Your API server already validates all admin operations through Better Auth's admin plugin, including role hierarchy enforcement.

3. **Sensitive operations require confirmation** - Dialogs are shown before destructive actions like banning or deleting users.

4. **Impersonation tracking** - When impersonating, the session stores the original admin's ID in `impersonatedBy` field for audit purposes.

5. **Session security** - Revoke sessions immediately if you suspect unauthorized access.

6. **Role hierarchy must match backend** - The frontend ROLE_HIERARCHY constant must exactly mirror the backend configuration to maintain security consistency.

### Best Practices

- **Audit logging**: Consider adding logging for admin actions on the backend
- **Two-factor authentication**: Enable 2FA for admin accounts
- **Regular access reviews**: Periodically review who has admin access
- **Principle of least privilege**: Only grant admin access when necessary
- **Session timeouts**: Configure appropriate session expiration times

## Troubleshooting

### "Access Denied" when accessing /admin

**Cause**: User doesn't have admin role

**Solution**:
1. Check the user's role in the database
2. Update the role to "admin" using one of the methods above
3. Sign out and sign back in to refresh the session

### Admin operations failing with 403 errors

**Cause**: Backend admin plugin not properly configured

**Solution**:
1. Verify Better Auth admin plugin is installed on API server
2. Check that admin roles are configured correctly
3. Ensure session cookies are being sent to the API

### Impersonation not working

**Cause**: Session not refreshing properly

**Solution**:
1. The hooks automatically reload the page after impersonation
2. If it doesn't work, manually sign out and sign back in
3. Check browser console for errors

### User list not loading

**Cause**: API connection issues

**Solution**:
1. Check network tab for failed requests
2. Verify NEXT_PUBLIC_API_URL is configured correctly
3. Ensure CORS is properly configured on API server
4. Check that credentials are being included in requests

## Available Roles

By default, the following roles are supported:
- `user` - Regular user (default)
- `admin` - Full administrative access
- `moderator` - Limited administrative access (if configured)

You can customize roles in your Better Auth admin plugin configuration on the API server.

## Admin Panel Routes

- `/admin` - Admin dashboard with statistics
- `/admin/users` - User management page
- `/admin/sessions` - Session management page

## Data Types

### User Object
```typescript
interface User {
  id: string
  email: string
  name: string
  image?: string | null
  emailVerified: boolean
  createdAt: Date
  updatedAt: Date
  role: string
  banned: boolean
  banReason: string | null
  banExpires: Date | null
}
```

### Session Object
```typescript
interface Session {
  id: string
  userId: string
  expiresAt: Date
  token: string
  ipAddress?: string
  userAgent?: string
  impersonatedBy: string | null
}
```

## Future Enhancements

Potential features to add:
- Bulk user operations (ban multiple users at once)
- Export user data as CSV/JSON
- User activity logs and analytics
- Email notifications for admin actions
- Custom role permissions
- Admin permission levels (super admin vs. moderator)

## Related Files

### Hooks
- `hooks/use-admin.ts` - All admin operations (consolidated)
- `hooks/use-permission.ts` - Permission checking with caching

### Components
- `components/admin/admin-guard.tsx` - Route protection
- `components/admin/role-badge.tsx` - Role display
- `components/admin/impersonation-banner.tsx` - Impersonation indicator
- `components/admin/user-management/*` - User management UI
- `components/admin/session-management/*` - Session management UI

### Pages
- `app/(app)/admin/layout.tsx` - Admin layout with navigation
- `app/(app)/admin/page.tsx` - Admin dashboard
- `app/(app)/admin/users/page.tsx` - User management
- `app/(app)/admin/sessions/page.tsx` - Session management

### Types and Constants
- `lib/types/auth.ts` - TypeScript type definitions
- `lib/constants/roles.ts` - Centralized role definitions and groups
- `lib/constants/permissions.ts` - Permission constants synced with backend
- `lib/types/better-auth.d.ts` - Better Auth type extensions

## Support

For issues or questions:
1. Check the Better Auth documentation: https://www.better-auth.com/docs/plugins/admin
2. Review this documentation
3. Check browser console for error messages
4. Verify API server logs for backend issues

## Changelog

### Initial Implementation
- Added Better Auth admin client plugin
- Created all admin hooks and components
- Built admin pages for user and session management
- Added impersonation functionality
- Protected admin routes with AdminGuard
- Added admin navigation to account menu

### Permission System Implementation
- Added granular permission checking with `usePermission` hook
- Implemented React Query-based caching (5min TTL)
- Created permission constants for type safety
- Added permission preloading in admin layout
- Updated components with permission-based rendering
- Consolidated all admin hooks into single file

### Role Management Refactor
- Created centralized role configuration in `lib/constants/roles.ts`
- Introduced semantic function naming with `useCanAccessAdmin()` and `useHasRole()`
- Synced frontend permissions with backend statement exactly
- Updated all components to use semantic hooks for role checking
- Made system future-proof: add new roles by updating single array in `ROLE_GROUPS`
- Added comprehensive role management documentation with best practices

### Role Hierarchy Security (Privilege Escalation Prevention)
- Added ROLE_HIERARCHY constant to `lib/constants/roles.ts` mirroring backend
- Implemented `canPerformActionOnUser()` helper function for privilege checking across ALL admin actions
- Generalized security to protect: edit, delete, ban, unban, set role, and impersonate
- Updated user actions menu with role hierarchy validation for every action
- Prevents moderators from acting on admins or other moderators (privilege escalation + lateral movement)
- Defense-in-depth: backend enforcement + frontend UX improvement
- Fixed impersonation banner detection (`session.session.impersonatedBy`)
- Added comprehensive role hierarchy security documentation with real-world examples

### User Search & Pagination Improvements
- **Fixed user search**: Properly works with Better Auth API now
- **Added pagination**: 20 users per page with Previous/Next controls
- **Smart search detection**: Automatically searches by email if input contains `@`, otherwise by name
- **Case-insensitive search**: Frontend converts to lowercase (requires backend support for full functionality)
- Updated `ListUsersQuery` interface to include all Better Auth search parameters
- Implemented query transformation in `useListUsers` hook to convert simple search to Better Auth format
- Added support for advanced search with explicit `searchField` and `searchOperator` parameters
- Pagination automatically resets to page 1 when search query changes
- Results counter shows "X to Y of Z users"
- Updated documentation with search examples, pagination info, and backend recommendations for case-insensitive search

### Admin UI Redesign (2025-10-10)
- **Single Heading Concept**: "Admin Panel" is now a small label (text-xs, uppercase) - each page has ONE prominent h1
- **No Competing Headings**: Clear visual hierarchy with page-specific titles as the only prominent headings
- **Modern Navigation**: Replaced plain text links with styled tab navigation with icons and active states
- **Enhanced Dashboard**: Color-coded stat cards with hover effects, animations, and loading states
- **Improved Layout**: Gradient backgrounds, better spacing, and visual hierarchy throughout
- **Clean & Minimalist**: Removed redundant descriptions and icons for a cleaner, more focused design
- **Data Table Implementation**: Implemented shadcn data table with TanStack Table for powerful sorting/filtering
- **Sortable Columns**: Click column headers to sort by User, Role, or Created date (ascending/descending)
- **Client-Side Filtering**: Instant search by name or email with real-time results
- **Column Visibility**: Toggle columns on/off via View dropdown menu
- **User Avatars**: Profile pictures or initials in colored circles for each user
- **Verified Checkmark**: Email verification shown as green checkmark icon inline (no confusing badge)
- **Badges with Icons**: Role badges (Shield/ShieldAlert/User), status badges (CircleCheck/Ban)
- **Theme Colors**: Admin uses primary color, moderator uses orange, user uses muted - consistent with theme
- **Improved Actions Button**: Changed from ghost to outline variant with visible border for better affordability
- **Pagination**: Built-in pagination with Previous/Next controls and page counter
- **Accessibility**: Proper focus states, keyboard navigation, and ARIA attributes
- **Visual Polish**: Smooth transitions, hover effects on rows, and professional table styling
- See `plan/admin-ui-redesign.md` for detailed implementation notes
