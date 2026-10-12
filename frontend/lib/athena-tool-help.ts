/** Field guidance for workbench dialogs; science remains in the existing commands. */
export const toolOptionHelp: Record<string, string> = {
  label: "The name shown in the data list, plots, and exports. Renaming preserves the measured data and source-file record.",
  multiplier: "Display scale applied to this data’s plotted signal. It does not rescale the measured arrays or change normalization.",
  offset: "Vertical display offset for this data. Use it to separate curves without changing their measured values.",
  importance: "Nonnegative data weight available to merging. Larger importance gives the data more influence when importance weighting is selected.",
  xmin: "Lower boundary of the analysis interval. Energy signals use absolute energy in eV; χ(k) uses wavenumber in Å⁻¹. Choose a range shared by the fitted data.",
  xmax: "Upper boundary of the analysis interval, in the same units as the minimum. Keep the window within usable data and exclude unrelated spectral features.",
  width: "Width of the broadening to remove: Gaussian standard deviation or Lorentzian half width at half maximum, in eV. Deconvolution can amplify noise.",
  start: "Value of the selected parameter in the first copy. Values are spaced evenly through the end value; the source data is retained.",
  stop: "Value of the selected parameter in the last copy. Use the same units as the parameter chosen above.",
  count: "Number of new data items to create across the parameter interval. Each copy is processed with its own parameter value.",
  kmin: "Lower k limit for the log-ratio fit, in Å⁻¹. Compare the same isolated shell in target and reference, where both signals are reliable.",
  kmax: "Upper k limit for the log-ratio fit, in Å⁻¹. Stop before noise or small reference amplitudes make the ratio unstable.",
  phase_offset: "Integer number of 2π turns added to the target-minus-reference phase. Inspect the phase branch before interpreting cumulant differences.",
  min_components: "Smallest number of standards allowed in a tested combination. Every subset within the chosen size limits is fitted.",
  max_components: "Largest number of standards allowed in a tested combination. More standards usually reduce R-factor; also compare reduced χ² and physical plausibility.",
  step_center: "Starting position of the background step in absolute energy, eV. Used when the step is not anchored to each data item’s E₀.",
  step_sigma: "Width parameter of the arctangent or error-function background step, in eV. Its meaning follows the selected step shape.",
}

export const peakFieldHelp = {
  center: "Starting position of this peak, in the chosen fit signal’s x units: eV for energy signals or Å⁻¹ for χ(k). The fit refines it within the analysis range.",
  sigma: "Starting peak width in the same x units as the centre. Gaussian uses standard deviation; Lorentzian uses half width at half maximum. Voigt combines Gaussian and Lorentzian broadening.",
  amplitude: "Starting integrated peak area, not peak height. The model combines this area with the width and line shape to determine the peak height.",
}
