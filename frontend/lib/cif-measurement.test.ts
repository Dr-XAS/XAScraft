import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { GLViewer } from "3dmol"
import { bindCifAtomPicking, drawCifMeasurement, measurementAngle, measurementDistance } from "./cif-measurement"
import { cartesian, latticeVectors } from "./cif-viewer"

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

it("measures displayed Cartesian geometry, including an oblique cell and degenerate angles", () => {
  const lattice = latticeVectors({ a: 4, b: 4, c: 6, alpha: 90, beta: 90, gamma: 60 })!
  const point = (v: number[]) => ({ x: v[0], y: v[1], z: v[2] })
  const origin = point([0, 0, 0])
  const a = point(cartesian([1, 0, 0], lattice))
  const b = point(cartesian([0, 1, 0], lattice))
  expect(measurementDistance(a, b)).toBeCloseTo(4, 10)
  expect(measurementAngle(a, origin, b)).toBeCloseTo(60, 10)
  expect(measurementAngle(a, origin, point([-4, 0, 0]))).toBe(180)
  expect(measurementAngle(a, origin, point([8, 0, 0]))).toBe(0)
  expect(measurementAngle(origin, origin, b)).toBeNull()
})

function fixture() {
  const host = document.createElement("div")
  const canvas = document.createElement("canvas")
  host.append(canvas)
  document.body.append(host)
  vi.spyOn(host, "getBoundingClientRect").mockReturnValue({ left: 10, top: 20, right: 210, bottom: 220, width: 200, height: 200 } as DOMRect)
  const atom = { index: 7, x: 1, y: 2, z: 3 }
  const view = [1, 2, 3, 4, 5, 6, 7, 8]
  const viewer = { getView: vi.fn(() => view), setView: vi.fn(), targetedObjects: vi.fn(() => [{ clickable: atom }]) }
  const onPick = vi.fn()
  const dispose = bindCifAtomPicking(host, viewer as unknown as GLViewer, [atom], onPick)
  const pointer = (type: string, x = 110, y = 120, id = 1, target: EventTarget = canvas, options: MouseEventInit = {}) => {
    const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0, ...options })
    Object.defineProperty(event, "pointerId", { value: id })
    target.dispatchEvent(event)
  }
  return { host, canvas, viewer, view, onPick, dispose, pointer, atom }
}

describe("CIF atom picking gestures", () => {
  it("picks once for a click or small jitter and restores the pre-gesture camera", () => {
    const f = fixture()
    try {
      f.pointer("pointerdown")
      f.pointer("pointerup")
      f.canvas.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }))
      f.canvas.dispatchEvent(new MouseEvent("click", { bubbles: true }))
      expect(f.onPick.mock.calls).toEqual([[7]])
      expect(f.viewer.targetedObjects).toHaveBeenLastCalledWith(0, 0, [f.atom])
      f.pointer("pointerdown")
      f.pointer("pointermove", 113)
      f.pointer("pointerup", 113)
      expect(f.onPick.mock.calls).toEqual([[7], [7]])
      expect(f.viewer.setView).toHaveBeenLastCalledWith(f.view)
      f.viewer.targetedObjects.mockReturnValue([])
      f.pointer("pointerdown"); f.pointer("pointerup")
      expect(f.onPick).toHaveBeenCalledTimes(2)
    } finally { f.dispose() }
  })

  it("rejects a drag even after returning to its start, right clicks, modifier clicks, and cancelled gestures", () => {
    const f = fixture()
    try {
      f.pointer("pointerdown"); f.pointer("pointermove", 150); f.pointer("pointermove"); f.pointer("pointerup")
      f.pointer("pointerdown", 110, 120, 1, f.canvas, { button: 2 }); f.pointer("pointerup")
      f.pointer("pointerdown", 110, 120, 1, f.canvas, { shiftKey: true }); f.pointer("pointerup")
      f.pointer("pointerdown"); f.pointer("pointercancel"); f.pointer("pointerup")
      f.pointer("pointerdown"); f.host.dispatchEvent(new Event("pointerleave")); f.pointer("pointerup")
      f.pointer("pointerdown"); f.pointer("pointerup", 110, 120, 1, document.body)
      f.pointer("pointerdown"); f.pointer("pointerup", 500, 500)
      f.pointer("pointerdown"); f.host.dispatchEvent(new Event("wheel")); f.pointer("pointerup")
      f.pointer("pointerdown"); window.dispatchEvent(new Event("blur")); f.pointer("pointerup")
      expect(f.onPick).not.toHaveBeenCalled()
      expect(f.viewer.setView).not.toHaveBeenCalled()
      f.pointer("pointerdown"); f.pointer("pointerup")
      expect(f.onPick).toHaveBeenCalledOnce()
    } finally { f.dispose() }
  })

  it("cancels a pinch until all fingers lift and removes listeners on disposal", () => {
    const f = fixture()
    f.pointer("pointerdown")
    f.pointer("pointerdown", 130, 120, 2)
    f.pointer("pointerup", 130, 120, 2)
    f.pointer("pointerup")
    expect(f.onPick).not.toHaveBeenCalled()
    f.pointer("pointerdown"); f.pointer("pointerup")
    expect(f.onPick).toHaveBeenCalledOnce()
    f.dispose()
    f.pointer("pointerdown"); f.pointer("pointerup")
    expect(f.onPick).toHaveBeenCalledOnce()
  })
})

describe("CIF measurement tags", () => {
  type Point = { x: number; y: number; z: number }
  type Screen = { x: number; y: number }
  type FakeLabel = { text: string; options: { position: Point; alignment?: string; screenOffset?: Screen }; canvas: { width: number; height: number }; sprite: { material: { screenOffset: Screen | null } } }
  // 3Dmol's SpriteAlignment vectors; +y is up, as in clip space.
  const alignments: Record<string, [number, number]> = {
    topLeft: [1, -1], topCenter: [0, -1], topRight: [-1, -1], centerLeft: [1, 0], center: [0, 0],
    centerRight: [-1, 0], bottomLeft: [1, 1], bottomCenter: [0, 1], bottomRight: [-1, 1],
  }
  const outline = 0.62
  let frames: FrameRequestCallback[] = []
  beforeEach(() => {
    frames = []
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => frames.push(callback))
    vi.stubGlobal("cancelAnimationFrame", (id: number) => { frames[id - 1] = () => {} })
  })
  afterEach(() => vi.unstubAllGlobals())
  const flushFrames = () => { const pending = frames; frames = []; pending.forEach(callback => callback(0)) }

  /** An orthographic camera looking down -z after a turn about y, `scale` pixels per Å. */
  const camera = (scale: number, turn = 0) => (p: Point): Screen => ({ x: 640 + scale * (p.x * Math.cos(turn) + p.z * Math.sin(turn)), y: 200 - scale * p.y })
  function fakeViewer(initial: (p: Point) => Screen) {
    let project = initial
    let changed: ((view: number[]) => void) | null = null
    const labels: FakeLabel[] = []
    const viewer = {
      addLabel: vi.fn((text: string, options: FakeLabel["options"]) => {
        const label = { text, options, canvas: { width: 8 + 7 * [...text].length, height: 23 }, sprite: { material: { screenOffset: options.screenOffset ?? null } } }
        labels.push(label)
        return label
      }),
      removeLabel: vi.fn((label: FakeLabel) => { labels.splice(labels.indexOf(label), 1) }),
      addCustom: vi.fn(() => ({})), addLine: vi.fn(() => ({})), removeShape: vi.fn(), render: vi.fn(),
      modelToScreen: vi.fn((coords: Point[]) => coords.map(p => project(p))),
      setViewChangeCallback: vi.fn((callback: typeof changed) => { changed = callback }),
    }
    return { viewer, labels, project: (p: Point) => project(p), callback: () => changed, rotate(next: (p: Point) => Screen) { project = next; changed?.([]) } }
  }
  type Fake = ReturnType<typeof fakeViewer>
  /** Where 3Dmol draws a tag: its anchor, then alignment, then the pixel screen offset (+y up). */
  function box(fake: Fake, label: FakeLabel) {
    const anchor = fake.project(label.options.position), [ax, ay] = alignments[label.options.alignment ?? "topLeft"]
    const offset = label.sprite.material.screenOffset ?? { x: 0, y: 0 }, { width, height } = label.canvas
    const x = anchor.x + ax * width / 2 + offset.x, y = anchor.y - ay * height / 2 - offset.y
    return { left: x - width / 2, right: x + width / 2, top: y - height / 2, bottom: y + height / 2, x, y }
  }
  function expectReadable(fake: Fake, atoms: Point[], scale: number) {
    const boxes = fake.labels.map(label => ({ text: label.text, box: box(fake, label), anchor: fake.project(label.options.position) }))
    boxes.forEach((a, i) => {
      for (const b of boxes.slice(i + 1)) {
        const overlap = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left) > 0.5 && Math.min(a.box.bottom, b.box.bottom) - Math.max(a.box.top, b.box.top) > 0.5
        expect(overlap, `"${a.text}" overlaps "${b.text}"`).toBe(false)
      }
      atoms.forEach((atom, index) => {
        const center = fake.project(atom)
        const gap = Math.hypot(Math.max(a.box.left - center.x, 0, center.x - a.box.right), Math.max(a.box.top - center.y, 0, center.y - a.box.bottom))
        expect(gap, `"${a.text}" covers atom ${index + 1}`).toBeGreaterThan(outline * scale - 0.5)
      })
      // Each tag stays beside what it labels.
      expect(Math.hypot(a.box.x - a.anchor.x, a.box.y - a.anchor.y), `"${a.text}" drifted`).toBeLessThan(outline * scale + 75)
    })
    return boxes.map(item => item.text)
  }
  // An fcc Cu triangle seen at the default camera: all pairs are 2.556 Å apart, the angle is 60°.
  const half = 3.615 / 2
  const triangle = [{ x: 0, y: 0, z: 0 }, { x: 0, y: half, z: half }, { x: half, y: 0, z: half }]

  it("keeps three-atom distance, angle and atom-number tags apart", () => {
    const fake = fakeViewer(camera(33))
    drawCifMeasurement(fake.viewer as unknown as GLViewer, triangle)
    expect(expectReadable(fake, triangle, 33)).toEqual(["1", "2", "2.556 Å", "3", "2.556 Å", "∠ 60.00°"])
  })

  it("lays tags out again after the camera rotates or zooms, then stops redrawing", () => {
    const fake = fakeViewer(camera(33))
    const dispose = drawCifMeasurement(fake.viewer as unknown as GLViewer, triangle)
    for (const [scale, turn] of [[24, 0.7], [80, -0.4], [33, 1.3]]) {
      fake.rotate(camera(scale, turn))
      flushFrames()
      expectReadable(fake, triangle, scale)
      // The redraw reports a view change too; a settled layout must not redraw again.
      fake.callback()?.([])
      fake.viewer.render.mockClear()
      flushFrames()
      expect(fake.viewer.render).not.toHaveBeenCalled()
    }
    dispose()
    expect(fake.viewer.setViewChangeCallback).toHaveBeenLastCalledWith(null)
    expect(fake.labels).toEqual([])
  })

  it("keeps a two-atom distance clear of both numbered atoms", () => {
    const fake = fakeViewer(camera(33))
    drawCifMeasurement(fake.viewer as unknown as GLViewer, triangle.slice(0, 2))
    expect(expectReadable(fake, triangle.slice(0, 2), 33)).toEqual(["1", "2", "2.556 Å"])
  })
})
