import { Link } from 'react-router-dom'
import { EmptyState } from '../components/ui'

export function NotFound() {
  return (
    <EmptyState title="Page not found" action={<Link to="/" className="btn btn-primary">Go to the dashboard</Link>}>
      The address may be mistyped, or the item may have been deleted.
    </EmptyState>
  )
}
