# BPM Evaluation Report — engine: `v2`

| File | Truth | Predicted | AbsErr | ErrPct | HarmonicErrRate | TimeToLock | ConfAtLock | FastLane% |
|------|-------|-----------|--------|--------|-----------------|------------|------------|-----------|
| 090bpm_click | 90.0 | 94.2 | 4.22 | 4.7% | 0.071 | 8.5s | 0.279 | 0% |
| 096bpm_click | 96.0 | 96.8 | 0.77 | 0.8% | 0.103 | 9.6s | 0.725 | 0% |
| 120bpm_click | 120.0 | 120.0 | 0.01 | 0.0% | 0.000 | 8.7s | 0.429 | 0% |
| 140bpm_click | 140.0 | 138.8 | 1.23 | 0.9% | 0.146 | 6.2s | 0.419 | 0% |
| 155bpm_click | 155.0 | 153.8 | 1.15 | 0.7% | 0.000 | 5.4s | 0.527 | 95% |

## Summary

- Files evaluated: 5
- Median absolute BPM error: **1.15** BPM
- Mean absolute BPM error: **1.48** BPM
- Mean harmonic error rate: **0.064**
- Median time-to-lock: **8.5s**
