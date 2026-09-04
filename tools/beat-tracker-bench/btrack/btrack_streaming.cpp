// btrack_streaming.cpp
//
// Minimal, custom pybind11 bindings exposing BTrack's real causal C++ API
// (the constructor, BTrack::processAudioFrame, and
// BTrack::getCurrentTempoEstimate, plus a couple of small related getters)
// directly to Python.
//
// This intentionally does NOT reuse or patch the upstream
// plugins/python-module/BTrackPythonModule.cpp bindings. Those only expose
// three batch/offline functions (detect_beats,
// calculate_onset_detection_function, detect_beats_from_odf), each of which
// consumes a complete NumPy array up front and runs an internal C++ loop
// before returning -- none of them retain per-call streaming state, so none
// can satisfy a feed()-once-per-live-block interface. See this directory's
// README.md for the full investigation.
//
// BTrack itself (Copyright (C) 2008-2014 Queen Mary University of London,
// author Adam Stark) is licensed GPL-3.0-or-later. This extension module
// links directly against BTrack's compiled static library and is therefore
// itself a GPL-3.0 derivative work. It is dev-only benchmarking tooling:
// never bundled into, imported by, or shipped as part of the unicorn-viz
// application. See README.md's "License" section.
//
// Build: see README.md for the exact compiler invocation. In short, this
// file is compiled against BTrack's `src/` and `libs/kiss_fft130/` headers
// (with -DUSE_KISS_FFT, matching how libBTrack.a itself was built) and
// linked against libBTrack.a plus the system libsamplerate.

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <stdexcept>
#include <string>

#include "BTrack.h"

namespace py = pybind11;

namespace {

/// Thin streaming wrapper around one BTrack instance.
///
/// hopSize/frameSize are fixed at construction time and not exposed for
/// later mutation: BTrack::updateHopAndFrameSize() exists in the underlying
/// C++ class, but it reinitialises internal buffers (onset detection
/// function history, cumulative score, comb-filter state), which would
/// silently discard everything the tracker has learned about the current
/// audio's tempo so far -- exactly the continuity a streaming benchmark
/// adapter depends on. If a caller needs a different hop/frame size, it
/// should construct a new BTrackStream instead.
class BTrackStream {
public:
    BTrackStream(int hop_size, int frame_size)
        : tracker_(hop_size, frame_size), hop_size_(hop_size) {}

    /// Process exactly one hop's worth of audio samples.
    ///
    /// `frame` must be a 1-D array of length hop_size, matching
    /// BTrack::processAudioFrame's documented contract (the number of
    /// samples must match the frame size the algorithm was constructed
    /// with -- BTrack's own internal windowing folds in the trailing
    /// history needed to reach its actual analysis frame size). Non-double
    /// or non-contiguous input is converted automatically by pybind11's
    /// `forcecast`.
    void process_audio_frame(
        py::array_t<double, py::array::c_style | py::array::forcecast> frame
    ) {
        py::buffer_info info = frame.request();
        if (info.ndim != 1 || info.shape[0] != hop_size_) {
            throw std::invalid_argument(
                "process_audio_frame expects a 1-D array of length hop_size ("
                + std::to_string(hop_size_) + "), got ndim="
                + std::to_string(info.ndim) + " shape[0]="
                + (info.ndim >= 1 ? std::to_string(info.shape[0]) : std::string("n/a")));
        }
        tracker_.processAudioFrame(static_cast<double*>(info.ptr));
    }

    double current_tempo_estimate() { return tracker_.getCurrentTempoEstimate(); }

    bool beat_due_in_current_frame() { return tracker_.beatDueInCurrentFrame(); }

    double latest_cumulative_score_value() {
        return tracker_.getLatestCumulativeScoreValue();
    }

    int hop_size() const { return hop_size_; }

private:
    BTrack tracker_;
    int hop_size_;
};

}  // namespace

PYBIND11_MODULE(btrack_streaming, m) {
    m.doc() =
        "Custom pybind11 bindings exposing BTrack's causal, frame-by-frame "
        "C++ API (not the upstream batch-only bindings). Dev-only, "
        "GPL-3.0-derivative benchmarking tooling -- see README.md.";

    py::class_<BTrackStream>(m, "BTrackStream")
        .def(
            py::init<int, int>(), py::arg("hop_size"), py::arg("frame_size"),
            "Construct a BTrack instance with a fixed hop_size/frame_size."
        )
        .def(
            "process_audio_frame", &BTrackStream::process_audio_frame,
            py::arg("frame"),
            "Process one hop_size-length double-precision audio frame."
        )
        .def(
            "current_tempo_estimate", &BTrackStream::current_tempo_estimate,
            "Return BTrack's current running tempo estimate, in BPM."
        )
        .def(
            "beat_due_in_current_frame", &BTrackStream::beat_due_in_current_frame,
            "Return True if BTrack judged a beat to fall within the most "
            "recently processed frame."
        )
        .def(
            "latest_cumulative_score_value",
            &BTrackStream::latest_cumulative_score_value,
            "Return the most recent value of BTrack's internal cumulative "
            "score function (an unbounded, unnormalised beat-alignment "
            "strength signal -- see README.md's confidence discussion)."
        )
        .def_property_readonly(
            "hop_size", &BTrackStream::hop_size,
            "The hop_size this instance was constructed with."
        );
}
