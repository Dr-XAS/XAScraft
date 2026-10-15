"use client"

import { Download, ChevronDown } from "lucide-react"
import { useEffect, useRef, useState, type RefObject } from "react"
import { AthenaContextMenu } from "../athena-context-menu"
import { exportViewerImage, viewerPlots } from "@/lib/viewer-image-export"
import styles from "./viewer-export-menu.module.css"

export type ViewerExportItem = {
  id: string
  label: string
  onSelect: () => void | Promise<void>
  disabled?: boolean
}

export function ViewerExportMenu({ title, items = [], container, images = true, disabled = false, filename = title }: {
  title: string
  items?: ViewerExportItem[]
  container: RefObject<HTMLElement | null>
  images?: boolean
  disabled?: boolean
  filename?: string
}) {
  const trigger = useRef<HTMLButtonElement>(null)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [hasPlots, setHasPlots] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => { if (disabled) setAnchor(null) }, [disabled])

  function open() {
    if (!trigger.current || disabled || busy) return
    const bounds = trigger.current.getBoundingClientRect()
    setHasPlots(viewerPlots(container.current).length > 0)
    setAnchor({ x: bounds.right - 230, y: bounds.bottom + 4 })
  }

  async function run(item: ViewerExportItem) {
    setError("")
    setBusy(true)
    try { await item.onSelect() }
    catch (error) { setError(error instanceof Error ? error.message : "Could not export this viewer. Try again.") }
    finally { setBusy(false) }
  }

  const imageItems: ViewerExportItem[] = images && (hasPlots || items.length === 0) ? (["png", "svg"] as const).map(format => ({
    id: `viewer-image-${format}`, label: `Image (${format.toUpperCase()})`, disabled: !hasPlots,
    onSelect: () => exportViewerImage(container.current, filename, format),
  })) : []
  const choices = [...items, ...imageItems]

  return <div className={styles.control}>
    <button ref={trigger} type="button" className={styles.trigger} aria-label={`Export ${title}`}
      aria-haspopup="menu" aria-expanded={!!anchor && !disabled} disabled={disabled || busy}
      title={`Export ${title}`} onClick={() => anchor ? setAnchor(null) : open()}
      onKeyDown={event => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); open() } }}>
      <Download size={17} strokeWidth={1.8} aria-hidden="true" /><span>{busy ? "exporting…" : "export"}</span><ChevronDown size={12} aria-hidden="true" />
    </button>
    {anchor && !disabled && <AthenaContextMenu label={`Export ${title}`} anchor={anchor} returnFocus={trigger.current} keepOpenOnTriggerPointerDown
      onClose={() => setAnchor(null)} items={choices.map((item, index) => ({ ...item,
        separatorBefore: index === items.length && items.length > 0,
        onSelect: () => { void run(item) },
      }))} />}
    {error && <span className={styles.error} role="alert">{error}</span>}
  </div>
}
