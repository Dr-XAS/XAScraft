"use client"

import type { ReactNode } from "react"
import { SectionHelp } from "../section-help"
import styles from "./viewer-plot-space.module.css"

interface PlotSpaceOption<Value extends string> {
  value: Value
  label: string
  description?: string
}

/** Shared placement and selected styling; the caller owns the plotted space and data. */
export function ViewerPlotSpace<Value extends string>({ label, options, value, onChange, onSpecialPlot,
  tabs = false, help, children }: {
  label: string
  options: readonly PlotSpaceOption<Value>[]
  value: Value | null
  onChange: (value: Value) => void
  onSpecialPlot?: (value: Value) => void
  tabs?: boolean
  help?: ReactNode
  children?: ReactNode
}) {
  return <div className={`ath-plot-top ${styles.toolbar}`} data-viewer-plot-toolbar>
    <div className={styles.spaces} role={tabs ? "tablist" : "group"} aria-label={label}>
      {options.map(option => <button type="button" key={option.value} className={styles.space}
        role={tabs ? "tab" : undefined} aria-selected={tabs ? value === option.value : undefined}
        aria-pressed={tabs ? undefined : value === option.value} data-selected={value === option.value}
        title={onSpecialPlot ? "Right-click for Craft’s special plot" : undefined}
        onContextMenu={onSpecialPlot ? event => { event.preventDefault(); onSpecialPlot(option.value) } : undefined}
        onClick={() => onChange(option.value)}>
        <b>{option.label}</b>{option.description && <span>{option.description}</span>}
      </button>)}
    </div>
    {help && <SectionHelp label={label}>{help}</SectionHelp>}
    {children}
  </div>
}
