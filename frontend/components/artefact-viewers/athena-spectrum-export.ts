import type { AthenaGroup } from "@/lib/athena"
import type { PlotSpace } from "./athena-plot-range"

const columns = {
  E: ["mu", "norm", "flat", "dmude", "d2mude", "pre_edge", "post_edge", "bkg"],
  k: ["chi", "weighted_chi", "kwin"],
  R: ["chir_re", "chir_im", "chir_mag", "chir_pha", "rwin"],
  q: ["chiq_re", "chiq_im", "chiq_mag", "chiq_pha"],
} as const

function csvCell(value: string | number) {
  const text = String(value)
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

/** Keep each spectrum's own grid and numeric arrays, without viewer scaling or clipping. */
export function spectrumDataCsv(groups: readonly AthenaGroup[], space: PlotSpace, kWeight: number | null = null) {
  const axis = { E: "energy_eV", k: "k_A^-1", R: "R_A", q: "q_A^-1" }[space]
  const axisKey = { E: "energy", k: "k", R: "r", q: "q" }[space]
  const lines = [
    "# Spectrum arrays; display offsets, multipliers and axis limits are not applied.",
    ...(space === "E" ? ["# Energy includes the saved energy shift."] : []),
    ...(space === "R" ? ["# R is not phase corrected; complex phase is in radians."] : []),
    ["data_id", "data_label", "data_type", "kweight", "energy_shift_eV", axis, ...columns[space]].join(","),
  ]
  for (const group of groups) {
    if (group.data_type === "detector" && space !== "E") continue
    const rawChi = group.data_type === "chi" && !group.result
    const arrays: Record<string, number[]> = group.result?.arrays ?? (rawChi
      ? { k: group.energy, chi: group.mu }
      : { energy: group.energy.map(value => value + group.parameters.energy_shift), mu: group.mu })
    const x = arrays[axisKey]
    if (!x?.length) continue
    const effectiveWeight = group.result?.effective.kweight
    const weight = space === "E" ? "" : kWeight ?? (rawChi ? 0 : typeof effectiveWeight === "number" ? effectiveWeight : group.parameters.kweight)
    const values = columns[space].map(key => {
      if (space === "k" && key === "weighted_chi" && arrays.chi?.length === x.length) {
        return arrays.chi.map((value, index) => value * x[index] ** Number(weight))
      }
      return arrays[key]?.length === x.length ? arrays[key] : undefined
    })
    if (!values.some(Boolean)) continue
    x.forEach((coordinate, index) => {
      lines.push([group.id, group.label, group.data_type, weight, group.parameters.energy_shift, coordinate,
        ...values.map(value => value && Number.isFinite(value[index]) ? value[index] : ""),
      ].map(csvCell).join(","))
    })
  }
  return `${lines.join("\n")}\n`
}
