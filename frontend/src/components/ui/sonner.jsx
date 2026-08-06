import { Toaster as Sonner } from 'sonner'

function Toaster(props) {
  return (
    <Sonner
      theme="dark"
      style={{
        '--normal-bg': 'var(--card)',
        '--normal-text': 'var(--foreground)',
        '--normal-border': 'var(--card-border)',
      }}
      {...props}
    />
  )
}

export { Toaster }
