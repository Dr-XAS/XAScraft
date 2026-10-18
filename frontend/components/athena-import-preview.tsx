"use client"

import { SectionHelp } from "./section-help"
import { ThemedPlot as Plot } from "./themed-plot"
import { useEffect, useState } from "react"
import { useAthenaApi } from "@/lib/athena-context"
import { columnPayload, columnProblem, type ColumnMapping, type ColumnPreview } from "@/lib/athena-import"
import styles from "./athena-column-selection.module.css"

const colors = ["#16736b", "#c37b38", "#7470b0", "#467cac", "#c85a65"]

export function AthenaImportPreview({ projectId, version, uploadId, mapping, disabled = false, automaticExafs = true }: {
  projectId: string; version: number; uploadId: string; mapping: ColumnMapping; disabled?: boolean; automaticExafs?: boolean
}) {
  const athenaApi = useAthenaApi()
  const [retry, setRetry] = useState(0)
  const [state, setState] = useState<{ key: string; value?: ColumnPreview; error?: string } | null>(null)
  const problem = columnProblem(mapping)
  const [showOriginal, setShowOriginal] = useState(true)
  const previewPayload = columnPayload(mapping, { automaticExafs })
  delete previewPayload.is_reference
  const key = JSON.stringify({ projectId, version, uploadId, mapping: previewPayload })
  useEffect(() => {
    if (disabled || problem) return
    const controller = new AbortController()
    let current = true
    const timeout = setTimeout(() => {
      void athenaApi<ColumnPreview>(`/projects/${projectId}/preview-columns`,
        { version, upload_id: uploadId, ...previewPayload }, "POST", controller.signal)
        .then(value => { if (current) setState({ key, value }) })
        .catch(error => { if (current) setState({ key, error: error instanceof Error ? error.message : "Column preview failed." }) })
    }, 180)
    return () => { current = false; clearTimeout(timeout); controller.abort() }
    // key contains the complete immutable request; changing any column cancels stale work.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, retry, disabled, problem])
  const isCurrent = state?.key === key
  const value = !problem && isCurrent ? state?.value : undefined
  const error = problem ?? (isCurrent ? state?.error : undefined)
  const referenceOnly = !!mapping.import_signals?.reference && !mapping.import_signals.transmission && !mapping.import_signals.fluorescence
  const traces = value?.traces.filter(t => showOriginal || t.stage !== 'original')
    .map(t => referenceOnly ? { ...t, label: 'Reference' } : t) ?? []
  const plottedReference = traces.some(t => t.role === "reference")
  return <section className={styles.previewPanel} aria-label="Column selection preview">
    <div className={styles.previewTools}><strong>Preview selected columns <SectionHelp label="Selected columns preview">The checked signals before normalization or background removal. Use the checkboxes beside the signal tabs to choose what to import and preview. Clicking a tab changes only the column editing panel.</SectionHelp></strong>
      {mapping.rebin?.enabled && <label className="ath-check"><input type="checkbox" checked={showOriginal} onChange={e => setShowOriginal(e.target.checked)} />Plot original data <SectionHelp label="Plot original data">Compare the unreduced signal with the rebinned preview to see whether the new grid preserves spectral features.</SectionHelp></label>}
    </div>
    <div className={styles.plot} aria-label="Imported signal preview plot" aria-busy={!isCurrent && !problem}>
      {value ? <Plot data={traces.map((trace, index) => ({ x: trace.x.slice(), y: trace.y.slice(), name: trace.label,
        type: "scatter", mode: "lines", opacity: trace.stage === 'original' ? .45 : 1,
        line: { color: trace.role === "reference" ? "#b96342" : colors[index % colors.length], dash: trace.role === "reference" ? "solid" : trace.stage === 'original' ? 'dot' : "solid", width: 1.8 },
        yaxis: trace.role === "reference" ? "y2" : "y", hovertemplate: "%{x:.4f}, %{y:.6g}<extra>%{fullData.name}</extra>" }))}
        layout={{ autosize: true, margin: { l: 60, r: plottedReference ? 60 : 25, t: traces.length > 1 ? 65 : 15, b: 60 },
          paper_bgcolor: "white", plot_bgcolor: "white", font: { color: "#43513d" },
          xaxis: { title: { text: value.x_label }, zeroline: false }, yaxis: { title: { text: value.y_label }, zeroline: false },
          yaxis2: { title: { text: "Reference" }, overlaying: "y", tickmode: "auto", side: "right", showgrid: false, zeroline: false },
          showlegend: traces.length > 1, legend: { orientation: "h", x: 0, y: 1.12, xanchor: "left", yanchor: "bottom" },
          uirevision: state?.key, hovermode: "closest" }}
        config={{ responsive: true, displaylogo: false, modeBarButtonsToRemove: ["select2d", "lasso2d"], toImageButtonOptions: { filename: "craft-column-preview" } }}
        style={{ width: "100%", height: "100%" }} useResizeHandler />
        : <p>{problem ? "Choose valid columns to preview." : error ? "Preview unavailable." : "Updating preview…"}</p>}
    </div>
    {error && <p role="alert" className="ath-error">{error}</p>}
    {error && !problem && <button type="button" disabled={disabled} onClick={() => { setRetry(n => n + 1); setState(null) }}>Retry preview</button>}
    {value && <p className="ath-hint">{value.points.toLocaleString()} source points{value.rebin_results ? " · rebinned spectra will be imported; original data are retained." : value.traces.some(t => t.x.length < value.points) ? " · display preserves local minima and maxima; every point is imported." : " · all points displayed."}</p>}
    {value?.rebin_results?.map(result => <p className="ath-hint" key={result.id}>{result.label}: {result.source_points.toLocaleString()} → {result.output_points.toLocaleString()} points · grid E₀ {result.e0.toFixed(3)} eV</p>)}
    {value?.warnings.map(note => <p key={note} className="ath-warning">{note}</p>)}
  </section>
}
