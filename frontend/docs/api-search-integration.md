# API Search Integration

**Date:** 2025-10-13
**Status:** Implemented
**Category:** Feature

---

## Overview

The API search integration extends the existing search component to fetch real-time user search results from the backend API (`/api/v1/search`) while maintaining static navigation suggestions. This implementation focuses on the **users category only**, with pagination support within the command dialog interface.

The architecture is designed for extensibility, making it trivial to add new categories (feedback, files, audit) in the future with minimal code changes.

---

## Implementation Summary

### Components Modified

1. **`lib/types/search.ts`** (New)
   - Generic types for search functionality
   - Category-specific result types (users, feedback, files, audit)
   - Type-safe search response structure

2. **`lib/types/index.ts`** (New)
   - Central export point for all type definitions

3. **`hooks/use-search.ts`** (New)
   - `useSearch()` hook for main search functionality with debouncing (400ms)
   - `useLoadMore()` hook for pagination
   - Post-processing pipeline to add navigation URLs to results
   - `CATEGORY_URL_MAPPERS` for managing navigation paths

4. **`components/search.tsx`** (Modified)
   - Integrated API search with existing command palette
   - Added user search results rendering with avatars and badges
   - Implemented progressive loading ("Load more") for pagination
   - Maintained static suggestions for empty query state
   - Added loading and error states

5. **`components/icons.tsx`** (Modified)
   - Added `ChevronDown`, `Spinner`, and `AlertCircle` icons

### Dependencies Added

- `use-debounce` (v10.0.6) - Input debouncing for search queries

---

## Architecture Highlights

### 1. Extensible Type System

The type system uses generics to support multiple categories:

```typescript
// Generic paginated results work with any item type
interface CategoryResults<T> {
  items: T[]
  total: number
  page: number
  limit: number
  hasMore: boolean
}

// Category-specific types with optional URL field (added by post-processing)
interface UserSearchResult {
  id: string
  name: string
  email: string
  image: string | null
  role: string | null
  createdAt: string
  url?: string  // Added by post-processing pipeline
}
```

### 2. Single Search Hook with Post-Processing

The `useSearch()` hook fetches all categories from the API and applies a post-processing pipeline to add navigation URLs:

```typescript
// Navigation URL mapper
const CATEGORY_URL_MAPPERS = {
  users: (item: UserSearchResult) => `/admin/users/${item.id}`,
  feedback: (item: FeedbackSearchResult) => `/admin/feedback/${item.id}`,
  files: (item: FileSearchResult) => `/files/${item.id}`,
  audit: (item: AuditSearchResult) => `/admin/audit/${item.id}`,
}
```

**Benefits:**
- Single API call is efficient
- URL logic is cleanly separated
- Type-safe navigation
- Easy to extend with new categories

### 3. Progressive Loading

Instead of traditional pagination controls, the implementation uses a "Load more" button within the command dialog:

- Initial load: 5 results
- Load more: 10 results per increment
- State management tracks loaded items, current page, and hasMore flag
- Loading spinner during fetch

---

## User Flow

1. **Empty Query:** Shows static navigation suggestions and theme switcher
2. **Query Length < 2:** Shows "Type at least 2 characters to search..."
3. **Query Length ≥ 2:**
   - Debounced API call (400ms)
   - Shows loading spinner
   - Displays user results with avatars, names, emails, and roles
   - Shows total count in group heading
   - "Load more" button if additional results exist
4. **Click User:** Navigates to `/admin/users/:id`
5. **Click Load More:** Fetches next page and appends to list

---

## API Integration

### Endpoint
```
GET /api/v1/search
```

### Query Parameters
- `q` (required): Search query (2-100 chars)
- `category` (optional): `all`, `users`, `feedback`, `files`, `audit` (default: `all`)
- `page` (optional): Page number (default: 1)
- `limit` (optional): Results per page (default: 5)

### Response Structure
```json
{
  "query": "john",
  "category": "all",
  "results": {
    "users": {
      "items": [...],
      "total": 15,
      "page": 1,
      "limit": 5,
      "hasMore": true
    }
  },
  "totalResults": 15,
  "searchTime": 145
}
```

---

## Future Extensions

### Adding a New Category (e.g., Feedback)

The architecture is designed for minimal effort:

**Step 1:** Types are already defined in `lib/types/search.ts` ✅

**Step 2:** Add URL mapper (one line):
```typescript
const CATEGORY_URL_MAPPERS = {
  users: (item: UserSearchResult) => `/admin/users/${item.id}`,
  feedback: (item: FeedbackSearchResult) => `/admin/feedback/${item.id}`, // ADD THIS
}
```

**Step 3:** Create renderer function (5-10 minutes):
```typescript
function renderFeedbackItem(item: FeedbackSearchResult, onSelect: (url: string) => void) {
  return (
    <CommandItem key={item.id} onSelect={() => item.url && onSelect(item.url)}>
      <Icons.MessageSquare className="mr-2 h-4 w-4" />
      <div className="flex-1">
        <div className="font-medium">{item.title}</div>
        <div className="text-xs text-muted-foreground truncate">{item.content}</div>
      </div>
      <Badge>{item.status}</Badge>
    </CommandItem>
  )
}
```

**Step 4:** Add render logic to component (5 minutes):
```typescript
{searchData?.results.feedback && (
  <CommandGroup heading={`Feedback (${searchData.results.feedback.total})`}>
    {searchData.results.feedback.items.map(item =>
      renderFeedbackItem(item, (url) => router.push(url))
    )}
    {/* Load more logic */}
  </CommandGroup>
)}
```

**Total Time: ~20-25 minutes per category**

---

## Performance Optimizations

1. **Debouncing:** 400ms delay reduces API load
2. **Query Caching:** TanStack Query caches for 5 minutes
3. **Minimum Query Length:** Only search when query length ≥ 2
4. **Progressive Loading:** Load 5 initially, 10 per increment
5. **Efficient API Calls:** Single call returns all categories

---

## Testing

### Type Checking
```bash
npm run typecheck  # ✅ No errors
```

### Linting
```bash
npm run lint  # ✅ No errors
```

### Manual Testing Required
- [ ] Search functionality with various queries
- [ ] User result navigation
- [ ] Load more pagination
- [ ] Loading states
- [ ] Error handling
- [ ] Keyboard navigation
- [ ] Mobile responsiveness

---

## Files Changed

| File | Type | Description |
|------|------|-------------|
| `lib/types/search.ts` | New | Search type definitions |
| `lib/types/index.ts` | New | Type exports |
| `hooks/use-search.ts` | New | Search hooks and URL processing |
| `components/search.tsx` | Modified | API integration and user rendering |
| `components/icons.tsx` | Modified | Added missing icons |
| `package.json` | Modified | Added use-debounce dependency |

---

## Configuration

No additional configuration required. The search component automatically:
- Uses the API URL from `NEXT_PUBLIC_API_URL` environment variable
- Includes credentials (cookies) in requests
- Handles errors gracefully

---

## Accessibility

- ✅ Keyboard navigation supported (arrow keys, enter, escape)
- ✅ ARIA labels on all interactive elements
- ✅ Loading states announced
- ✅ Focus management maintained

---

## Known Limitations

1. Only users category is rendered (by design - others planned for future)
2. Maximum 50 accumulated results recommended for UX
3. Search history not persisted (planned for v2.0)
4. No advanced search operators (planned for v2.0)

---

## Related Documentation

- [Plan Document](/plan/api-search-integration.md) - Detailed planning and architecture
- [Admin Integration](/docs/admin-integration.md) - Admin panel integration
- [Authentication Security](/docs/authentication-security-audit.md) - Auth security patterns

---

## Maintenance Notes

- Search debounce delay can be adjusted in `hooks/use-search.ts` (currently 400ms)
- Initial result limit can be adjusted in `components/search.tsx` (currently 5)
- Load more increment can be adjusted in `hooks/use-search.ts` (currently 10)
- Cache duration can be adjusted in `useSearch` and `useLoadMore` hooks (currently 5 minutes)
