"use client"

import { useState } from "react"

import { ElementPicker } from "./index"

/** The host owns the selected symbol and decides when to search or save it. */
export function ElementPickerExample() {
  const [element, setElement] = useState<string | null>("Cu")

  return (
    <section aria-label="Structure element filter">
      <p>Contains element</p>
      <ElementPicker value={element} onChange={setElement} />
      <p aria-live="polite">{element ? `Selected: ${element}` : "Any element"}</p>
    </section>
  )
}
