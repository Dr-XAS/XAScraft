"use client"

import { SectionHelp } from "../section-help"
import { useId, useRef, useState, type ReactNode } from "react"
import { viewerIcons } from "../athena-viewer-icons"
import type { ViewerId } from "@/lib/athena-viewer-order"
import { ViewerExportMenu, type ViewerExportItem } from "./viewer-export-menu"
import styles from "./viewer-panel.module.css"

/** Keep each plot mounted so collapsing preserves its camera and display controls. */
export function ViewerPanel({ title, label = title, viewerId, actions, help, children, className = "",
  exportItems, exportImages = true, exportDisabled = false, exportFilename }: {
  title: string
  label?: string
  viewerId?: ViewerId
  actions?: ReactNode
  help?: ReactNode
  children: ReactNode
  className?: string
  exportItems?: ViewerExportItem[]
  exportImages?: boolean
  exportDisabled?: boolean
  exportFilename?: string
}) {
  const id = useId()
  const panel = useRef<HTMLElement>(null)
  const [collapsed, setCollapsed] = useState(false)
  const Icon = viewerId ? viewerIcons[viewerId] : null

  function toggle() {
    setCollapsed(value => !value)
    // Plotly listens for window resizing; notify it after the panel is visible.
    if (collapsed) window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")))
  }

  return <section ref={panel} className={`${styles.panel} ${className}`.trim()} aria-label={label} data-viewer-panel data-collapsed={collapsed}>
    <header className={styles.heading}>
      <h3><button type="button" className={styles.toggle} aria-expanded={!collapsed} aria-controls={id}
        aria-label={`${collapsed ? "Expand" : "Collapse"} ${title}`} onClick={toggle}>
        <svg className={styles.triangle} viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M3.5 2.5 8 6l-4.5 3.5Z" fill="currentColor" /></svg>
        {Icon && <Icon className={styles.icon} size={20} strokeWidth={2} aria-hidden="true" />}
        <span>{title}</span>
      </button>{help && <SectionHelp label={title}>{help}</SectionHelp>}</h3>
      <div className={styles.actions} hidden={collapsed}>{actions}<ViewerExportMenu title={title} items={exportItems}
        container={panel} images={exportImages} disabled={exportDisabled || collapsed} filename={exportFilename} /></div>
    </header>
    <div id={id} className={styles.content} hidden={collapsed}>{children}</div>
  </section>
}
