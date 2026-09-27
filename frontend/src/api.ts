export type Role = 'admin' | 'user'
export type Category = 'game' | 'console' | 'pc_big_box' | 'controller' | 'accessory' | 'other'
export type MediaType = 'cartridge' | 'disc' | 'card' | 'floppy' | 'digital' | 'mixed' | 'none'
export type ItemStatus = 'owned' | 'wishlist' | 'sold'
export type Condition = 'loose' | 'cib' | 'new' | 'graded' | 'box_only' | 'manual_only'

export const CATEGORIES: Record<Category, string> = {
  game: 'Game',
  console: 'Console',
  pc_big_box: 'PC Big Box',
  controller: 'Controller',
  accessory: 'Accessory',
  other: 'Other',
}
export const MEDIA_TYPES: Record<MediaType, string> = {
  cartridge: 'Cartridge',
  disc: 'Disc',
  card: 'Card',
  floppy: 'Floppy',
  digital: 'Digital',
  mixed: 'Mixed',
  none: 'None',
}
export const STATUSES: Record<ItemStatus, string> = {
  owned: 'Owned',
  wishlist: 'Wishlist',
  sold: 'Sold',
}
export const CONDITIONS: Record<Condition, string> = {
  loose: 'Loose',
  cib: 'CIB',
  new: 'New / Sealed',
  graded: 'Graded',
  box_only: 'Box only',
  manual_only: 'Manual only',
}

export interface User {
  id: number
  username: string
  email: string | null
  role: Role
  is_active: boolean
}

export interface Platform {
  id: number
  name: string
  slug: string
  brand: string
  generation: number | null
  era: string | null
  media_type: MediaType
  handheld: boolean
  region: string
  release_year: number | null
  pricecharting_slug: string | null
}

export interface Product {
  id: number
  title: string
  platform_id: number
  platform: Platform
  category: Category
  region: string | null
  genre: string | null
  release_date: string | null
  upc: string | null
  pricecharting_id: string | null
  pricecharting_url: string | null
}

export interface ItemFields {
  status: ItemStatus
  condition: Condition
  has_item: boolean
  has_box: boolean
  has_manual: boolean
  has_inserts: boolean
  grade: string | null
  quantity: number
  purchase_price: string | null
  purchase_date: string | null
  sold_price: string | null
  sold_date: string | null
  target_price: string | null
  location: string | null
  tags: string[]
  notes: string | null
}

export interface Item extends ItemFields {
  id: number
  product: Product
  created_at: string
  updated_at: string
}

export interface Facets {
  brands: string[]
  eras: string[]
  platforms: { id: number; name: string }[]
  regions: string[]
  tags: string[]
  locations: string[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Params = Record<string, string | number | boolean | (string | number)[] | null | undefined>

function toQuery(params?: Params): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    for (const v of Array.isArray(value) ? value : [value]) search.append(key, String(v))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  const res = await fetch(`/api${path}${toQuery(params)}`, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let message = res.statusText
    try {
      const data = await res.json()
      message =
        typeof data.detail === 'string'
          ? data.detail
          : (data.detail?.map?.((d: { msg: string }) => d.msg).join(', ') ?? message)
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, message)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>('GET', path, undefined, params),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: (path: string) => request<void>('DELETE', path),
}
