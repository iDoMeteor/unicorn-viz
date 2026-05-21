# BPM Evaluation Report — engine: `legacy`

| File | Truth | Predicted | AbsErr | ErrPct | HarmonicErrRate | TimeToLock | ConfAtLock | FastLane% |
|------|-------|-----------|--------|--------|-----------------|------------|------------|-----------|
| 090bpm_click | 90.0 | 146.3 | 56.30 | 62.5% | 0.385 | -1.0s | 0.000 | 68% |
| 096bpm_click | 96.0 | 157.7 | 61.73 | 64.3% | 0.000 | -1.0s | 0.000 | 100% |
| 120bpm_click | 120.0 | 139.7 | 19.66 | 16.4% | 0.000 | -1.0s | 0.000 | 50% |
| 140bpm_click | 140.0 | 143.0 | 3.00 | 2.1% | 0.000 | 2.1s | 0.667 | 100% |
| 155bpm_click | 155.0 | 159.6 | 4.61 | 3.0% | 0.000 | 17.4s | 0.498 | 100% |

## Summary

- Files evaluated: 5
- Median absolute BPM error: **19.66** BPM
- Mean absolute BPM error: **29.06** BPM
- Mean harmonic error rate: **0.077**
- Median time-to-lock: **9.8s**
