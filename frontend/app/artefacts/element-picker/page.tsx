"use client"

import { useState } from "react"

import { ELEMENTS, ElementPicker } from "@/components/artefacts/element-picker"
import { appUrl } from "@/lib/app-url"

import styles from "./page.module.css"

export default function ElementPickerArtefactPage() {
  const [value, setValue] = useState<string | null>("Cu")
  const selected = ELEMENTS.find((element) => element.symbol === value)

  return (
    <main className={styles.page}>
      <nav className={styles.navigation} aria-label="Artefact navigation">
        <a href={appUrl("/")}>← XAScraft</a>
        <span>Dr.XAS artefacts</span>
      </nav>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>ELEMENT PICKER</p>
          <h1>One table. Every element.</h1>
          <p className={styles.introduction}>
            Choose from 118 elements, with the familiar Dr.XAS palette.
          </p>
        </div>
        <a
          className={styles.download}
          href={appUrl("/artefacts/drxas-element-picker.zip")}
          download="drxas-element-picker.zip"
        >
          Download source ZIP <span aria-hidden="true">↓</span>
        </a>
      </header>
      <section className={styles.preview} aria-labelledby="preview-heading">
        <div className={styles.controls}>
          <p className={styles.eyebrow}>LIVE PREVIEW</p>
          <h2 id="preview-heading">Contains element</h2>
          <p>Open the periodic table and choose an element.</p>
          <ElementPicker value={value} onChange={setValue} />
        </div>
        <div className={styles.selection} aria-live="polite" aria-atomic="true">
          {selected ? (
            <>
              <div className={styles.elementTile} aria-hidden="true">
                <span>{selected.number}</span>
                <strong>{selected.symbol}</strong>
                <span>{selected.name}</span>
              </div>
              <div>
                <p className={styles.selectionLabel}>Selected element</p>
                <h2>{selected.name}</h2>
                <p>{selected.symbol} · Atomic number {selected.number}</p>
              </div>
            </>
          ) : (
            <div>
              <p className={styles.selectionLabel}>Element filter cleared</p>
              <h2>Any element</h2>
              <p>Choose an element to narrow your search.</p>
            </div>
          )}
        </div>
      </section>
      <footer className={styles.footer}>
        <p>Reuse the React component and scoped styles in your app; your app owns the selected value.</p>
        <span>React 18+ · CSS Modules · MIT</span>
      </footer>
    </main>
  )
}
