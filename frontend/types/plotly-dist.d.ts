declare module "plotly.js-dist-min" {
  const Plotly: {
    version: string
    toImage(figure: HTMLElement | { data: Array<Record<string, unknown>>; layout: Record<string, unknown> },
      options: { format: "svg" | "png"; width: number; height: number; scale?: number }): Promise<string>
  }
  export default Plotly
}
