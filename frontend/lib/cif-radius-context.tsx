"use client"

import { createContext, useContext, useMemo, useState, type ReactNode } from "react"
import { CIF_VIEWER_MAX_RADIUS, CIF_VIEWER_MIN_RADIUS } from "./cif-viewer"

const DEFAULT_CLUSTER_RADIUS = 5

type RadiusStore = {
  projectId?: string
  radii: Record<string, number>
  setRadii: React.Dispatch<React.SetStateAction<Record<string, number>>>
}
const CifRadii = createContext<RadiusStore | null>(null)

/** One radius per project and exact CIF snapshot, shared by viewers and calculators. */
export function CifRadiusProvider({ projectId, children }: { projectId?: string; children: ReactNode }) {
  const [radii, setRadii] = useState<Record<string, number>>({})
  const value = useMemo(() => ({ projectId, radii, setRadii }), [projectId, radii])
  return <CifRadii value={value}>{children}</CifRadii>
}

export function useCifRadius(cif?: string, projectId?: string): [number, (radius: number) => void] {
  const shared = useContext(CifRadii)
  const [localRadii, setLocalRadii] = useState<Record<string, number>>({})
  const key = JSON.stringify([shared?.projectId ?? projectId ?? null, cif ?? null])
  const radii = shared?.radii ?? localRadii
  const setRadii = shared?.setRadii ?? setLocalRadii
  return [radii[key] ?? DEFAULT_CLUSTER_RADIUS, radius => {
    if (!cif || !Number.isFinite(radius) || radius < CIF_VIEWER_MIN_RADIUS || radius > CIF_VIEWER_MAX_RADIUS) return
    setRadii(previous => previous[key] === radius ? previous : { ...previous, [key]: radius })
  }]
}
