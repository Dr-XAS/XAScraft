import type { AtomSpec, GLViewer, LabelSpec } from "3dmol"

type Point = { x: number; y: number; z: number }
export const measurementDistance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z)

/** Angle ABC, with B as the vertex, in the displayed Cartesian coordinates. */
export function measurementAngle(a: Point, b: Point, c: Point): number | null {
  const ab = measurementDistance(a, b)
  const cb = measurementDistance(c, b)
  if (ab < 1e-8 || cb < 1e-8) return null
  const cosine = ((a.x - b.x) * (c.x - b.x) + (a.y - b.y) * (c.y - b.y) + (a.z - b.z) * (c.z - b.z)) / (ab * cb)
  return Math.acos(Math.max(-1, Math.min(1, cosine))) * 180 / Math.PI
}

const SELECTION_RADIUS = 0.62

function selectionOutline(viewer: GLViewer, center: Point, color: string) {
  const vertexArr: Point[] = [], normalArr: Point[] = [], faceArr: number[] = []
  const rings = 16, segments = 32, radius = SELECTION_RADIUS
  for (let ring = 0; ring <= rings; ring++) {
    const theta = Math.PI * ring / rings
    for (let segment = 0; segment <= segments; segment++) {
      const phi = 2 * Math.PI * segment / segments
      const x = Math.sin(theta) * Math.cos(phi), y = Math.cos(theta), z = Math.sin(theta) * Math.sin(phi)
      vertexArr.push({ x: center.x + radius * x, y: center.y + radius * y, z: center.z + radius * z })
      // Light the inside of the shell: its back faces form the visible rim.
      normalArr.push({ x: -x, y: -y, z: -z })
      if (ring < rings && segment < segments) {
        const a = ring * (segments + 1) + segment, b = a + segments + 1
        faceArr.push(a, a + 1, b, a + 1, b + 1, b)
      }
    }
  }
  // BackSide = 1. The original atom hides the rear shell, preserving its color.
  return viewer.addCustom({ vertexArr, normalArr, faceArr, color, opacity: 1, side: 1 })
}

type Screen = { x: number; y: number }
type Box = { left: number; top: number; right: number; bottom: number }
/** A tag in CSS pixels: the side it prefers, and how far its near edge must stay from its anchor. */
export type MeasurementLabelRequest = { anchor: Screen; width: number; height: number; direction: Screen; clearance: number }

const DIRECTIONS = Array.from({ length: 16 }, (_, index) => ({ x: Math.cos(index * Math.PI / 8), y: Math.sin(index * Math.PI / 8) }))
const unit = (vector: Screen) => {
  const length = Math.hypot(vector.x, vector.y)
  return length > 1e-6 ? { x: vector.x / length, y: vector.y / length } : null
}
// How far a candidate must move to clear a placed tag or a selected atom.
function boxDepth(a: Box, b: Box) {
  const x = Math.min(a.right, b.right) - Math.max(a.left, b.left), y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return x > 0 && y > 0 ? Math.min(x, y) : 0
}
function discDepth(box: Box, disc: Screen & { radius: number }) {
  const dx = Math.max(box.left - disc.x, 0, disc.x - box.right), dy = Math.max(box.top - disc.y, 0, disc.y - box.bottom)
  return Math.max(0, disc.radius - Math.hypot(dx, dy))
}

/** Tag centers in request order: each beside its anchor, clear of the tags placed before
 * it and of the selected atoms, or the least covered spot when nothing nearby is clear.
 */
export function layoutMeasurementLabels(requests: MeasurementLabelRequest[], atoms: (Screen & { radius: number })[]) {
  const placed: Box[] = []
  return requests.map(request => {
    const preferred = unit(request.direction) ?? { x: 0, y: -1 }
    let best = { center: request.anchor, depth: Infinity, cost: Infinity }
    for (let step = 0; step < 16; step++) {
      const reach = request.clearance + 3 * step
      for (const direction of DIRECTIONS) {
        // Put the tag's near edge `reach` pixels out along this direction.
        const extent = Math.abs(direction.x) * request.width / 2 + Math.abs(direction.y) * request.height / 2
        const center = { x: request.anchor.x + direction.x * (reach + extent), y: request.anchor.y + direction.y * (reach + extent) }
        const box = { left: center.x - request.width / 2 - 1, right: center.x + request.width / 2 + 1, top: center.y - request.height / 2 - 1, bottom: center.y + request.height / 2 + 1 }
        const depth = placed.reduce((sum, other) => sum + boxDepth(box, other), 0) + atoms.reduce((sum, atom) => sum + discDepth(box, atom), 0)
        const cost = reach + 10 * Math.acos(Math.max(-1, Math.min(1, direction.x * preferred.x + direction.y * preferred.y)))
        if (depth < best.depth - 1e-6 || (depth <= best.depth + 1e-6 && cost < best.cost)) best = { center, depth, cost }
      }
    }
    placed.push({ left: best.center.x - request.width / 2, right: best.center.x + request.width / 2, top: best.center.y - request.height / 2, bottom: best.center.y + request.height / 2 })
    return best.center
  })
}

/** Own only measurement objects: hover and the structure keep their own lifetimes. */
export function drawCifMeasurement(viewer: GLViewer, atoms: Point[]) {
  type Tag = { label: ReturnType<GLViewer["addLabel"]>; position: Point; rank: number; direction: (screen: Screen[]) => Screen; clearance: (radius: number[]) => number }
  const tags: Tag[] = []
  const shapes: ReturnType<GLViewer["addSphere"]>[] = []
  const color = "#7c3aed"
  const tag = (text: string, position: Point, rank: number, direction: Tag["direction"], clearance: Tag["clearance"]) => tags.push({
    label: viewer.addLabel(text, {
      position, fontSize: 12, fontColor: "white", backgroundColor: color, backgroundOpacity: 0.95, inFront: true,
      alignment: "center", screenOffset: { x: 0, y: 0 } as NonNullable<LabelSpec["screenOffset"]>,
    }), position, rank, direction, clearance,
  })
  const toward = (from: Screen, to: Screen) => ({ x: to.x - from.x, y: to.y - from.y })
  atoms.forEach((atom, index) => {
    shapes.push(selectionOutline(viewer, atom, color))
    // Atom numbers point away from the middle of the selection.
    tag(String(index + 1), atom, 0, screen => toward({
      x: screen.reduce((sum, point) => sum + point.x, 0) / screen.length, y: screen.reduce((sum, point) => sum + point.y, 0) / screen.length,
    }, screen[index]), radius => radius[index] + 2)
    if (index === 0) return
    const previous = atoms[index - 1]
    shapes.push(viewer.addLine({ start: previous, end: atom, color, dashed: true }))
    // Distances sit off their line, on the side away from the third atom (or above it).
    tag(`${measurementDistance(previous, atom).toFixed(3)} Å`, {
      x: (previous.x + atom.x) / 2, y: (previous.y + atom.y) / 2, z: (previous.z + atom.z) / 2,
    }, 2, screen => {
      const start = screen[index - 1], end = screen[index], normal = { x: start.y - end.y, y: end.x - start.x }
      const other = atoms.length === 3 ? screen[index === 1 ? 2 : 0] : null
      const side = other ? (other.x - start.x) * normal.x + (other.y - start.y) * normal.y : normal.y || -normal.x
      return side > 0 ? { x: -normal.x, y: -normal.y } : normal
    }, () => 3)
  })
  if (atoms.length === 3) {
    const angle = measurementAngle(atoms[0], atoms[1], atoms[2])
    // The angle sits inside its arms, past the vertex atom.
    if (angle !== null) tag(`∠ ${angle.toFixed(2)}°`, atoms[1], 1, screen => {
      const [a, c] = [toward(screen[1], screen[0]), toward(screen[1], screen[2])].map(arm => unit(arm) ?? { x: 0, y: 0 })
      return { x: a.x + c.x, y: a.y + c.y }
    }, radius => radius[1] + 2)
  }
  // 3Dmol draws tags at a fixed pixel size, so they are laid out on screen. Offsets point up.
  const layout = () => {
    const screen: Screen[] = viewer.modelToScreen(atoms)
    const radius = atoms.map((atom, index) => Math.max(...[[1, 0, 0], [0, 1, 0], [0, 0, 1]].map(([x, y, z]) => {
      const [edge]: Screen[] = viewer.modelToScreen([{ x: atom.x + SELECTION_RADIUS * x, y: atom.y + SELECTION_RADIUS * y, z: atom.z + SELECTION_RADIUS * z }])
      return Math.hypot(edge.x - screen[index].x, edge.y - screen[index].y)
    })))
    const anchors: Screen[] = viewer.modelToScreen(tags.map(item => item.position))
    const order = tags.map((_, index) => index).sort((a, b) => tags[a].rank - tags[b].rank)
    const centers = layoutMeasurementLabels(order.map(index => ({
      anchor: anchors[index], width: tags[index].label.canvas.width, height: tags[index].label.canvas.height,
      direction: tags[index].direction(screen), clearance: tags[index].clearance(radius),
    })), screen.map((point, index) => ({ ...point, radius: radius[index] })))
    let moved = false
    order.forEach((index, position) => {
      const offset = tags[index].label.sprite.material?.screenOffset
      const x = centers[position].x - anchors[index].x, y = anchors[index].y - centers[position].y
      if (!offset || (Math.abs(offset.x - x) < 0.5 && Math.abs(offset.y - y) < 0.5)) return
      offset.x = x
      offset.y = y
      moved = true
    })
    return moved
  }
  layout()
  viewer.render()
  let frame = 0
  // Every render reports a view change; only a tag that moved needs another render.
  viewer.setViewChangeCallback(() => {
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; if (layout()) viewer.render() })
  })
  return () => {
    if (frame) cancelAnimationFrame(frame)
    viewer.setViewChangeCallback(null)
    tags.forEach(item => viewer.removeLabel(item.label))
    shapes.forEach(item => viewer.removeShape(item))
    viewer.render()
  }
}

/** Tolerate hand jitter without confusing a drag, pinch, or long press with a pick.
 * Hoverable atoms already have picking geometry; no native click callbacks are
 * registered, so compatibility mouse/touch events cannot pick a second time.
 */
export function bindCifAtomPicking(host: HTMLElement, viewer: GLViewer, atoms: AtomSpec[], onPick: (index: number) => void) {
  const pointers = new Set<number>()
  let gesture: { id: number; x: number; y: number; time: number; view: ReturnType<GLViewer["getView"]> } | null = null
  const cancel = () => { gesture = null }
  const reset = () => { cancel(); pointers.clear() }
  const down = (event: PointerEvent) => {
    pointers.add(event.pointerId)
    if (pointers.size !== 1 || event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) { cancel(); return }
    gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, time: event.timeStamp, view: viewer.getView() }
  }
  const move = (event: PointerEvent) => {
    if (gesture?.id === event.pointerId && Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 4) cancel()
  }
  const up = (event: PointerEvent) => {
    const start = gesture
    pointers.delete(event.pointerId)
    cancel()
    if (!start || start.id !== event.pointerId || event.timeStamp - start.time > 750 ||
      Math.hypot(event.clientX - start.x, event.clientY - start.y) > 4 || !host.contains(event.target as Node)) return
    const rect = host.getBoundingClientRect()
    if (!rect.width || !rect.height || event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) return
    // 3Dmol may have rotated slightly during a sub-threshold movement.
    viewer.setView(start.view)
    const hit = viewer.targetedObjects(2 * (event.clientX - rect.left) / rect.width - 1, 1 - 2 * (event.clientY - rect.top) / rect.height, atoms)[0]?.clickable as AtomSpec | undefined
    if (hit?.index !== undefined) onPick(hit.index)
  }
  const cancelled = (event: PointerEvent) => { pointers.delete(event.pointerId); cancel() }
  host.addEventListener("pointerdown", down)
  host.addEventListener("pointerleave", cancel)
  host.addEventListener("wheel", cancel)
  window.addEventListener("pointermove", move)
  window.addEventListener("pointerup", up)
  window.addEventListener("pointercancel", cancelled)
  window.addEventListener("blur", reset)
  return () => {
    reset()
    host.removeEventListener("pointerdown", down)
    host.removeEventListener("pointerleave", cancel)
    host.removeEventListener("wheel", cancel)
    window.removeEventListener("pointermove", move)
    window.removeEventListener("pointerup", up)
    window.removeEventListener("pointercancel", cancelled)
    window.removeEventListener("blur", reset)
  }
}
