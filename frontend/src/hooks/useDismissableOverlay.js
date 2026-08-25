import { useEffect, useRef } from 'react'

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

// Shared keyboard/focus behavior for any dismissable overlay -- a dropdown
// menu, popover, or drawer: Escape closes it, Tab is trapped inside it
// while open, focus moves to its first focusable element on open, and
// focus returns to whatever triggered it on close. Used by ExportMenu,
// AskCommandHistory, and RepositoryBriefDrawer instead of each
// reimplementing this.
//
// Returns a ref -- attach it to the overlay's outermost container.
//
// `onClose` is read through a ref, not as an effect dependency: callers
// that pass an inline arrow function (a fresh identity every render, e.g.
// `onClose={() => setOpen(false)}`) must not cause this effect to
// re-run on every parent re-render -- that would re-capture the trigger
// and yank focus back to the first element mid-interaction. Only `open`
// actually changing should do that.
export function useDismissableOverlay(open, onClose) {
  const containerRef = useRef(null)
  const triggerRef = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return undefined

    triggerRef.current = document.activeElement

    const focusable = containerRef.current?.querySelectorAll(FOCUSABLE_SELECTOR)
    focusable?.[0]?.focus()

    function handleKeydown(event) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
        return
      }

      if (event.key !== 'Tab' || !containerRef.current) return
      const focusableEls = containerRef.current.querySelectorAll(FOCUSABLE_SELECTOR)
      if (focusableEls.length === 0) return

      const first = focusableEls[0]
      const last = focusableEls[focusableEls.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeydown)
    return () => {
      document.removeEventListener('keydown', handleKeydown)
      triggerRef.current?.focus?.()
    }
  }, [open])

  return containerRef
}
