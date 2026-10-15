import { describe, expect, it } from "vitest"
import type { AthenaGroup, Parameters } from "@/lib/athena"
import { spectrumDataCsv } from "./athena-spectrum-export"

function group(overrides: Partial<AthenaGroup> = {}): AthenaGroup {
  return {
    id: "sample", label: 'Sample, "one"', data_type: "mu", energy: [100, 101], mu: [2, 4],
    marked: true, frozen: false, multiplier: 8, offset: 20, notes: "", reference_id: null,
    parameters: { energy_shift: 3, kweight: 2 } as Parameters,
    result: { arrays: { energy: [103, 104], mu: [2, 4], norm: [0.2, 0.4] }, effective: { kweight: 3 }, warnings: [] },
    processing_error: null, source: {}, ...overrides,
  }
}

describe("spectrumDataCsv", () => {
  it("retains independent energy grids, shifted axes and unscaled values with escaped labels", () => {
    const first = group()
    const second = group({ id: "raw", label: "Raw", result: null, energy: [200, 201, 202], mu: [5, 6, 7] })
    const before = JSON.stringify([first, second])
    const csv = spectrumDataCsv([first, second], "E")
    expect(csv).toContain('sample,"Sample, ""one""",mu,,3,103,2,0.2,')
    expect(csv).toContain("raw,Raw,mu,,3,203,5,")
    expect(csv).toContain("raw,Raw,mu,,3,205,7,")
    expect(csv).toContain("energy_eV,mu,norm,flat")
    expect(JSON.stringify([first, second])).toBe(before)
  })

  it("exports unweighted and viewer-weighted chi without changing saved arrays", () => {
    const sample = group({ result: {
      arrays: { k: [1, 2], chi: [0.5, -0.25], weighted_chi: [0.5, -2], kwin: [0.2, 1] },
      effective: { kweight: 3 }, warnings: [],
    } })
    const csv = spectrumDataCsv([sample], "k", 2)
    expect(csv).toContain('mu,2,3,1,0.5,0.5,0.2')
    expect(csv).toContain('mu,2,3,2,-0.25,-1,1')
    expect(sample.result?.arrays.weighted_chi).toEqual([0.5, -2])
    expect(spectrumDataCsv([sample], "k")).toContain('mu,3,3,2,-0.25,-2,1')
  })

  it("retains raw chi and every Fourier component without double weighting", () => {
    const raw = group({ data_type: "chi", result: null, energy: [1, 2], mu: [0.5, -0.25] })
    expect(spectrumDataCsv([raw], "k")).toContain('chi,0,3,2,-0.25,-0.25,')
    const transformed = group({ result: {
      arrays: { r: [0, 1], chir_re: [3, 0], chir_im: [4, 5], chir_mag: [5, 5], chir_pha: [0.2, 1], rwin: [0, 1] },
      effective: { kweight: 1 }, warnings: [],
    } })
    const csv = spectrumDataCsv([transformed], "R", 1)
    expect(csv).toContain("# R is not phase corrected")
    expect(csv).toContain('mu,1,3,0,3,4,5,0.2,0')
    expect(csv).toContain('mu,1,3,1,0,5,5,1,1')
  })
})
