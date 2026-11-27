# Measurement methodology

Benchmark conclusions apply to the recorded corpus, configuration, software,
hardware, and observation window. A polished demo or a successful example is not
evidence of general accuracy or a production latency guarantee.

## Measurements and clocks

| Measurement | Definition and limit |
| --- | --- |
| Received FPS | Frames observed by the public RTC reader divided by the elapsed portion of the latest five-second window. Includes no-code frames. |
| Processing FPS | Completed frame operations in that window, including misses and rejected late results. The disabled-scanning control is labelled frame handling. |
| Image / encoding rate | Completed operations per observed window, in images/s or codes/s. A single operation is exploratory; use repetitions and longer batches for throughput evidence. |
| Frame latency | Worker receipt before frame copying through completion. Includes host scheduling and decoder admission. Excludes camera capture and earlier transport stages. |
| Image latency | Admission of authorized image bytes through completed operation. Excludes worker startup/warmup. |
| Encoding latency | Public encoding operation through PNG output. Independent OpenCV verification is recorded separately. |
| p50/p95/p99 | Interpolated percentiles of the latest up to 20,000 completion latencies within one attempt. Summary p95 is the median of attempt p95s, explicitly labelled; it is not a pooled-frame p95. |
| Queue age | Age from receipt to the host task starting its operation. Waiting inside an occupied decoder executor is included in total latency, not falsely reported as decoder CPU time. |
| First correct payload | First accepted complete payload multiset matching the evaluator oracle. No-code cases have no positive first-read time. |
| Capture to first correct | Available for controlled same-process publishers. Starts at the first published frame, not a browser camera timestamp or an inferred QR appearance in a recording. |
| Recovery | First accepted correct result after the recorded resume/reconnect/replacement event. Every configured source must produce results for a successful load case. |
| CPU | Sampled process CPU; 100% means one logical core. Worker and other components are separately scoped. Very short operations can fall below OS CPU accounting resolution. |
| Memory | Sampled RSS, not total allocations or unique physical memory. Peaks between samples can be missed. Encoding verification shares its worker's RSS. |
| Memory/latency drift | Endpoint RSS slope and p95s for halves of the retained latency window. Short windows and changing workload phases are noisy; these are diagnostic measures, not leak proofs. |

All QR operation intervals use one worker monotonic clock. No browser timestamp is
subtracted from a worker timestamp. Browser preview FPS is measured by video frame
callbacks and identified separately. Frames lost before the public RTC reader are
not observable as exact queue drops. Sampling, pending replacements, expired
results, retired sources, and late rejections have distinct counters.

## Controlled protocols

Select a suite, seed, split, implementations, repetitions, warmup, duration,
requested rates, decoder workers, and stream/room counts. The frozen report records
them. Each attempt uses a fresh worker. Warmups happen within that worker and are
excluded from measurement. A cold process is not a cold OS page cache. Cloud
requests are not warmed; provider caching remains an external variable.

The attempt order is deterministically shuffled. Paired implementations receive
the same image bytes and expected labels. Consecutive frames are correlated and
are not treated as independent accuracy trials. Attempt successes are shown
separately from the number of unique input groups that pass every repetition.
The Wilson 95% interval describes that input-consistency measure; repeating six
images does not turn them into eighteen independent corpus samples. Encoding
groups use the actual text input. Median timing intervals use a seeded
1,000-resample bootstrap over process attempts, conditional on this fixed workload.
Fewer than 30 input groups/attempts per condition receive an exploratory warning;
larger counts still require a corpus and power analysis appropriate to a claim.

Full and minimal tracing profiles form the observer-overhead experiment. Minimal
omits per-operation raw trace events but retains the same QR work, counters, and
four-Hz resource sampler. Matched-pair ratios estimate the observed cost of trace
generation/writer contention, with bootstrap uncertainty. They do not isolate
every source of machine noise. The scanning-disabled RTC control separately
measures frame handling without QR work.

Targets are chosen before execution. They are observed-sample acceptance budgets,
not a certification of population accuracy. Empty targets yield unrated results.
Timeouts, errors, unsupported modes, invalid JSON, missed payloads, incorrect
payloads, false detections, and recovery/capacity failures remain in evidence.
Scored execution failures remain in the accuracy denominator. Unlabelled inputs
are unscored. Missing data never becomes a zero latency or an invented success.

## Corpus and scoring

Synthetic-v1 uses an independent Segno encoder, explicit payloads, and deterministic
transforms: blur, skew, rotation, compression, low light, glare, small/multiple
codes, negatives, numeric/alphanumeric/UTF-8 payloads, and a labelled out-of-spec
quiet-zone crop. These transforms are not representative field prevalence.
Development/held-out synthetic seeds differ. Public fixtures have fixed disjoint
split assignments, but public data cannot prove that a model never encountered it.

The bundled public black-box subset is pinned to ZXing `zxing-3.5.3`; its label
files are preserved exactly, including whitespace, independently of all decoders
under test. It includes upstream license/notice and checksums. Import ZIP corpora
for your own photographs/recordings and independent labelling. The manifest needs
name, version, source, license, file, split, scenario, and exact expected strings;
an empty list marks a true negative. A corpus may declare real-world provenance;
the declaration does not independently certify its collection method.

Scoring compares complete text multisets, preserving whitespace, case, and
multiplicity. Raw native bytes/fidelity/landmarks remain in completion evidence;
the supplied text suites do not certify binary QR support or all QR variants.
Multiple-code video results aggregate distinct observed text over an attempt;
per-frame exact evidence and source coverage remain available for investigation.
Finding a QR symbol with no supported complete text is recorded as
`unsupported_payload`, separately from `missed`. Such a detection in a labelled
no-code case is a false detection, not a successful negative. Partial byte segments
remain explicitly partial and never become an invented full answer.

## AI and voice interpretation

Provider image modes use the same inputs and exact model IDs: vision alone,
provider-hosted code tools, or the registered QR function. No model sees oracle
answers or baseline outputs. QR tool availability is not the same as observed QR
tool use. Forced first-tool calls are a distinct recorded protocol. Hosted code
tool calls are observed, not assumed from the model's prose.

Record first output, QR tool request/result, complete structured answer, generation
interval after first output, cleanup, and token counts separately. Complete-answer
latency stops when the model response completes; file/container deletion happens
afterward. The elapsed interval after first output can include tool/network waits;
it is not isolated model compute. Client-observed stages do not reveal provider
queueing, internal GPU time, dependency installation, or network-only latency.
Token usage may include reported cached/reasoning counts. Invoice totals and all
hosted-tool fees are unknown, so the product does not invent billed savings.

LiveKit voice uses cloud inference only when explicitly enabled. It adds an agent,
audio, and a local tool bridge to the same measured QR pipeline. Transcript-to-tool,
agent tool round trip, and worker fresh-receipt scan duration have separate scopes.
Neither agent-state events nor transcript timestamps establish audible speech
latency. Consumer app screenshots and model explanations are qualitative records;
they do not establish a product-wide lack of QR capability or an API latency.

## Reproducibility and known operational limit

Exported ZIPs contain reports, inputs, raw events, corpus/recording when used, and
checksums. Replay verifies bytes and repeats the recorded attempts. It does not
recreate hardware/OS caches, network conditions, camera scenes, or future provider
behavior. Reports identify editable SDK installations, package fingerprints,
environment, requested/resolved model IDs when reported, and measurement revision.

Local RTC verification currently observes native LiveKit "unknown FFI handle"
messages during shutdown despite public reader/source/room cleanup. Workers exit
and their processes/resources are reclaimed; the warnings are counted and the
cleanup field says so. They are not suppressed or represented as a proven
production-clean lifecycle. Validate the relevant RTC SDK release before adoption.
