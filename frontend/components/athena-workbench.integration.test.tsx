import "@testing-library/jest-dom/vitest"

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest"
import type { AthenaProject, Parameters } from "@/lib/athena"
import { AthenaProvider } from "@/lib/athena-context"
import { AthenaPointEdit } from "./athena-point-edit"
import { AthenaProjectImport, type ProjectPreview } from "./athena-project-import"
import { AthenaWorkbench } from "./athena-workbench"

vi.mock("next/dynamic", () => ({ default: () => () => null }))

const parameters: Parameters = {
  e0: 8979, step: null, pre1: -150, pre2: -30, norm1: 100, norm2: 300,
  nnorm: 2, flatten: true, rbkg: 1, bkg_kmin: 0, bkg_kmax: null,
  bkg_kweight: 2, clamp_lo: 0, clamp_hi: 1, kmin: 3, kmax: 12,
  kweight: 2, dk: 1, window: "hanning", rmin: 1, rmax: 3, dr: 0,
  rwindow: "hanning", energy_shift: 0, nfft: 2048, kstep: 0.05,
}

function eligibleProject(): AthenaProject {
  return {
    id: "integrated-project", name: "Read only", version: 7, journal: "",
    updated: "2026-09-16T00:00:00Z", undo: [], redo: [], history: [],
    groups: [{
      id: "sample", label: "EXAFS sample", marked: true, frozen: false,
      data_type: "mu", energy: [8960, 8980, 9000], mu: [0.1, 0.8, 1.1],
      multiplier: 1, offset: 0, notes: "", reference_id: null,
      parameters: { ...parameters }, processing_error: null, source: {},
      result: {
        arrays: {
          energy: [8960, 8980, 9000], norm: [0, 0.7, 1],
          k: [0, 1, 2, 3], chi: [0, 2, -1, 1], r: [0, 1, 2],
          chir_mag: [2, 3, 2], chir_re: [1, 1, 1], chir_im: [1, 2, 1], chir_pha: [0, 1, 2],
        },
        effective: { e0: 8979, edge_step: 1, kweight: 2 }, warnings: [],
      },
    }],
  }
}

function pointEditPreview(project: AthenaProject, body: string) {
  const request = JSON.parse(body) as { options: { mode: string, scope: string } }
  const group = project.groups[0]
  const removed = request.options.mode === "inspect" ? [] : [1]
  const kept = group.energy.map((_, index) => index).filter(index => !removed.includes(index))
  return {
    project_id: project.id, version: project.version, options: request.options,
    skipped_reasons: {}, changed_group_ids: removed.length ? [group.id] : [],
    results: [{
      group_id: group.id, label: group.label, kept_indices: kept, removed_indices: removed,
      energy: kept.map(index => group.energy[index]), mu: kept.map(index => group.mu[index]),
      selected_energy: removed.map(index => group.energy[index]), selected_mu: removed.map(index => group.mu[index]),
      input_points: group.energy.length, output_points: kept.length, snapped: null, processing_error: null, margins: null,
      original: { mu: { x: group.energy, y: group.mu }, chie: null },
      modified: { mu: { x: kept.map(index => group.energy[index]), y: kept.map(index => group.mu[index]) }, chie: null },
      selected_chie: null,
    }],
  }
}

const pointEditSession = {
  mode: "integration" as const, projectId: "integrated-project", capability: "point-edit-capability",
  allowedOperations: ["preview"], expiresAt: "2099-01-01T00:00:00Z",
}

function pointEdit(project: AthenaProject, allowedActions: { preview: boolean, deglitch: boolean, truncate: boolean, undo: boolean, redo: boolean }) {
  return <AthenaPointEdit project={project} activeId="sample" selectGroup={vi.fn()} initialMode="point" rememberDraft={vi.fn()}
    setBusy={vi.fn()} disabled={false} allowedActions={allowedActions} saved={vi.fn()} close={vi.fn()} />
}

function attemptDisabledAction(name: string) {
  const button = screen.getByRole("button", { name })
  button.removeAttribute("disabled")
  fireEvent.click(button)
}

// jsdom has no <dialog> modal API.
function stubShowModal() {
  const showModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal")
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, writable: true, value(this: HTMLDialogElement) { this.setAttribute("open", "") } })
  onTestFinished(() => {
    if (showModal) Object.defineProperty(HTMLDialogElement.prototype, "showModal", showModal)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal")
  })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("AthenaWorkbench integrated request gating", () => {
  it("issues only the initial project GET for a read-project-only EXAFS session", async () => {
    const project = eligibleProject()
    project.groups.push({ ...project.groups[0], id: "second-sample", label: "Second EXAFS sample" })
    const fetcher = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith("/api/athena/projects/integrated-project")) {
        return new Response(JSON.stringify(project), {
          headers: { "content-type": "application/json" },
        })
      }
      return new Response(JSON.stringify({ error: { message: `Unexpected request: ${url}` } }), {
        status: 404, headers: { "content-type": "application/json" },
      })
    })
    vi.stubGlobal("fetch", fetcher)

    render(<AthenaWorkbench session={{
      mode: "integration", projectId: "integrated-project", capability: "read-only-capability",
      allowedOperations: ["read_project"], expiresAt: "2099-01-01T00:00:00Z",
    }} />)

    await screen.findAllByRole("button", { name: /EXAFS sample/ })
    for (const name of ["Single spectrum viewer", "Multiple spectra viewer"]) {
      fireEvent.click(within(screen.getByRole("region", { name })).getByRole("tab", { name: /Fourier/ }))
    }
    for (const name of ["Single spectrum k-weight", "Multiple spectra k-weight", "Wavelet k-weight"]) {
      const viewerWeight = screen.getByRole("combobox", { name })
      expect(viewerWeight).toBeDisabled()
    }
    await new Promise(resolve => window.setTimeout(resolve, 250))

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    expect(fetcher.mock.calls[0][0]).toBe("/api/backend/api/athena/projects/integrated-project")
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "GET" })
    expect((fetcher.mock.calls[0][1]?.headers as Headers).get("x-xraylarch-project-capability")).toBe("read-only-capability")
  })

  it("keeps ordinary raw import available without restore", async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/athena/projects/integrated-project")) return new Response(JSON.stringify(eligibleProject()))
      return new Response(JSON.stringify({ detail: "unexpected" }), { status: 404 })
    })
    vi.stubGlobal("fetch", fetcher)
    render(<AthenaWorkbench session={{
      mode: "integration", projectId: "integrated-project", capability: "raw-import", allowedOperations: ["read_project", "upload", "preview", "read_upload", "import"], expiresAt: "2099-01-01T00:00:00Z",
    }} />)
    await screen.findAllByRole("button", { name: /EXAFS sample/ })
    expect(screen.getByRole("button", { name: "Import spectra" })).toBeEnabled()
  })

  it("opens a project file into the bound project, never offering a new or recent one", async () => {
    const preview: ProjectPreview = {
      upload_id: "upload-project", filename: "export.json", name: "Exported project", journal: "",
      warnings: [], groups: [{ id: "source", label: "Source", data_type: "mu", points: 3,
        x: [1, 2, 3], y: [1, 2, 3], notes: "", reference_id: null }],
    }
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith("/api/athena/projects/integrated-project")) return new Response(JSON.stringify(eligibleProject()))
      if (url.endsWith("/api/athena/projects/integrated-project/preview-project")) return new Response(JSON.stringify(preview))
      return new Response(JSON.stringify({ detail: "unexpected" }), { status: 404 })
    })
    vi.stubGlobal("fetch", fetcher)
    stubShowModal()
    render(<AthenaWorkbench session={{
      mode: "integration", projectId: "integrated-project", capability: "restore",
      allowedOperations: ["read_project", "upload", "preview", "read_upload", "import", "restore"], expiresAt: "2099-01-01T00:00:00Z",
    }} />)
    await screen.findAllByRole("button", { name: /EXAFS sample/ })
    fireEvent.click(screen.getByRole("button", { name: "Import spectra" }))
    fireEvent.change(screen.getByLabelText("Choose data files"), { target: { files: [new File(["{}"], "export.json")] } })

    expect(await screen.findByRole("button", { name: "Import all data" })).toBeEnabled()
    expect(screen.getByLabelText("Destination project")).toHaveTextContent("added to the open project")
    expect(screen.queryByLabelText("Open in a new project instead")).not.toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Recent local projects" })).not.toBeInTheDocument()
  })

  it("merges marked repeat scans and leaves out the tools a linked project cannot run", async () => {
    const project = eligibleProject()
    project.groups.push({ ...project.groups[0], id: "second-sample", label: "Second EXAFS sample" })
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/athena/projects/integrated-project")) return new Response(JSON.stringify(project))
      return new Response(JSON.stringify({ detail: "unexpected" }), { status: 404 })
    })
    vi.stubGlobal("fetch", fetcher)
    stubShowModal()
    render(<AthenaWorkbench session={{
      mode: "integration", projectId: "integrated-project", capability: "merge",
      allowedOperations: ["read_project", "preview", "merge"], expiresAt: "2099-01-01T00:00:00Z",
    }} />)
    await screen.findAllByRole("button", { name: /EXAFS sample/ })
    fireEvent.click(screen.getByRole("button", { name: "Process" }))
    for (const name of ["Dispersive energy calibration", "Fluorescence XAS from XRF fit", "Raw XRF spectra and maps"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument()
    }
    const merge = screen.getByRole("button", { name: "Merge marked data" })
    expect(merge).toBeEnabled()
    fireEvent.click(merge)

    await screen.findByRole("dialog", { name: "Merge marked data" })
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/api/athena/projects/integrated-project/merge/preview"))).toBe(true), { timeout: 2500 })
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("/api/athena/preferences/"))).toBe(false)
    expect(screen.queryByRole("button", { name: "Save merge defaults" })).not.toBeInTheDocument()
  })

  // Catches a dropped detector file opening an XRF panel the linked project cannot run.
  it("says why a detector file's spectra stay out of a linked project instead of opening an XRF panel", async () => {
    const columns = ["Energy", "I0", "It"].map((name, index) => ({ column_id: `col_${index}`, name, index, numeric: true, unit: null,
      role_hint: name === "Energy" ? "energy" : name === "I0" ? "i0" : null, preview: [1, 2, 3] }))
    const both = { upload_id: "upload-both", display_name: "both.0007.hdf5", row_count: 3, warnings: [], issues: [], columns,
      athena_suggestion: { energy_column: "col_0", numerator: ["col_1"], denominator: "col_2", mode: "transmission", units: "eV", data_type: "mu" },
      detector_file: { opens: "xrf_xas" } }
    const inspections = [{ kind: "xrf_detector_file", opens: "xrf_xas", display_name: "scan.0029.hdf5" }, both]
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith("/api/athena/projects/integrated-project")) return new Response(JSON.stringify(eligibleProject()))
      if (url.endsWith("/api/athena/projects/integrated-project/inspect")) return new Response(JSON.stringify(inspections.shift()))
      return new Response(JSON.stringify({ detail: "unexpected" }), { status: 404 })
    })
    vi.stubGlobal("fetch", fetcher)
    stubShowModal()
    render(<AthenaWorkbench session={{
      mode: "integration", projectId: "integrated-project", capability: "raw-import",
      allowedOperations: ["read_project", "upload", "preview", "read_upload", "import"], expiresAt: "2099-01-01T00:00:00Z",
    }} />)
    await screen.findAllByRole("button", { name: /EXAFS sample/ })
    fireEvent.click(screen.getByRole("button", { name: "Import spectra" }))
    fireEvent.change(screen.getByLabelText("Choose data files"), { target: { files: [new File(["hdf"], "scan.0029.hdf5")] } })

    const dialog = await screen.findByRole("dialog", { name: "Import spectra" })
    const listed = await within(dialog).findByLabelText("Detector spectrum files in this batch")
    expect(listed).toHaveTextContent("scan.0029.hdf5 holds detector spectra rather than a table of columns. A project opened from Dr.XAS cannot fit detector spectra.")
    expect(within(listed).queryByRole("button")).not.toBeInTheDocument()
    expect(screen.queryByRole("dialog", { name: "Fluorescence XAS from XRF fit" })).not.toBeInTheDocument()

    fireEvent.change(within(dialog).getByLabelText("Choose data files"), { target: { files: [new File(["hdf"], "both.0007.hdf5")] } })
    await within(dialog).findByRole("combobox", { name: "Energy column" })
    const offer = within(dialog).getByLabelText("Detector spectra in this file")
    expect(offer).toHaveTextContent("both.0007.hdf5 also holds detector spectra. Its columns import here; a project opened from Dr.XAS cannot fit its spectra.")
    expect(within(offer).queryByRole("button")).not.toBeInTheDocument()
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("/xrf-"))).toBe(false)
  })

  it("keeps reviewed project restoration inert without restore", async () => {
    const project = eligibleProject()
    const preview: ProjectPreview = {
      upload_id: "upload-project", filename: "source.prj", name: "Source project", journal: "",
      warnings: [], groups: [{ id: "source", label: "Source", data_type: "mu", points: 3,
        x: [1, 2, 3], y: [1, 2, 3], notes: "", reference_id: null }],
    }
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ detail: "unexpected" }), { status: 404 }))
    render(<AthenaProvider session={{
      mode: "integration", projectId: project.id, capability: "no-restore", allowedOperations: ["upload", "read_upload"], expiresAt: "2099-01-01T00:00:00Z",
    }} fetcher={fetcher}><AthenaProjectImport getProject={() => project} onImported={vi.fn()} onComplete={vi.fn()} onBusyChange={vi.fn()}
      initialFiles={[new File(["project"], "source.prj")]} initialPreview={preview} canRestore={false} /></AthenaProvider>)

    const restore = await screen.findByRole("button", { name: "Import all data" })
    expect(restore).toBeDisabled()
    fireEvent.click(restore)
    expect(fetcher).not.toHaveBeenCalled()
  })

  it("does not send a point-edit preview through provider transport without preview", async () => {
    const project = eligibleProject()
    const fetcher = vi.fn()
    render(<AthenaProvider session={{ ...pointEditSession, allowedOperations: ["deglitch"] }} fetcher={fetcher}>
      {pointEdit(project, { preview: false, deglitch: true, truncate: false, undo: false, redo: false })}
    </AthenaProvider>)

    attemptDisabledAction("Refresh preview")
    await new Promise(resolve => window.setTimeout(resolve, 400))
    expect(fetcher).not.toHaveBeenCalled()
  })

  it("does not send a point-edit command through provider transport without the current mutation capability", async () => {
    const project = eligibleProject()
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify(pointEditPreview(project, String(init?.body)))))
    const rendered = render(<AthenaProvider session={pointEditSession} fetcher={fetcher}>
      {pointEdit(project, { preview: true, deglitch: true, truncate: false, undo: false, redo: false })}
    </AthenaProvider>)
    fireEvent.change(screen.getByLabelText("Point energy · eV", { exact: true }), { target: { value: "8980" } })
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove point" })).toBeEnabled())

    rendered.rerender(<AthenaProvider session={pointEditSession} fetcher={fetcher}>
      {pointEdit(project, { preview: true, deglitch: false, truncate: false, undo: false, redo: false })}
    </AthenaProvider>)
    attemptDisabledAction("Remove point")
    await new Promise(resolve => window.setTimeout(resolve, 50))
    expect(fetcher.mock.calls.filter(([input]) => String(input).endsWith("/command"))).toHaveLength(0)
  })

  it("does not send undo through provider transport without undo despite available history", async () => {
    const project = eligibleProject()
    project.undo = ["edit"]
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify(pointEditPreview(project, String(init?.body)))))
    render(<AthenaProvider session={pointEditSession} fetcher={fetcher}>
      {pointEdit(project, { preview: true, deglitch: true, truncate: false, undo: false, redo: false })}
    </AthenaProvider>)

    attemptDisabledAction("Undo last edit")
    await new Promise(resolve => window.setTimeout(resolve, 400))
    expect(fetcher.mock.calls.filter(([input]) => String(input).endsWith("/command"))).toHaveLength(0)
  })

  it("does not send redo through provider transport without redo despite available history", async () => {
    const project = eligibleProject()
    project.redo = ["edit"]
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify(pointEditPreview(project, String(init?.body)))))
    render(<AthenaProvider session={pointEditSession} fetcher={fetcher}>
      {pointEdit(project, { preview: true, deglitch: true, truncate: false, undo: false, redo: false })}
    </AthenaProvider>)

    attemptDisabledAction("Redo last edit")
    await new Promise(resolve => window.setTimeout(resolve, 400))
    expect(fetcher.mock.calls.filter(([input]) => String(input).endsWith("/command"))).toHaveLength(0)
  })
})
