import "@testing-library/jest-dom/vitest"
import { useState } from "react"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { compactNumberDisplay, useCompactNumberDisplay } from "./use-compact-number-display"

afterEach(cleanup)

describe("compact numeric presentation", () => {
  it.each([
    [8979.123456789, "8979.123"],
    [0.003123456789, "0.003123457"],
    [1.234567891e-12, "1.234568e-12"],
    [-145.123456789, "-145.1235"],
    [25.019, "25.019"],
    [0, "0"],
    [null, ""],
    [undefined, ""],
    ["1e3", "1e3"],
    [Number.MIN_VALUE, "5e-324"],
  ] as const)("formats %s without zeroing small quantities", (raw, expected) => {
    expect(compactNumberDisplay(raw)).toBe(expected)
  })

  it.each(["", "-", "+", ".", "1.", "1e", "1e-", "1e+", "NaN", "Infinity", " 1.23 "])("retains blank or incomplete text %j", raw => {
    expect(compactNumberDisplay(raw)).toBe(raw)
  })

  it("preserves exact text when rounding would hide or introduce a boundary error", () => {
    expect(compactNumberDisplay(1.00000004, { max: 1 })).toBe("1.00000004")
    expect(compactNumberDisplay(0.99999996, { min: 1 })).toBe("0.99999996")
    expect(compactNumberDisplay(0.99999996, { max: 0.99999999 })).toBe("0.99999996")
    expect(compactNumberDisplay(0.99999996, { max: 1 })).toBe("0.99999996")
    expect(compactNumberDisplay(1.00000004, { min: 1 })).toBe("1.00000004")
    expect(compactNumberDisplay(2.345678912, { min: 0, max: 3 })).toBe("2.345679")
  })

  it("keeps exact numbers for integer and other stepped inputs", () => {
    expect(compactNumberDisplay(12345678, { step: 1 })).toBe("12345678")
    expect(compactNumberDisplay(0.123456789, { step: "0.000000001" })).toBe("0.123456789")
    expect(compactNumberDisplay(1.00000004, { step: "0.1" })).toBe("1.00000004")
  })
})

describe("number display focus", () => {
  it("restores full precision for editing and never commits through focus or blur", () => {
    const changed = vi.fn()
    const submitted = vi.fn()
    function Host() {
      const [value, setValue] = useState(8979.123456789)
      const display = useCompactNumberDisplay(value)
      return <form onSubmit={event => { event.preventDefault(); submitted(value) }}>
        <input aria-label="Energy" type="number" step="any" {...display} onChange={event => {
          changed(Number(event.target.value))
          setValue(Number(event.target.value))
        }} />
        <button type="submit">Save</button>
      </form>
    }
    render(<Host />)
    const input = screen.getByRole("spinbutton", { name: "Energy" })
    expect(input).toHaveValue(8979.123)
    expect(input).toHaveAttribute("title", "8979.123456789")
    fireEvent.focus(input)
    expect(input).toHaveValue(8979.123456789)
    fireEvent.blur(input)
    expect(input).toHaveValue(8979.123)
    expect(changed).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    expect(submitted).toHaveBeenLastCalledWith(8979.123456789)

    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: "8980.987654321" } })
    expect(input).toHaveValue(8980.987654321)
    fireEvent.blur(input)
    expect(input).toHaveValue(8980.988)
    expect(changed).toHaveBeenCalledExactlyOnceWith(8980.987654321)
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    expect(submitted).toHaveBeenLastCalledWith(8980.987654321)
  })

  it("keeps a typed trailing zero while the parent holds the parsed number", () => {
    function Host() {
      const [value, setValue] = useState(10)
      const display = useCompactNumberDisplay(value)
      return <input aria-label="k max" type="number" step="any" {...display} onChange={event => setValue(Number(event.target.value))} />
    }
    render(<Host />)
    const input = screen.getByRole("spinbutton", { name: "k max" }) as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: "10.0" } })
    expect(input.value).toBe("10.0")
    fireEvent.change(input, { target: { value: "10.05" } })
    expect(input.value).toBe("10.05")
  })

  it("selects the exact text it swaps in on focus so typing replaces it", () => {
    const select = vi.spyOn(HTMLInputElement.prototype, "select")
    function Host({ value }: { value: number }) {
      const display = useCompactNumberDisplay(value)
      return <input aria-label="k max" type="number" step="any" {...display} onChange={() => {}} />
    }
    const view = render(<Host value={11.902728727719536} />)
    const input = screen.getByRole("spinbutton", { name: "k max" }) as HTMLInputElement
    act(() => input.focus())
    expect(input).toHaveValue(11.902728727719536)
    expect(select).toHaveBeenCalledTimes(1)
    act(() => input.blur())
    view.rerender(<Host value={10} />)
    act(() => input.focus())
    expect(select).toHaveBeenCalledTimes(1)
    select.mockRestore()
  })

  it("refreshes an automatic display without converting a null recipe into an override", () => {
    const changed = vi.fn()
    function Host({ effective }: { effective: number }) {
      const [value, setValue] = useState<number | null>(null)
      const [cleared, setCleared] = useState(false)
      const display = useCompactNumberDisplay(value ?? (cleared ? "" : effective))
      return <>
        <input aria-label="Edge step" type="number" step="any" {...display}
          onBlur={() => { display.onBlur(); setCleared(false) }}
          onChange={event => {
            const next = event.target.value === "" ? null : Number(event.target.value)
            setCleared(event.target.value === "")
            setValue(next)
            changed(next)
          }} />
        <output data-testid="recipe">{value === null ? "automatic" : String(value)}</output>
      </>
    }
    const view = render(<Host effective={0.0000123456789} />)
    const input = screen.getByRole("spinbutton", { name: "Edge step" })
    expect(input).toHaveValue(0.00001234568)
    fireEvent.focus(input)
    expect(input).toHaveValue(0.0000123456789)
    fireEvent.blur(input)
    expect(screen.getByTestId("recipe")).toHaveTextContent("automatic")
    expect(changed).not.toHaveBeenCalled()

    view.rerender(<Host effective={0.0000987654321} />)
    expect(input).toHaveValue(0.00009876543)
    fireEvent.focus(input)
    expect(input).toHaveValue(0.0000987654321)
    fireEvent.change(input, { target: { value: "0.002345678912" } })
    fireEvent.change(input, { target: { value: "" } })
    expect(input).toHaveValue(null)
    expect(screen.getByTestId("recipe")).toHaveTextContent("automatic")
    fireEvent.blur(input)
    expect(input).toHaveValue(0.00009876543)
    expect(changed.mock.calls).toEqual([[0.002345678912], [null]])
  })

  it("preserves existing native validation while compact or focused", () => {
    function Host({ value, min, max, step = "any" }: { value: number; min?: number; max?: number; step?: string }) {
      const display = useCompactNumberDisplay(value, { min, max, step })
      return <input aria-label="Bounded value" type="number" min={min} max={max} step={step} {...display} readOnly={false} onChange={() => {}} />
    }
    const view = render(<Host value={1.00000004} max={1} />)
    const input = screen.getByRole("spinbutton", { name: "Bounded value" }) as HTMLInputElement
    expect(input.validity.rangeOverflow).toBe(true)
    fireEvent.focus(input)
    fireEvent.blur(input)
    expect(input.validity.rangeOverflow).toBe(true)
    view.rerender(<Host value={0.99999996} max={0.99999999} />)
    expect(input.validity.valid).toBe(true)
    view.rerender(<Host value={1.00000004} min={0} step="0.1" />)
    expect(input.validity.stepMismatch).toBe(true)
    fireEvent.focus(input)
    fireEvent.blur(input)
    expect(input.validity.stepMismatch).toBe(true)
  })
})
