import { describe, expect, it } from "vitest"
import type { AthenaGroup, AthenaProject } from "./athena"
import { mergeDuplicateUpdate, type AthenaDuplicateUpdate } from "./athena-duplicate"

function group(id: string): AthenaGroup {
  return {
    id, label: id, data_type: "mu", marked: true, frozen: false, energy: [10, 20], mu: [0, 1],
    multiplier: 1, offset: 0, notes: "", reference_id: null, processing_error: null, source: {},
    parameters: { e0: 15, step: null, pre1: null, pre2: null, norm1: null, norm2: null, nnorm: null,
      flatten: true, rbkg: 1, bkg_kmin: 0, bkg_kmax: null, bkg_kweight: 2, clamp_lo: 0, clamp_hi: 1,
      kmin: 0, kmax: 3, kweight: 2, dk: 1, window: "hanning", rmin: 1, rmax: 3, dr: 0,
      rwindow: "hanning", energy_shift: 0, nfft: 2048, kstep: 0.05 },
    result: { arrays: { energy: [10, 20], norm: [0, 1] }, effective: { e0: 15 }, warnings: [] },
  }
}

function fixture() {
  const project: AthenaProject = { id: "p", name: "Copper", version: 7, updated: "before", journal: "notes",
    groups: [group("a"), group("b")], group_versions: { a: 5, b: 7 }, group_added_orders: { a: 0, b: 1 },
    group_folders: [{ id: "folder", name: "Series", group_ids: ["a", "b"] }], undo: [], redo: ["next"], history: [], analyses: [] }
  const update: AthenaDuplicateUpdate = { ...project, kind: "duplicate", base_version: 7, version: 8, updated: "after",
    groups: [group("copy")], group_order: ["a", "copy", "b"], group_versions: { a: 5, b: 7, copy: 8 },
    group_added_orders: { a: 0, b: 1, copy: 2 }, group_folders: [{ id: "folder", name: "Series", group_ids: ["a", "copy", "b"] }],
    undo: ["duplicate"], redo: [], history: [{ time: "after", message: "Duplicate" }],
    last_operation: { action: "duplicate", skipped_group_ids: [] } }
  return { project, update }
}

describe("mergeDuplicateUpdate", () => {
  it("inserts new data beside its source while preserving every existing object and the server metadata", () => {
    const { project, update } = fixture()
    const before = JSON.stringify(project)
    const next = mergeDuplicateUpdate(project, update)
    expect(next.groups.map(item => item.id)).toEqual(["a", "copy", "b"])
    expect(next.groups[0]).toBe(project.groups[0])
    expect(next.groups[2]).toBe(project.groups[1])
    expect(next.groups[1]).toBe(update.groups[0])
    expect(next.groups[0].result?.arrays).toBe(project.groups[0].result?.arrays)
    expect(next).toMatchObject({ version: 8, group_versions: update.group_versions, group_added_orders: update.group_added_orders,
      group_folders: update.group_folders, undo: ["duplicate"], redo: [], history: update.history })
    expect(next).not.toHaveProperty("kind")
    expect(next).not.toHaveProperty("base_version")
    expect(next).not.toHaveProperty("group_order")
    expect(JSON.stringify(project)).toBe(before)
  })

  it.each([
    ["project", { id: "other" }], ["base version", { base_version: 6 }], ["next version", { version: 9 }],
    ["missing source", { group_order: ["a", "copy"] }], ["unknown source", { group_order: ["a", "copy", "unknown"] }],
    ["duplicate order", { group_order: ["a", "copy", "copy"] }], ["reordered originals", { group_order: ["b", "copy", "a"] }],
    ["changed original revision", { group_versions: { a: 8, b: 7, copy: 8 } }],
    ["stale duplicate revision", { group_versions: { a: 5, b: 7, copy: 7 } }],
    ["wrong action", { last_operation: { action: "parameters", skipped_group_ids: [] } }],
    ["replacement source", { groups: [group("a")] }],
    ["duplicate payload", { groups: [group("copy"), group("copy")] }],
  ] satisfies [string, Partial<AthenaDuplicateUpdate>][]) ("rejects a mismatched %s without changing the project", (_, patch) => {
    const { project, update } = fixture()
    const before = JSON.stringify(project)
    expect(() => mergeDuplicateUpdate(project, { ...update, ...patch })).toThrow(/does not match/)
    expect(JSON.stringify(project)).toBe(before)
  })
})
