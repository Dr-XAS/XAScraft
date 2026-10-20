"use client"

import { useLayoutEffect, useRef, useState, type FocusEvent } from "react"

type NumberDisplayValue = number | string | null | undefined
type NumberDisplayConstraints = { min?: number; max?: number; step?: number | string }

// A complete decimal number only: blank/partial edits ("-", "1.", "1e-")
// must stay untouched, including when a parent retains them after blur.
const completeNumber = /^[+-]?(?:\d+|\d*\.\d+)(?:e[+-]?\d+)?$/i

export function compactNumberDisplay(raw: NumberDisplayValue, { min, max, step = "any" }: NumberDisplayConstraints = {}): string {
  const text = raw == null ? "" : String(raw)
  if (!completeNumber.test(text)) return text
  const value = Number(text)
  if (!Number.isFinite(value)) return text

  // Seven significant digits keep small quantities visible without filling
  // narrow controls with floating-point tails. This string is display only.
  const compact = String(Number(value.toPrecision(7)))
  const rounded = Number(compact)
  if (compact.length >= text.length) return text

  if (rounded !== value) {
    // Native number inputs validate their displayed value. Preserve exact
    // text for stepped fields and around bounds, including invalid values,
    // so a shorter display cannot conceal or introduce a validation error.
    if (step !== "any") return text
    if (min !== undefined && (value < min || Math.sign(value - min) !== Math.sign(rounded - min))) return text
    if (max !== undefined && (value > max || Math.sign(value - max) !== Math.sign(rounded - max))) return text
  }
  return compact
}

/**
 * Presentation only: the caller continues to own its exact value and edit
 * handlers. Focus/blur never call onChange or commit a rounded value.
 */
export function useCompactNumberDisplay(raw: NumberDisplayValue, constraints?: NumberDisplayConstraints) {
  const [focused, setFocused] = useState(false)
  const reselect = useRef<HTMLInputElement | null>(null)
  const exact = raw == null ? "" : String(raw)
  const compact = compactNumberDisplay(raw, constraints)
  useLayoutEffect(() => {
    const input = reselect.current
    reselect.current = null
    // Swapping in the exact text drops the selection a Tab focus made, so the
    // next keystrokes would append to it. Select it again so typing replaces.
    if (input && input === document.activeElement) input.select()
  }, [focused])
  return {
    // A number while editing: React compares it loosely with the input's text,
    // so "10." and "10.0" survive instead of collapsing to "10" mid-typing.
    value: focused && typeof raw === "number" ? raw : focused ? exact : compact,
    title: compact !== exact ? exact : undefined,
    onFocus: (event?: FocusEvent<HTMLInputElement>) => {
      if (event && compact !== exact) reselect.current = event.currentTarget
      setFocused(true)
    },
    onBlur: () => setFocused(false),
  }
}
