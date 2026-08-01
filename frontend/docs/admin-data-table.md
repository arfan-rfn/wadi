# Admin Data Table Documentation

**Component**: User Management Data Table
**Location**: `/admin/users`
**Technology**: TanStack Table v8 (React Table) + shadcn/ui

## Overview

The admin user management interface uses a powerful data table implementation that provides sorting, filtering, column visibility controls, and pagination. This follows the shadcn data table pattern for maximum flexibility and performance.

## Features

### 1. Sortable Columns

Click on any column header with the sort icon (↕) to toggle sorting:

- **User** - Sort alphabetically by name
- **Role** - Sort by role (admin → moderator → user)
- **Created** - Sort by creation date (newest/oldest first)

**How it works:**
- First click: Sort ascending (A→Z, oldest→newest)
- Second click: Sort descending (Z→A, newest→oldest)
- Third click: Remove sorting

### 2. Search & Filtering

**Global Search:**
- Located at the top-left of the table
- Searches across user names and emails via Better Auth API
- Debounced search (300ms delay) to prevent excessive API calls
- Case-insensitive matching
- Automatically resets to first page when search changes

**Example searches:**
- `john` - Finds "John Doe", "Johnny Smith"
- `@gmail` - Finds all Gmail users
- `admin` - Finds users with "admin" in name/email

**Technical Details:**
- Server-side search implementation
- Email detection: Searches containing `@` are treated as email searches
- Otherwise searches in name field

### 3. Column Visibility

**View Button** (top-right):
- Toggle columns on/off as needed
- Hide columns you don't need
- Settings persist during your session
- Useful for focusing on specific data

**Available columns:**
- User (with avatar, name, email, ID)
- Role
- Status (Active/Banned)
- Profile Complete
- Created date
- Actions menu

### 4. Pagination

- **20 users per page** (configurable)
- Previous/Next navigation buttons
- Page counter showing current/total pages
- Total user count displayed
- Keyboard accessible

### 5. Visual Indicators

**User Column:**
- Avatar with profile picture or initials
- Name in bold
- Email with mail icon
- Green checkmark (✓) for verified emails
- User ID below email (monospace font)
- Copy button next to ID for quick copying

**Role Badges:**
- 🛡️ Admin (primary color)
- 🛡️⚠️ Moderator (orange)
- 👤 User (muted)

**Status Badges:**
- ✅ Active (green)
- 🚫 Banned (red)

**Profile Complete Column:**
- "Complete" badge with checkmark for users with completed profiles
- "Incomplete" badge for users with incomplete profiles

### 6. User Details Dialog

**Click any row to view complete user details:**
- Full user information in a modal dialog
- Avatar and basic info (name, email, role, status)
- All account fields with copy functionality
- Email verification status
- Profile completion status
- Account creation and update timestamps
- Profile completion and first login dates (when available)
- Profile image link (when available)

**Quick Copy:**
- Click copy button next to User ID or Email to copy to clipboard
- Visual feedback (checkmark) when copied

### 7. Actions Menu

Each row has a three-dot menu (⋯) providing:
- Edit user details
- Change role
- Ban/Unban user
- Impersonate user
- Delete user

Actions are permission-based and respect role hierarchy.

**Note:** Clicking the actions menu button does not trigger the row click.

## Technical Implementation

### Architecture

```
components/admin/user-management/
├── user-list.tsx              # Main component (loads data)
├── data-table.tsx             # Reusable table component with dialog
├── columns.tsx                # Column definitions
├── user-details-dialog.tsx    # Full user details modal
├── user-actions-menu.tsx      # Actions dropdown menu
├── edit-user-dialog.tsx       # Edit user dialog
├── set-role-dialog.tsx        # Change role dialog
└── ban-user-dialog.tsx        # Ban user dialog
```

### Column Definitions

Located in `columns.tsx`, each column defines:
- `accessorKey`: Data field to display
- `header`: Column header (with sorting button)
- `cell`: How to render the cell content
- `filterFn`: Custom filtering logic (optional)

### Data Flow

1. **user-list.tsx** fetches users via `useListUsers()` hook
2. Passes data and column definitions to `DataTable`
3. **data-table.tsx** manages table state (sorting, filtering, pagination, dialog)
4. **columns.tsx** defines how each column renders
5. **user-details-dialog.tsx** displays complete user information when row is clicked

### User Interaction Flow

**Viewing User Details:**
1. User clicks on any table row
2. `handleRowClick` is triggered in `data-table.tsx`
3. Selected user is stored in state
4. Dialog opens with user information
5. User can copy ID/email with one click

**Actions Menu:**
1. Three-dot menu button uses `stopPropagation` to prevent row click
2. Actions respect permission system and role hierarchy
3. Each action opens its specific dialog (edit, ban, role change)

### State Management

**Data Table Component:**
- `sorting` - Current sort column and direction (client-side)
- `columnVisibility` - Which columns are visible (client-side)
- `selectedUser` - Currently selected user for details dialog
- `dialogOpen` - Whether the user details dialog is open

**User List Component:**
- `search` - Current search input value
- `debouncedSearch` - Debounced search value (300ms delay)
- `page` - Current page index (0-based)

**Note:** Pagination and search are server-side for scalability.

## Performance

### Server-Side Pagination

**Current Implementation:**
- Server-side pagination via Better Auth API
- Loads only 20 users per page
- Search handled by the server
- Debounced search (300ms) prevents excessive API calls
- Manual pagination mode in TanStack Table

**Implementation:**
```typescript
export function UserList() {
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(0)
  const [debouncedSearch, setDebouncedSearch] = useState("")

  // Debounce search to avoid too many API calls
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
      setPage(0) // Reset to first page when search changes
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const { data, isLoading, error } = useListUsers({
    search: debouncedSearch.toLowerCase(),
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    sortBy: "createdAt",
    sortDirection: "desc"
  })
}
```

**Pros:**
- Scalable for any number of users
- Lower memory footprint
- Faster initial page load
- Better for large datasets

**Cons:**
- Network latency for pagination and search
- Requires server support for filtering/sorting

## Responsive Design

- **Desktop**: Full table with all columns
- **Tablet**: Horizontal scrolling if needed
- **Mobile**: Horizontal scrolling with sticky first column

## Accessibility

- ✅ Keyboard navigation (Tab, Arrow keys)
- ✅ Screen reader support (ARIA labels)
- ✅ Focus indicators on all interactive elements
- ✅ Semantic HTML table structure

## Customization

### Change Page Size

Edit `data-table.tsx`:

```typescript
initialState: {
  pagination: {
    pageSize: 50, // Change from 20 to 50
  },
},
```

### Add New Column

1. Add column definition to `columns.tsx`:

```typescript
{
  accessorKey: "updatedAt",
  header: "Last Updated",
  cell: ({ row }) => {
    return new Date(row.getValue("updatedAt")).toLocaleDateString()
  },
}
```

2. Column automatically appears in table

### Custom Filtering

Add to column definition:

```typescript
{
  accessorKey: "role",
  // ...
  filterFn: (row, id, value) => {
    // Custom filter logic
    return value.includes(row.getValue(id))
  },
}
```

## Future Enhancements

Potential improvements:
- **Bulk actions**: Select multiple users for batch operations
- **Export to CSV**: Download user data
- **Column resizing**: Drag to resize columns
- **Advanced filters**: Filter by date range, multiple roles, verification status
- **Saved views**: Save custom column/filter configurations
- **Server-side sorting**: Currently client-side, could be moved to server
- **Column-specific search**: Individual search per column

## Related Documentation

- [Admin Integration](./admin-integration.md) - Overall admin system
- [Better Auth Admin Plugin](https://www.better-auth.com/docs/plugins/admin)
- [TanStack Table Docs](https://tanstack.com/table/latest)
- [shadcn Data Table](https://ui.shadcn.com/docs/components/data-table)
