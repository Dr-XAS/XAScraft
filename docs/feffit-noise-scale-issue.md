# Reduced chi-square in feffit depends on how the noise level is set (factor 2), and on the k window

Applies to the Larch copy in this repository (`larch/xafs/feffit.py`), the same code as upstream Larch 2026.3.1. This issue is a write-up with a reproducer. No code changes with it, because the fix involves a convention choice for the team.

## What happens

A fit's reduced chi-square, chi-square, AIC and BIC depend on which route set the noise level. Best-fit values and their reported standard errors do not.
- **When `epsilon_k` is supplied** (by the user or after AUTOBK), `FeffitDataSet.set_epsilon_k` converts it to the R-space `epsilon_r` with `scale = 2*sqrt(pi*w/(kstep*I))`.
- **Otherwise**, `FeffitDataSet.estimate_noise` measures `epsilon_r` and converts with `scale = sqrt(2*pi*w/(kstep*I))`.

Here `w = 2*kweight + 1` and `I = kmax**w - kmin**w`. The two constants differ by √2, so passing the `epsilon_k` that `estimate_noise` returned back through `set_epsilon_k` doubles chi-square.

## Known-answer check

The model is perfect: pure white noise with σ = 0.002, no paths and no variables. A correct noise scale then gives reduced chi-square of about 1. The values are means over 100 seeded realizations (k 3–14, k-weight 2, R 1–3 Å). Each realization spreads by about ±50%, because R-space bins are correlated.

| Window | No `epsilon_k` (estimate_noise) | `epsilon_k` = true σ | `epsilon_k` = estimated |
|---|---|---|---|
| Rectangular (hanning, dk=0) | 1.01 | 1.95 | 2.02 |
| Hanning, dk=2 | 1.01 | 1.82 | 2.01 |
| Kaiser, dk=4 (the default) | 0.59 | 0.91 | 1.19 |

For rectangular and Hanning windows the `estimate_noise` constant is the one that matches the transform's normalization (Parseval for `xftf_fast`). `set_epsilon_k` is off by √2.

## Why this is not a one-line fix

Changing only the `set_epsilon_k` constant makes the two routes agree exactly (ratio 1.0000) and fixes rectangular and Hanning windows. But with the default Kaiser window, the true-σ route would fall from 0.91 to 0.46.

The 0.91 is close to 1 only by coincidence. `estimate_noise` divides the measured R-space noise by the window's mean value (`kwin_ave` = 0.77 for the default). The right correction is the k-weighted RMS of the window, and the missing √2 happened to offset that error.

A correct fix therefore changes both:
- `set_epsilon_k` converts with the window-aware constant, `epsilon_r = epsilon_k * kstep * sqrt(sum k**(2*kw) * W(k)**2 / (2*pi))`;
- `estimate_noise` keeps the measured R-space RMS as `epsilon_r`, with no `kwin_ave` division.

With both changes a perfect model should give about 1 for every window and both routes. That changes the reduced chi-square users see for every fit, and the `epsilon_k` reported for the default window by about 12%.

## Reproducer

`noise_scale_demo.py` (below) prints the table above from Larch's own `prepare_fit` and residual. Run it with this repository's `larch` on the path.

## Related, already fixed

The standalone `estimate_noise` passed its window as `kwindow=` to `xftf`, which takes `window=`, so it always used a Kaiser window. Hanning with dk=0 then became an all-zero Kaiser window and failed. This is fixed in #32.

<details><summary>noise_scale_demo.py</summary>

```python
"""Compare Larch's two epsilon_k -> epsilon_r conversions against the
empirical noise level of the Fourier-transformed chi(k).

Synthetic data: smooth chi(k) plus white Gaussian noise of known sigma on
Larch's standard grid (kstep = 0.05, k = 0..20). For each window and each
seeded realization we compute:

  rms_fit   empirical RMS of Re and Im of FT[noise] (the noise alone,
            transformed exactly as feffit does) in the fit R-range 1-3 A
  rms_hi    same, in the high-R range 15-30 A used by estimate_noise
  pred      analytic RMS: sigma * kstep/sqrt(2 pi) * sqrt(sum k^(2w) W(k)^2)
  eps_r(est)              FeffitDataSet.estimate_noise() on signal+noise
  eps_k(est)              its epsilon_k
  eps_r(set sigma)        FeffitDataSet.set_epsilon_k(sigma)
  eps_r(set est eps_k)    FeffitDataSet.set_epsilon_k(eps_k(est))

In an R-space fit the residual is realimag(FT[data - model]) / epsilon_r
(feffit.py, FeffitDataSet._residual), so for a perfect model the reduced
chi-square is about (rms_fit / epsilon_r)^2. That quantity is reported as
'implied reduced chi-square'.

A second check uses Larch's own residual: a FeffitDataSet whose data are
pure noise and which has no paths (model chi = 0, no variables), run through
prepare_fit() and _residual(). feffit() reports
chi2_reduced = chisqr * n_idp / npts / (n_idp - nvarys), which with nvarys = 0
is mean(residual**2). We do this (a) without data.epsilon_k (prepare_fit then
calls estimate_noise), (b) with data.epsilon_k = true sigma, and (c) with
data.epsilon_k = the epsilon_k that (a) estimated (both go through
set_epsilon_k).
"""
import numpy as np
import lmfit
import larch
from larch import Group
from larch.math import realimag
from larch.xafs import estimate_noise as estimate_noise_fn
from larch.xafs import xftf
from larch.xafs.feffit import TransformGroup, FeffitDataSet

KSTEP, KMIN, KMAX, KW = 0.05, 3.0, 14.0, 2
SIGMA = 0.002          # noise in chi(k), unweighted
NREAL = 100
SEED0 = 20261003
WINDOWS = [("hanning", 0.0, "rectangular (hanning, dk=0)"),
           ("hanning", 2.0, "hanning, dk=2"),
           ("kaiser", 4.0, "kaiser, dk=4 (Larch default)")]

k = KSTEP * np.arange(401)                       # 0 .. 20
# one smooth EXAFS-like shell at R ~ 2.2 A (no signal above R ~ 5 A)
signal = 0.5 * np.sin(2 * 2.2 * k + 0.5) * np.exp(-2 * 0.006 * k**2) / np.maximum(k, 1.0)


def rms_range(trans, x, rlo, rhi):
    chir = trans.fftf(x)
    i0 = int(0.01 + rlo / trans.rstep)
    i1 = int(min(trans.nfft / 2, 1.01 + rhi / trans.rstep))
    ri = realimag(chir[i0:i1])
    return np.sqrt((ri * ri).mean())


print(f"larch version: {larch.__version__}")
print(f"numpy version: {np.__version__}")
print(f"sigma={SIGMA}, kstep={KSTEP}, k-range {KMIN}-{KMAX}, kweight={KW}, "
      f"realizations={NREAL}, seeds {SEED0}..{SEED0 + NREAL - 1}")
print("fit R-range 1-3 A; estimate_noise high-R range 15-30 A\n")

summary = []
for wname, dk, label in WINDOWS:
    trans = TransformGroup(kmin=KMIN, kmax=KMAX, kweight=KW, dk=dk,
                           window=wname, kstep=KSTEP, rmin=1.0, rmax=3.0,
                           fitspace='r')
    trans.make_karrays()
    _ = trans.fftf(np.zeros_like(k))             # builds trans.kwin
    W = trans.kwin[:len(k)]
    pred = SIGMA * KSTEP / np.sqrt(2 * np.pi) * np.sqrt((k**(2 * KW) * W**2).sum())
    kwin_ave = W.sum() * KSTEP / (KMAX - KMIN)

    rows = []
    fn_errors = []
    for i in range(NREAL):
        rng = np.random.default_rng(SEED0 + i)
        noise = rng.normal(0.0, SIGMA, size=k.size)
        chi = signal + noise
        ds = FeffitDataSet(data=Group(k=k, chi=chi), transform=trans)

        ds.estimate_noise(chi=chi, rmin=15.0, rmax=30.0)
        eps_k_est, eps_r_est = float(ds.epsilon_k), float(ds.epsilon_r)

        # standalone larch.xafs.estimate_noise with the same window settings
        # (its kwindow argument is passed to xftf as 'kwindow', which xftf
        # does not accept as a window name, so xftf uses its default 'kaiser')
        g = Group(epsilon_k=np.nan, epsilon_r=np.nan)
        try:
            estimate_noise_fn(k, chi, group=g, rmin=15.0, rmax=30.0, kweight=KW,
                              kmin=KMIN, kmax=KMAX, dk=dk, kwindow=wname,
                              kstep=KSTEP)
        except Exception as exc:
            fn_errors.append(type(exc).__name__)

        ds.set_epsilon_k(SIGMA)
        eps_r_set_sigma = float(ds.epsilon_r)
        ds.set_epsilon_k(eps_k_est)
        eps_r_set_est = float(ds.epsilon_r)

        redchi = []
        for eps_in in (None, SIGMA, "est"):
            d = Group(k=k, chi=noise.copy())
            if eps_in == "est":
                d.epsilon_k = eps_k_auto
            elif eps_in is not None:
                d.epsilon_k = eps_in
            dsf = FeffitDataSet(data=d, transform=trans)
            pars = lmfit.Parameters()
            dsf.prepare_fit(pars)
            res = dsf._residual(pars)
            if eps_in is None:
                eps_k_auto = float(dsf.epsilon_k)
            redchi.append((res**2).mean())

        rows.append(redchi + [rms_range(trans, noise, 1.0, 3.0),
                     rms_range(trans, noise, 15.0, 30.0),
                     eps_k_est, eps_r_est, eps_r_set_sigma, eps_r_set_est,
                     g.epsilon_k, g.epsilon_r])
    a = np.array(rows)
    rc_auto, rc_sigma, rc_est, rms_fit, rms_hi, ek_est, er_est, er_sig, er_setest, ek_fn, er_fn = a.T

    def ms(x):
        return f"{x.mean():.4e} +- {x.std(ddof=1):.1e}"

    print(f"=== window: {label} ===")
    print(f"  mean window value kwin_ave (estimate_noise divides by this): {kwin_ave:.4f}")
    print(f"  analytic RMS of Re/Im of FT[noise]            : {pred:.4e}")
    print(f"  empirical RMS, R 1-3  (fit range)             : {ms(rms_fit)}")
    print(f"  empirical RMS, R 15-30 (estimate_noise range) : {ms(rms_hi)}")
    print(f"  estimate_noise epsilon_k  (true sigma {SIGMA})   : {ms(ek_est)}")
    print(f"  estimate_noise epsilon_r                      : {ms(er_est)}")
    print(f"  set_epsilon_k(sigma)          -> epsilon_r    : {ms(er_sig)}")
    print(f"  set_epsilon_k(est. epsilon_k) -> epsilon_r    : {ms(er_setest)}")
    if fn_errors:
        print(f"  standalone estimate_noise(kwindow={wname!r}, dk={dk}): raised "
              f"{sorted(set(fn_errors))} in {len(fn_errors)}/{NREAL} realizations")
    else:
        print(f"  standalone estimate_noise(kwindow={wname!r}, dk={dk}): eps_k {ms(ek_fn)}, eps_r {ms(er_fn)}")
    print("  ratios (mean over realizations):")
    print(f"    eps_r(estimate_noise) / eps_r(set_epsilon_k(est eps_k)) : {(er_est / er_setest).mean():.4f}  (sqrt2 = {np.sqrt(2):.4f})")
    print(f"    eps_r(estimate_noise) / empirical RMS (R 1-3)            : {(er_est / rms_fit).mean():.4f}")
    print(f"    eps_r(set_epsilon_k(sigma)) / empirical RMS (R 1-3)      : {(er_sig / rms_fit).mean():.4f}")
    print(f"    eps_k(estimate_noise) / true sigma                       : {(ek_est / SIGMA).mean():.4f}")
    print("  implied reduced chi-square for a perfect model, (rms_fit/eps_r)^2:")
    print(f"    with eps_r from estimate_noise                 : {((rms_fit / er_est)**2).mean():.3f}")
    print(f"    with eps_r from set_epsilon_k(est. eps_k)      : {((rms_fit / er_setest)**2).mean():.3f}")
    print(f"    with eps_r from set_epsilon_k(true sigma)      : {((rms_fit / er_sig)**2).mean():.3f}")
    print("  Larch's own residual (pure noise, no paths, nvarys=0) -> chi2_reduced:")
    print(f"    no epsilon_k given (prepare_fit -> estimate_noise) : {ms(rc_auto)}")
    print(f"    data.epsilon_k = true sigma (-> set_epsilon_k)     : {ms(rc_sigma)}")
    print(f"    data.epsilon_k = estimated eps_k (-> set_epsilon_k): {ms(rc_est)}")
    print(f"    ratio (c)/(a), mean                                : {(rc_est / rc_auto).mean():.4f}")
    print()
```

</details>
