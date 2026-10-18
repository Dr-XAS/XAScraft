"use client"

import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent } from "react"
import { createPortal } from "react-dom"
import { ELEMENTS, type ChemicalElement } from "./elements"
import styles from "./element-picker.module.css"

interface ElementPickerBaseProps {
  disabled?: boolean
  triggerLabel?: string
  className?: string
  /** Applied to both the trigger and portalled dialog, including --ep-* theme tokens. */
  style?: CSSProperties & { [token: `--ep-${string}`]: string | number }
}

export type ElementPickerProps = ElementPickerBaseProps & ({
  multiple?: false
  value: string | null
  onChange: (symbol: string | null) => void
} | {
  multiple: true
  value: string[]
  onChange: (symbols: string[]) => void
})

const orderedElements = [...ELEMENTS].sort((a, b) => a.number - b.number)
const elementsBySymbol = new Map(orderedElements.map(item => [item.symbol.toLowerCase(), item]))
const directions: Record<string, [number, number]> = {
  ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0],
}
const categories: Record<ChemicalElement["category"], string> = {
  alkali: "Alkali metal", alkaline: "Alkaline earth metal", transition: "Transition metal",
  "post-transition": "Post-transition metal", metalloid: "Metalloid", nonmetal: "Nonmetal",
  halogen: "Halogen", noble: "Noble gas", lanthanide: "Lanthanide", actinide: "Actinide",
}

function TableIcon() {
  return <svg width="15" height="15" viewBox="0 0 18 18" fill="none" aria-hidden="true">
    <path d="M1.5 2.5h3v4h9v-4h3v13h-15zM1.5 11h15M4.5 6.5v9m3-9v9m3-9v9m3-13v13" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
  </svg>
}

/** A controlled symbol picker. The host owns persistence, validation and requests. */
export function ElementPicker(props: ElementPickerProps) {
  const { disabled = false, triggerLabel = props.multiple ? "Pick elements" : "Pick element", className, style } = props
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const id = useId()

  function close() {
    setOpen(false)
    if (trigger.current?.isConnected) trigger.current.focus()
  }

  useEffect(() => { if (disabled) setOpen(false) }, [disabled])

  const values = props.multiple ? props.value : props.value ? [props.value] : []
  const selectedSymbols = new Set(values.map(value => value.trim().toLowerCase()))
  const selected = [...selectedSymbols].flatMap(symbol => {
    const item = elementsBySymbol.get(symbol)
    return item ? [item] : []
  })

  function select(symbol: string | null) {
    if (props.multiple) {
      const symbols = selected.map(item => item.symbol)
      props.onChange(symbol === null ? [] : symbols.includes(symbol) ? symbols.filter(item => item !== symbol) : [...symbols, symbol])
    } else {
      close()
      props.onChange(symbol)
    }
  }

  return <>
    <button ref={trigger} type="button" className={`${styles.trigger}${className ? ` ${className}` : ""}`} style={style}
      disabled={disabled} aria-haspopup="dialog" aria-expanded={open && !disabled} aria-controls={open && !disabled ? id : undefined}
      onClick={() => setOpen(true)}><TableIcon />{triggerLabel}</button>
    {open && !disabled && createPortal(<PickerDialog id={id} selected={selected} hasValue={values.length > 0} multiple={props.multiple === true} style={style}
      onClose={close} onSelect={select} />, document.body)}
  </>
}

function PickerDialog({ id, selected, hasValue, multiple, style, onClose, onSelect }: {
  id: string; selected: ChemicalElement[]; hasValue: boolean; multiple: boolean; style?: ElementPickerProps["style"]
  onClose: () => void; onSelect: (symbol: string | null) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const search = useRef<HTMLInputElement>(null)
  const buttons = useRef(new Map<string, HTMLButtonElement>())
  const [query, setQuery] = useState("")
  const [focused, setFocused] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const normalized = query.trim().toLowerCase()
  const selectedSymbols = new Set(selected.map(item => item.symbol))
  const matches = orderedElements.filter(item => !normalized || item.symbol.toLowerCase().startsWith(normalized)
    || item.name.toLowerCase().includes(normalized) || String(item.number) === normalized)
  const matchingSymbols = new Set(matches.map(item => item.symbol))
  const tabStop = [focused, ...selectedSymbols, matches[0]?.symbol].find(symbol => symbol && matchingSymbols.has(symbol))
  const preview = orderedElements.find(item => item.symbol === (hovered ?? focused)) ?? selected[0]
  const selectionSummary = multiple ? selected.map(item => item.symbol).join(", ") : selected[0]?.name

  useEffect(() => {
    const node = dialog.current!
    node.showModal()
    search.current?.focus()
    return () => { if (node.open) node.close() }
  }, [])

  useEffect(() => {
    if (normalized) buttons.current.get(matches[0]?.symbol)?.scrollIntoView?.({ block: "nearest", inline: "nearest" })
  }, [normalized])

  function dismiss() {
    // Release the native modal before restoring focus to a trigger in the host dialog.
    dialog.current?.close()
    onClose()
  }

  function choose(symbol: string | null) {
    if (!multiple) dialog.current?.close()
    onSelect(symbol)
  }

  function focusElement(item?: ChemicalElement) {
    if (!item) return
    const button = buttons.current.get(item.symbol)
    button?.focus({ preventScroll: true })
    button?.scrollIntoView?.({ block: "nearest", inline: "nearest" })
  }

  function navigate(event: KeyboardEvent<HTMLButtonElement>, current: ChemicalElement) {
    const direction = directions[event.key]
    const boundary = event.key === "Home" || event.key === "End"
    if ((!direction && !boundary) || event.altKey || event.ctrlKey || event.metaKey) return
    event.preventDefault()
    if (boundary) { focusElement(event.key === "Home" ? matches[0] : matches.at(-1)); return }
    const [dr, dc] = direction
    const candidates = matches.filter(item => dr ? (item.row - current.row) * dr > 0 : (item.column - current.column) * dc > 0)
    candidates.sort((a, b) => {
      const alignedA = dr ? a.column === current.column : a.row === current.row
      const alignedB = dr ? b.column === current.column : b.row === current.row
      if (alignedA !== alignedB) return Number(alignedB) - Number(alignedA)
      const distance = (item: ChemicalElement) => (item.row - current.row) ** 2 + (item.column - current.column) ** 2
      return distance(a) - distance(b)
    })
    focusElement(candidates[0])
  }

  return <dialog ref={dialog} id={id} className={styles.dialog} style={style} aria-labelledby={`${id}-title`} aria-describedby={`${id}-help`}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); dismiss() }}
    onClose={event => { event.stopPropagation(); if (!event.currentTarget.open) onClose() }}
    onKeyDown={event => { if (event.key === "Escape") event.stopPropagation() }}>
    <header className={styles.header}>
      <div><h2 id={`${id}-title`}>{multiple ? "Pick elements" : "Pick element"}</h2><p id={`${id}-help`}>{multiple ? "Select all elements to include. Click again to deselect." : "Choose an element to fill the field."}</p></div>
      <button type="button" className={styles.close} aria-label="Close element picker" onClick={dismiss}>
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="m4 4 10 10M14 4 4 14" stroke="currentColor" strokeWidth="1.5" /></svg>
      </button>
    </header>
    <div className={styles.searchBar}>
      <label className={styles.search}>
        <svg width="16" height="16" viewBox="0 0 18 18" fill="none" aria-hidden="true"><circle cx="7.5" cy="7.5" r="5" stroke="currentColor" strokeWidth="1.5" /><path d="m11.5 11.5 4 4" stroke="currentColor" strokeWidth="1.5" /></svg>
        <input ref={search} aria-label="Find element" type="search" placeholder="Symbol, name or atomic number" autoComplete="off" value={query}
          onChange={event => { setQuery(event.target.value); setFocused(null); setHovered(null) }}
          onKeyDown={event => {
            if (event.key === "ArrowDown") { event.preventDefault(); focusElement(matches.find(item => item.symbol === tabStop) ?? matches[0]) }
            if (event.key === "Enter") {
              const exactSymbol = matches.find(item => item.symbol.toLowerCase() === normalized)
              const match = exactSymbol ?? (matches.length === 1 ? matches[0] : undefined)
              if (match) { event.preventDefault(); choose(match.symbol) }
            }
          }} />
      </label>
      <span className={styles.count} role="status">{normalized ? matches.length ? `${matches.length} matching element${matches.length === 1 ? "" : "s"}` : "No matching elements" : "118 elements"}</span>
    </div>
    <p className={styles.mobileHint}>Scroll sideways to see the full table.</p>
    <div className={styles.tableScroll}>
      <div className={styles.columns} aria-hidden="true">{Array.from({ length: 18 }, (_, index) => <span key={index}>{index + 1}</span>)}</div>
      <div className={styles.table} role="group" aria-label="Periodic table">
        <div className={styles.preview}>
          {preview ? <><span className={styles.previewSymbol} data-category={preview.category} data-column={preview.column}>{preview.symbol}</span><div><strong>{preview.name}</strong><span>{preview.number} · {categories[preview.category]}</span></div></>
            : <div><strong>Periodic table</strong><span>Explore by symbol, name or atomic number.</span></div>}
        </div>
        {ELEMENTS.map(item => <button type="button" key={item.symbol}
          ref={node => { if (node) buttons.current.set(item.symbol, node); else buttons.current.delete(item.symbol) }}
          className={styles.tile} data-column={item.column} data-category={item.category}
          style={{ gridRow: item.row, gridColumn: item.column }}
          aria-label={`${item.symbol} · ${item.name} · Atomic number ${item.number}`} title={`${item.name} (${item.symbol}) · ${item.number} · ${categories[item.category]}`}
          aria-pressed={selectedSymbols.has(item.symbol)} disabled={!matchingSymbols.has(item.symbol)} tabIndex={tabStop === item.symbol ? 0 : -1}
          onMouseEnter={() => setHovered(item.symbol)} onMouseLeave={() => setHovered(null)} onFocus={() => setFocused(item.symbol)}
          onKeyDown={event => navigate(event, item)} onClick={() => choose(item.symbol)}>
          <span className={styles.number}>{item.number}</span><strong className={styles.symbol}>{item.symbol}</strong><span className={styles.name}>{item.name}</span>
        </button>)}
        <div className={styles.placeholder} style={{ gridRow: 6, gridColumn: 3 }} aria-hidden="true"><strong>57–71</strong><span>La–Lu</span></div>
        <div className={styles.placeholder} style={{ gridRow: 7, gridColumn: 3 }} aria-hidden="true"><strong>89–103</strong><span>Ac–Lr</span></div>
        <div className={styles.series} style={{ gridRow: 9 }}><strong>Lanthanides</strong><span>57–71</span></div>
        <div className={styles.series} style={{ gridRow: 10 }}><strong>Actinides</strong><span>89–103</span></div>
      </div>
    </div>
    <footer className={styles.footer}><span className={styles.selection}>
      <span className={styles.selectionSummary} title={selectionSummary} aria-live={multiple ? "polite" : undefined}>{selected.length ? multiple
        ? <><strong>{selectionSummary}</strong> · {selected.length} selected</>
        : <><strong>{selected[0].symbol}</strong> · {selected[0].name}</>
        : multiple ? "No elements selected" : "No element selected"}</span>
      <small>Arrow keys to move · Enter to {multiple ? "toggle" : "select"}</small></span>
      <div className={styles.actions}>
        <button type="button" className={styles.clear} disabled={!hasValue} onClick={() => choose(null)}>Clear selection</button>
        {multiple && <button type="button" className={styles.done} onClick={dismiss}>Done</button>}
      </div>
    </footer>
  </dialog>
}
