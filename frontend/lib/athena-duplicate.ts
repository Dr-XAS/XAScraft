import type { AthenaGroup, AthenaProject } from "./athena"

/** Duplicate returns project metadata plus only the newly created spectra. */
export interface AthenaDuplicateUpdate extends AthenaProject {
  kind: "duplicate"
  base_version: number
  group_order: string[]
  group_versions: NonNullable<AthenaProject["group_versions"]>
}

/** Keep existing data identities so duplicating does not invalidate their plots. */
export function mergeDuplicateUpdate(project: AthenaProject, update: AthenaDuplicateUpdate): AthenaProject {
  const invalid = (): never => { throw new Error("The duplicate response does not match this project. Reload the project before editing.") }
  if (update.kind !== "duplicate" || update.id !== project.id || update.base_version !== project.version ||
    update.version !== project.version + 1 || typeof update.name !== "string" || typeof update.updated !== "string" ||
    typeof update.journal !== "string" || !Array.isArray(update.groups) || !Array.isArray(update.group_order) ||
    !Array.isArray(update.undo) || !update.undo.every(item => typeof item === "string") ||
    !Array.isArray(update.redo) || !update.redo.every(item => typeof item === "string") ||
    !Array.isArray(update.history) || !update.history.every(item => item && typeof item.time === "string" && typeof item.message === "string") ||
    !Array.isArray(update.analyses) || !update.group_versions || typeof update.group_versions !== "object" ||
    update.last_operation?.action !== "duplicate" || !Array.isArray(update.last_operation.skipped_group_ids)) return invalid()

  const existing = new Map(project.groups.map(group => [group.id, group]))
  const all = new Map(existing)
  for (const group of update.groups) {
    if (!group || typeof group.id !== "string" || !group.id || all.has(group.id) ||
      typeof group.label !== "string" || !Array.isArray(group.energy) || !Array.isArray(group.mu) ||
      !group.parameters || !group.source || typeof group.marked !== "boolean" || typeof group.frozen !== "boolean" ||
      update.group_versions[group.id] !== update.version) return invalid()
    all.set(group.id, group)
  }
  if (update.group_order.length !== all.size || new Set(update.group_order).size !== all.size) return invalid()
  const groups: AthenaGroup[] = update.group_order.map(id => {
    const group = all.get(id)
    const revision = update.group_versions[id]
    if (!group || !Number.isInteger(revision) || revision < 0 || revision > update.version ||
      (existing.has(id) && project.group_versions?.[id] !== undefined && revision !== project.group_versions[id])) return invalid()
    return group
  })
  // Only new entries may be inserted; duplicate cannot remove or reorder its sources.
  if (groups.filter(group => existing.has(group.id)).some((group, index) => group !== project.groups[index])) return invalid()
  const { kind, base_version, group_order, ...saved } = update
  return { ...project, ...saved, groups }
}
