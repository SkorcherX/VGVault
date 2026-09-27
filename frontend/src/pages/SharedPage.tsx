import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { ErrorText, money } from '../components'
import CollectionPage from './CollectionPage'

interface Sharer {
  id: number
  username: string
  items: number
  total_value: number
  shows_paid: boolean
}

export function SharedListPage() {
  const sharers = useQuery({ queryKey: ['sharers'], queryFn: () => api.get<Sharer[]>('/shared') })
  return (
    <div className="page">
      <div className="page-head">
        <h1>Shared collections</h1>
      </div>
      <p className="muted">
        Collections other people on this VGVault have chosen to share. You can share yours from your{' '}
        <Link to="/account" className="link">
          account settings
        </Link>
        .
      </p>
      <ErrorText error={sharers.error} />
      {sharers.data?.length === 0 && <p className="muted">Nobody else is sharing a collection yet.</p>}
      <div className="sharers">
        {sharers.data?.map((s) => (
          <Link key={s.id} to={`/shared/${s.id}`} className="card sharer">
            <strong>{s.username}</strong>
            <div className="kpi-value">{money(s.total_value)}</div>
            <div className="muted small">
              {s.items} {s.items === 1 ? 'item' : 'items'}
              {s.shows_paid && ' · shows prices paid'}
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

export function SharedCollectionRoute() {
  const { id } = useParams()
  const ownerId = Number(id)
  if (!Number.isInteger(ownerId)) return <p className="error">Not found.</p>
  // key: reset filters/paging when switching between people
  return <CollectionPage key={ownerId} ownerId={ownerId} />
}
