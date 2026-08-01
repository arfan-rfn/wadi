/**
 * Common types shared across multiple features
 * Only include truly generic types here
 */

export interface BaseResponse {
  success: boolean
  message: string
}

// Standard API response wrapper type
export interface APIResponse<T> {
  data: T
  status: number
  success: boolean
}

export interface PaginationParams {
  page: number
  limit: number
  sort?: string
  order?: 'asc' | 'desc'
}

export interface PaginatedResponse<T> {
  data: T[]
  pagination: {
    page: number
    limit: number
    total: number
    totalPages: number
  }
}