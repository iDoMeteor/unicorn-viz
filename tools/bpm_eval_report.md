# BPM Evaluation Report — engine: `v2`

| File | Truth | Predicted | AbsErr | ErrPct | HarmonicErrRate | TimeToLock | ConfAtLock | FastLane% |
|------|-------|-----------|--------|--------|-----------------|------------|------------|-----------|
| 090bpm_click | 90.0 | 91.6 | 1.64 | 1.8% | 0.138 | 10.2s | 0.255 | 0% |
| 096bpm_click | 96.0 | 96.0 | 0.05 | 0.1% | 0.034 | 6.0s | 0.967 | 0% |
| 120bpm_click | 120.0 | 120.0 | 0.00 | 0.0% | 0.000 | 6.7s | 0.400 | 0% |
| 140bpm_click | 140.0 | 139.5 | 0.47 | 0.3% | 0.080 | 7.5s | 0.379 | 0% |
| 155bpm_click | 155.0 | 153.8 | 1.15 | 0.7% | 0.000 | 4.1s | 0.229 | 100% |

## Summary

- Files evaluated: 5
- Median absolute BPM error: **0.47** BPM
- Mean absolute BPM error: **0.66** BPM
- Mean harmonic error rate: **0.050**
- Median time-to-lock: **6.7s**
