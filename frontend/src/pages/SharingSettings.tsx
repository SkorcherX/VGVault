import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { ErrorText } from '../components'

interface Sharing {
  share_collection: boolean
  share_paid: boolean
}

export default function SharingSettings() {
  const qc = useQueryClient()
  const current = useQuery({ queryKey: ['sharing'], queryFn: () => api.get<Sharing>('/auth/sharing') })
  const save = useMutation({
    mutationFn: (body: Sharing) => api.put<Sharing>('/auth/sharing', body),
    onSuccess: (data) => qc.setQueryData(['sharing'], data),
  })
  const s = current.data
  if (!s) return null

  return (
    <div className="card">
      <h2>Sharing</h2>
      <p className="muted small">
        Let other people signed in to this VGVault browse your collection (read-only). It is never public on the
        internet. Notes and storage locations always stay private.
      </p>
      <label className="check" style={{ marginBottom: '0.5rem' }}>
        <input
          type="checkbox"
          checked={s.share_collection}
          disabled={save.isPending}
          onChange={(e) => save.mutate({ share_collection: e.target.checked, share_paid: s.share_paid })}
        />
        Share my collection with other users
      </label>
      <label className="check" style={{ marginLeft: '1.5rem', opacity: s.share_collection ? 1 : 0.5 }}>
        <input
          type="checkbox"
          checked={s.share_paid}
          disabled={!s.share_collection || save.isPending}
          onChange={(e) => save.mutate({ share_collection: true, share_paid: e.target.checked })}
        />
        Also show what I paid (purchase / sold prices and dates, wishlist targets)
      </label>
      <ErrorText error={save.error} />
    </div>
  )
}
