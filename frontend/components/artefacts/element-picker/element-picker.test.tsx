import "@testing-library/jest-dom/vitest"

import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { useState } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ElementPicker } from "./index"
import { ELEMENTS } from "./elements"

const copper = "Cu · Copper · Atomic number 29"
const zinc = "Zn · Zinc · Atomic number 30"
const sulfur = "S · Sulfur · Atomic number 16"

function openPicker(multiple = false) {
  const name = multiple ? "Pick elements" : "Pick element"
  const trigger = screen.getByRole("button", { name })
  trigger.focus()
  fireEvent.click(trigger)
  return { trigger, dialog: screen.getByRole("dialog", { name }) }
}

function MultiplePicker({ initial = [], onChange = () => {} }: { initial?: string[]; onChange?: (symbols: string[]) => void }) {
  const [value, setValue] = useState(initial)
  return <ElementPicker multiple value={value} onChange={symbols => { setValue(symbols); onChange(symbols) }} />
}

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", "") } })
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); this.dispatchEvent(new Event("close")) } })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe("ElementPicker", () => {
  it("provides all 118 elements with unique atomic numbers and symbols", () => {
    expect(ELEMENTS).toHaveLength(118)
    expect(new Set(ELEMENTS.map(element => element.symbol)).size).toBe(118)
    expect(ELEMENTS.map(element => element.number).sort((a, b) => a - b)).toEqual(Array.from({ length: 118 }, (_, index) => index + 1))
    render(<ElementPicker value="Cu" onChange={vi.fn()} />)
    const { dialog } = openPicker()
    expect(within(dialog).getAllByRole("button", { name: / · Atomic number \d+$/ })).toHaveLength(118)
    expect(within(dialog).getByRole("button", { name: copper })).toHaveAttribute("aria-pressed", "true")
    expect(within(dialog).getByRole("button", { name: sulfur })).toHaveAttribute("aria-pressed", "false")
  })

  it.each(["cU", "  copper  ", "29"])("finds an element using %j without committing a selection", query => {
    const onChange = vi.fn()
    render(<ElementPicker value={null} onChange={onChange} />)
    const { dialog } = openPicker()
    fireEvent.change(within(dialog).getByLabelText("Find element"), { target: { value: query } })
    expect(within(dialog).getByRole("button", { name: copper })).toBeEnabled()
    expect(within(dialog).getByRole("button", { name: "O · Oxygen · Atomic number 8" })).toBeDisabled()
    expect(onChange).not.toHaveBeenCalled()
  })

  it("returns the canonical symbol, closes, and restores trigger focus", () => {
    const onChange = vi.fn()
    render(<ElementPicker value="Cu" onChange={onChange} />)
    const { trigger, dialog } = openPicker()
    fireEvent.click(within(dialog).getByRole("button", { name: sulfur }))
    expect(onChange).toHaveBeenCalledExactlyOnceWith("S")
    expect(screen.queryByRole("dialog", { name: "Pick element" })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("prefers an exact chemical symbol on Enter over element-name matches", () => {
    const onChange = vi.fn()
    render(<ElementPicker value={null} onChange={onChange} />)
    const { dialog } = openPicker()
    const search = within(dialog).getByLabelText("Find element")
    fireEvent.change(search, { target: { value: "cu" } })
    expect(within(dialog).getByRole("button", { name: copper })).toBeEnabled()
    expect(within(dialog).getByRole("button", { name: "Cm · Curium · Atomic number 96" })).toBeEnabled()
    fireEvent.keyDown(search, { key: "Enter" })
    expect(onChange).toHaveBeenCalledExactlyOnceWith("Cu")
    expect(screen.queryByRole("dialog", { name: "Pick element" })).not.toBeInTheDocument()
  })

  it("clears the selection explicitly and closes", () => {
    const onChange = vi.fn()
    render(<ElementPicker value="Cu" onChange={onChange} />)
    const { trigger, dialog } = openPicker()
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear selection" }))
    expect(onChange).toHaveBeenCalledExactlyOnceWith(null)
    expect(screen.queryByRole("dialog", { name: "Pick element" })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it.each(["close button", "Escape"])("dismisses with %s without changing the selection", action => {
    const onChange = vi.fn()
    render(<ElementPicker value="Cu" onChange={onChange} />)
    const { trigger, dialog } = openPicker()
    if (action === "close button") fireEvent.click(within(dialog).getByRole("button", { name: "Close element picker" }))
    else fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }))
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.queryByRole("dialog", { name: "Pick element" })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("supports arrow navigation and Home/End without selecting on focus", () => {
    const onChange = vi.fn()
    render(<ElementPicker value="Cu" onChange={onChange} />)
    const { dialog } = openPicker()
    const cu = within(dialog).getByRole("button", { name: copper })
    const zn = within(dialog).getByRole("button", { name: zinc })
    act(() => cu.focus())
    fireEvent.keyDown(cu, { key: "ArrowRight" })
    expect(zn).toHaveFocus()
    expect(zn).toHaveAttribute("tabindex", "0")
    expect(cu).toHaveAttribute("tabindex", "-1")
    fireEvent.keyDown(zn, { key: "ArrowLeft" })
    expect(cu).toHaveFocus()
    fireEvent.keyDown(cu, { key: "Home" })
    const hydrogen = within(dialog).getByRole("button", { name: "H · Hydrogen · Atomic number 1" })
    expect(hydrogen).toHaveFocus()
    fireEvent.keyDown(hydrogen, { key: "End" })
    expect(within(dialog).getByRole("button", { name: "Og · Oganesson · Atomic number 118" })).toHaveFocus()
    expect(onChange).not.toHaveBeenCalled()
  })

  it("moves from search to a matching tile with ArrowDown", () => {
    render(<ElementPicker value={null} onChange={vi.fn()} />)
    const { dialog } = openPicker()
    const search = within(dialog).getByLabelText("Find element")
    fireEvent.change(search, { target: { value: "Copper" } })
    fireEvent.keyDown(search, { key: "ArrowDown" })
    expect(within(dialog).getByRole("button", { name: copper })).toHaveFocus()
  })

  it("respects a disabled trigger and a caller-provided label", () => {
    const onChange = vi.fn()
    render(<ElementPicker value={null} onChange={onChange} disabled triggerLabel="Choose absorber" />)
    const trigger = screen.getByRole("button", { name: "Choose absorber" })
    expect(trigger).toBeDisabled()
    fireEvent.click(trigger)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it("selects and deselects multiple elements without closing, using canonical unique symbols", () => {
    const onChange = vi.fn()
    render(<MultiplePicker initial={[" cU ", "cu"]} onChange={onChange} />)
    const { dialog } = openPicker(true)
    const cu = within(dialog).getByRole("button", { name: copper })
    const zn = within(dialog).getByRole("button", { name: zinc })
    expect(cu).toHaveAttribute("aria-pressed", "true")
    fireEvent.click(zn)
    expect(onChange).toHaveBeenLastCalledWith(["Cu", "Zn"])
    expect(dialog).toBeInTheDocument()
    expect(cu).toHaveAttribute("aria-pressed", "true")
    expect(zn).toHaveAttribute("aria-pressed", "true")
    expect(dialog).toHaveTextContent("Cu, Zn · 2 selected")
    fireEvent.click(cu)
    expect(onChange).toHaveBeenLastCalledWith(["Zn"])
    expect(cu).toHaveAttribute("aria-pressed", "false")
    expect(zn).toHaveAttribute("aria-pressed", "true")
    expect(dialog).toBeInTheDocument()
  })

  it("clears all selections while leaving the multiple picker open", () => {
    const onChange = vi.fn()
    render(<MultiplePicker initial={["Cu", "Zn"]} onChange={onChange} />)
    const { dialog } = openPicker(true)
    const clear = within(dialog).getByRole("button", { name: "Clear selection" })
    fireEvent.click(clear)
    expect(onChange).toHaveBeenCalledExactlyOnceWith([])
    expect(dialog).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: copper })).toHaveAttribute("aria-pressed", "false")
    expect(within(dialog).getByRole("button", { name: zinc })).toHaveAttribute("aria-pressed", "false")
    expect(clear).toBeDisabled()
    expect(dialog).toHaveTextContent("No elements selected")
  })

  it("preserves the existing selection order when another element is selected", () => {
    const onChange = vi.fn()
    render(<MultiplePicker initial={["Zn", "Cu"]} onChange={onChange} />)
    const { dialog } = openPicker(true)
    fireEvent.click(within(dialog).getByRole("button", { name: sulfur }))
    expect(onChange).toHaveBeenCalledExactlyOnceWith(["Zn", "Cu", "S"])
  })

  it.each(["Done", "close button", "Escape"])("preserves controlled selections when closed with %s and reopened", action => {
    const onChange = vi.fn()
    render(<MultiplePicker initial={["Cu"]} onChange={onChange} />)
    const { trigger, dialog } = openPicker(true)
    fireEvent.click(within(dialog).getByRole("button", { name: zinc }))
    if (action === "Escape") fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }))
    else fireEvent.click(within(dialog).getByRole("button", { name: action === "Done" ? "Done" : "Close element picker" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    const reopened = openPicker(true).dialog
    expect(within(reopened).getByRole("button", { name: copper })).toHaveAttribute("aria-pressed", "true")
    expect(within(reopened).getByRole("button", { name: zinc })).toHaveAttribute("aria-pressed", "true")
    expect(onChange).toHaveBeenCalledExactlyOnceWith(["Cu", "Zn"])
  })

  it("keeps search and keyboard navigation available while toggling multiple selections", () => {
    const onChange = vi.fn()
    render(<MultiplePicker onChange={onChange} />)
    const { dialog } = openPicker(true)
    const search = within(dialog).getByLabelText("Find element")
    fireEvent.change(search, { target: { value: "cu" } })
    fireEvent.keyDown(search, { key: "Enter" })
    expect(onChange).toHaveBeenLastCalledWith(["Cu"])
    expect(dialog).toBeInTheDocument()
    fireEvent.keyDown(search, { key: "Enter" })
    expect(onChange).toHaveBeenLastCalledWith([])
    fireEvent.keyDown(search, { key: "ArrowDown" })
    const cu = within(dialog).getByRole("button", { name: copper })
    expect(cu).toHaveFocus()
    fireEvent.keyDown(cu, { key: "ArrowRight" })
    expect(within(dialog).getByRole("button", { name: "Hg · Mercury · Atomic number 80" })).toHaveFocus()
    expect(onChange).toHaveBeenCalledTimes(2)
  })
})
