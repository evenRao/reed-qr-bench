import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Room, LocalVideoTrack, LocalAudioTrack } from "livekit-client";
import type { Attempt, Bootstrap, Config, Run, Status } from "./types";
import "./style.css";

import { names, number } from "./display";
import { initial, sources, suiteDescription } from "./protocols";
import { Icon, Metric, Chart, Payloads } from "./telemetry";
import { NumberField, CloudControls } from "./controls";
import { SummaryTable, Comparison } from "./reports";
const isActive = (run?: Run | null) =>
  !!run &&
  ["queued", "running", "cancelling", "finalizing"].includes(run.status);
function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null),
    [tab, setTab] = useState(location.hash.slice(1) || "bench");
  const [status, setStatus] = useState<Status>({
      run: null,
      live: null,
      series: [],
    }),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [settings, setSettings] = useState(false);
  const [demo, setDemo] = useState<Config>({
    ...initial,
    suite: "interactive",
    source: "video",
    implementations: ["plugin"],
    scenarios: ["clean"],
    repetitions: 1,
    duration_s: 15,
  });
  const [experiment, setExperiment] = useState<Config>(initial),
    [history, setHistory] = useState<Run[]>([]),
    [report, setReport] = useState<Run | null>(null),
    [detail, setDetail] = useState<Attempt | null>(null);
  const [baseline, setBaseline] = useState<Run | null>(null),
    [query, setQuery] = useState(""),
    [failuresOnly, setFailuresOnly] = useState(false),
    [cameraState, setCameraState] = useState("Camera off"),
    [previewFps, setPreviewFps] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null),
    camera = useRef<{
      room: Room;
      track: LocalVideoTrack;
      audio?: LocalAudioTrack;
    } | null>(null),
    pendingCamera = useRef<LocalVideoTrack | null>(null);
  const pendingAudio = useRef<LocalAudioTrack | null>(null);
  const expectedRun = useRef<string | null>(null);
  const [uploadName, setUploadName] = useState(""),
    [recordingName, setRecordingName] = useState(""),
    [corpusName, setCorpusName] = useState("");
  const [keys, setKeys] = useState<Record<string, string>>({
      openai: "",
      gemini: "",
    }),
    [keyNotice, setKeyNotice] = useState("");
  const [expectedText, setExpectedText] = useState("");
  async function api(path: string, body?: unknown) {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined
          ? {}
          : {
              "Content-Type": "application/json",
              "X-REED-Bench": boot?.token || "",
            },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || "Request failed");
    return value;
  }
  useEffect(() => {
    fetch("/api/bootstrap")
      .then((r) => r.json())
      .then((bootstrap: Bootstrap) => {
        const models: Record<string, string> = {};
        Object.entries(bootstrap.provider_specs).forEach(([p, s]) => {
          models[p] = s.model;
          s.modes.forEach((m) => {
            names[`${p}:${m}`] =
              m === "reed"
                ? `${s.label} + REED QR`
                : `${s.label} · ${m === "code" ? "code tools" : "vision"}`;
          });
        });
        setDemo((c) => ({ ...c, models }));
        setExperiment((c) => ({ ...c, models }));
        setBoot(bootstrap);
      })
      .catch(() => setError("Could not connect to the local host."));
    const listener = () => setTab(location.hash.slice(1) || "bench");
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  useEffect(() => {
    if (!boot) return;
    let ended = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = (await api("/api/status")) as Status;
        if (
          !ended &&
          (!expectedRun.current || next.run?.id === expectedRun.current)
        )
          setStatus(next);
      } catch (e) {
        if (!ended) setError(String(e));
      } finally {
        if (!ended) timer = setTimeout(poll, 250);
      }
    }
    poll();
    return () => {
      ended = true;
      clearTimeout(timer);
    };
  }, [boot]);
  useEffect(() => {
    if (tab === "reports" && boot)
      api("/api/runs")
        .then(setHistory)
        .catch((e) => setError(String(e)));
  }, [tab, boot, status.run?.status]);
  useEffect(() => {
    if (report?.id && report.id === status.run?.id)
      api(`/api/runs/${report.id}`)
        .then(setReport)
        .catch((e) => setError(String(e)));
  }, [report?.id, status.run?.status, status.run?.progress.completed]);
  useEffect(() => {
    document.getElementById("content")?.focus();
  }, [tab]);
  useEffect(() => {
    if (!settings && !detail) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSettings(false);
        setDetail(null);
      }
      if (event.key === "Tab") {
        const nodes = Array.from(
          document.querySelectorAll<HTMLElement>(
            ".dialog button:not(:disabled),.dialog input,.dialog select,.dialog textarea,.dialog a[href]",
          ),
        );
        const first = nodes[0],
          last = nodes.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", key);
    };
  }, [settings, detail]);
  useEffect(() => {
    if (status.run && !isActive(status.run)) closeCamera();
  }, [status.run?.status]);
  useEffect(() => {
    if (tab === "bench" && camera.current && videoRef.current)
      camera.current.track.attach(videoRef.current);
  }, [tab, status.live?.attempt_id]);
  useEffect(() => {
    let ended = false;
    async function connect() {
      const connection = status.live?.camera;
      if (
        !connection ||
        camera.current ||
        !pendingCamera.current ||
        !isActive(status.run)
      )
        return;
      const track = pendingCamera.current;
      pendingCamera.current = null;
      const { Room, RoomEvent, Track } = await import("livekit-client");
      const room = new Room();
      camera.current = { room, track };
      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (ended) return;
        if (track.kind === Track.Kind.Audio) {
          const element = track.attach();
          element.dataset.voiceAudio = "true";
          document.body.append(element);
          element
            .play()
            .catch(() =>
              setError(
                "Allow audio playback in the browser to hear the agent.",
              ),
            );
        }
      });
      room.on(RoomEvent.TrackUnsubscribed, (track) =>
        track.detach().forEach((el) => el.remove()),
      );
      room.on(RoomEvent.Disconnected, () =>
        setCameraState("Camera disconnected"),
      );
      room
        .connect(connection.url, connection.token)
        .then(async () => {
          if (ended || camera.current?.room !== room) {
            track.stop();
            await room.disconnect();
            return;
          }
          await room.localParticipant.publishTrack(track, {
            source: Track.Source.Camera,
            simulcast: false,
          });
        })
        .then(async () => {
          if (ended) return;
          const audio = pendingAudio.current;
          pendingAudio.current = null;
          if (audio) {
            camera.current!.audio = audio;
            await room.localParticipant.publishTrack(audio, {
              source: Track.Source.Microphone,
            });
          }
          setCameraState("Publishing through LiveKit");
        })
        .catch((e) => {
          if (ended || camera.current?.room !== room) {
            track.stop();
            room.disconnect();
            return;
          }
          setError(`Camera connection failed: ${String(e)}`);
          closeCamera();
          api("/api/stop", {}).catch(() => {});
        });
    }
    connect().catch((e) => setError(String(e)));
    return () => {
      ended = true;
    };
  }, [status.live?.camera?.token]);
  useEffect(() => {
    const v = videoRef.current;
    if (
      !v ||
      !camera.current ||
      typeof v.requestVideoFrameCallback !== "function"
    )
      return;
    let handle = 0,
      last = performance.now(),
      frames = 0,
      ended = false;
    function frame(now: number) {
      frames++;
      if (now - last >= 1000) {
        setPreviewFps((frames * 1000) / (now - last));
        last = now;
        frames = 0;
      }
      if (!ended) handle = v!.requestVideoFrameCallback(frame);
    }
    handle = v.requestVideoFrameCallback(frame);
    return () => {
      ended = true;
      v.cancelVideoFrameCallback(handle);
    };
  }, [cameraState, tab]);
  function closeCamera() {
    document.querySelectorAll("[data-voice-audio]").forEach((e) => e.remove());
    pendingAudio.current?.stop();
    pendingAudio.current = null;
    pendingCamera.current?.stop();
    pendingCamera.current = null;
    if (camera.current) {
      camera.current.track.stop();
      camera.current.audio?.stop();
      camera.current.room.disconnect();
      camera.current = null;
    }
    setCameraState("Camera off");
    setPreviewFps(null);
  }
  useEffect(() => () => closeCamera(), []);
  async function start(config: Config) {
    setError("");
    setBusy(true);
    expectedRun.current = "starting";
    setStatus({ run: null, live: null, series: [] });
    try {
      if (config.source === "camera") {
        const { createLocalVideoTrack, createLocalAudioTrack } = await import(
          "livekit-client"
        );
        if (config.voice) pendingAudio.current = await createLocalAudioTrack();
        const track = await createLocalVideoTrack({
          resolution: { width: 640, height: 480, frameRate: config.input_hz },
        });
        pendingCamera.current = track;
        track.attach(videoRef.current!);
        setCameraState("Connecting camera");
      }
      const started = await api("/api/runs", config);
      expectedRun.current = started.id;
      setStatus({
        run: {
          id: started.id,
          status: started.status,
          progress: { completed: 0, total: 0 },
          summary: [],
        },
        live: null,
        series: [],
      });
    } catch (e) {
      expectedRun.current = null;
      setError(String(e).replace("Error: ", ""));
      closeCamera();
    } finally {
      setBusy(false);
    }
  }
  async function stop() {
    setBusy(true);
    try {
      closeCamera();
      await api("/api/stop", {});
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function upload(
    files: FileList | null,
    kind: "images" | "recordings" | "corpora",
    forExperiment = false,
  ) {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      const ids: string[] = [];
      for (const file of Array.from(files)) {
        const response = await fetch(`/api/${kind}`, {
          method: "POST",
          headers: { "X-REED-Bench": boot?.token || "" },
          body: file,
        });
        const value = await response.json();
        if (!response.ok) throw new Error(value.error);
        ids.push(value.id);
      }
      if (kind === "images") {
        setUploadName(
          `${files.length} image${files.length > 1 ? "s" : ""} · ${files[0].name}`,
        );
        setDemo((c) => ({ ...c, image_ids: ids }));
        if (forExperiment)
          setExperiment((c) => ({
            ...c,
            image_ids: ids,
            source: "image",
            corpus_id: undefined,
          }));
      }
      if (kind === "recordings") {
        setRecordingName(files[0].name);
        setDemo((c) => ({ ...c, recording_id: ids[0] }));
        setExperiment((c) => ({
          ...c,
          recording_id: ids[0],
          source: "recording",
        }));
      }
      if (kind === "corpora") {
        setCorpusName(files[0].name);
        setExperiment((c) => ({
          ...c,
          corpus_id: ids[0],
          source: "image",
          image_ids: [],
        }));
      }
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  }
  const active = isActive(status.run),
    live = active || status.live?.source === demo.source ? status.live : null,
    metrics = (tab === "bench" ? live : status.live)?.metrics || {},
    video = ["video", "camera", "recording"].includes(
      live?.source || demo.source,
    );
  const unit = video
    ? "fps"
    : (live?.source || demo.source) === "encode"
      ? "codes/s"
      : "images/s";
  const viewDemo: Config =
    active && status.run?.config && live
      ? {
          ...status.run.config,
          implementations: [live.implementation],
          scenarios: [live.scenario],
        }
      : demo;
  const selectedSource = sources.find((s) => s.id === viewDemo.source)?.label;
  const shownSummary = report?.summary || status.run?.summary || [];
  function selectSource(source: string) {
    setDemo((c) => ({
      ...c,
      source,
      voice: false,
      implementations: [
        c.implementations[0].includes(":") || source === "encode"
          ? "plugin"
          : c.implementations[0],
      ],
      image_ids: source === "image" ? c.image_ids : [],
      repetitions: 1,
      operations: 1,
    }));
  }
  function preset(key: string) {
    const chosen = boot?.suites[key];
    if (chosen) {
      const { title: _title, ...selected } = chosen;
      setExperiment({
        ...initial,
        ...selected,
        suite: key,
        loads: chosen.loads || [1],
        models: experiment.models,
        targets: experiment.targets,
        allow_cloud: experiment.allow_cloud,
      });
    }
  }
  const modes = Object.entries(names)
    .filter(([key]) => demo.source === "image" || !key.includes(":"))
    .filter(
      ([key]) => demo.source !== "encode" || ["plugin", "sdk"].includes(key),
    );

  return (
    <>
      <a className="skip" href="#content">
        Skip to workspace
      </a>
      <header className="app-header">
        <a href="#bench" className="brand">
          <span className="brand-mark">
            <Icon name="qr" />
          </span>
          <span>
            REED QR <b>Bench</b>
            <small>DEMO + BENCHMARK</small>
          </span>
        </a>
        <nav aria-label="Workspaces">
          {[
            ["bench", "Test bench", "bench"],
            ["experiments", "Experiments", "experiments"],
            ["reports", "Reports", "reports"],
          ].map(([id, label, icon]) => (
            <a
              href={`#${id}`}
              key={id}
              aria-current={tab === id ? "page" : undefined}
            >
              <Icon name={icon} />
              {label}
            </a>
          ))}
        </nav>
        <button
          className="quiet settings-button"
          aria-label="Integrations"
          onClick={() => setSettings(true)}
        >
          <Icon name="settings" />
          <span>Integrations</span>
        </button>
      </header>
      <main id="content" tabIndex={-1}>
        <div className="workspace-heading">
          <div>
            <div className="eyebrow">REED QR / EVALUATION WORKSPACE</div>
            <h1>
              {tab === "bench"
                ? "Live QR test bench"
                : tab === "experiments"
                  ? "Run a controlled experiment."
                  : "Benchmark reports"}
            </h1>
            <p>
              {tab === "bench"
                ? "The installed QR capability, with live measurements beside the result."
                : tab === "experiments"
                  ? "Freeze the inputs, protocol, and acceptance targets before measuring."
                  : "Compare like-for-like runs, investigate failures, and take the evidence with you."}
            </p>
          </div>
          <span className={`status-pill ${active ? "running" : ""}`}>
            <i />
            {status.run?.status || "Ready"}
            {active
              ? ` · ${status.run!.progress.completed} / ${status.run!.progress.total}`
              : ""}
          </span>
          {active && (
            <button className="stop" disabled={busy} onClick={stop}>
              Stop run
            </button>
          )}
        </div>
        {error && (
          <div role="alert" className="error">
            <span>{error}</span>
            <button className="quiet" onClick={() => setError("")}>
              Dismiss
            </button>
          </div>
        )}
        {tab === "bench" && (
          <>
            <div className="source-tabs" aria-label="Test source">
              {sources.map((s) => (
                <button
                  key={s.id}
                  disabled={active || busy}
                  aria-pressed={viewDemo.source === s.id}
                  onClick={() => selectSource(s.id)}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <section className="control-bar panel">
              <label>
                Implementation
                <select
                  aria-label="Implementation"
                  disabled={active || busy}
                  value={viewDemo.implementations[0]}
                  onChange={(e) =>
                    setDemo({ ...demo, implementations: [e.target.value] })
                  }
                >
                  {modes.map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              {viewDemo.source === "video" && (
                <label>
                  Scene
                  <select
                    disabled={active || busy}
                    value={viewDemo.scenarios[0]}
                    onChange={(e) =>
                      setDemo({ ...demo, scenarios: [e.target.value] })
                    }
                  >
                    {Object.entries(boot?.scenarios || {}).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {["video", "camera", "recording"].includes(viewDemo.source) ? (
                <>
                  <NumberField
                    label="Decode target (Hz)"
                    value={viewDemo.scan_hz}
                    disabled={active || busy}
                    min={0.5}
                    max={60}
                    onChange={(scan_hz) => setDemo({ ...demo, scan_hz })}
                  />
                  <NumberField
                    label="Duration (seconds)"
                    value={viewDemo.duration_s}
                    disabled={active || busy}
                    min={2}
                    max={3600}
                    onChange={(duration_s) => setDemo({ ...demo, duration_s })}
                  />
                </>
              ) : (
                <NumberField
                  label="Measured operations"
                  value={viewDemo.operations}
                  disabled={active || busy}
                  min={1}
                  max={10000}
                  onChange={(operations) => setDemo({ ...demo, operations })}
                />
              )}
              <button
                className={active ? "stop" : "primary"}
                disabled={!boot || busy}
                onClick={() => (active ? stop() : start(demo))}
              >
                <Icon name={active ? "stop" : "play"} />
                {busy ? "Working…" : active ? "Stop test" : "Start test"}
              </button>
            </section>
            {viewDemo.source === "image" && (
              <section className="source-input panel">
                <label className="upload">
                  Upload image or batch
                  <input
                    type="file"
                    multiple
                    accept="image/png,image/jpeg"
                    disabled={active || busy}
                    onChange={(e) => upload(e.target.files, "images")}
                  />
                </label>
                <span className="muted">
                  {uploadName ||
                    "No upload: uses an independent Segno fixture."}
                </span>
                <button
                  className="quiet"
                  disabled={active || busy}
                  onClick={() => {
                    setDemo({ ...demo, image_ids: [] });
                    setUploadName("");
                  }}
                >
                  Use fixture
                </button>
              </section>
            )}
            {viewDemo.source === "recording" && (
              <section className="source-input panel">
                <label className="upload">
                  Upload recording
                  <input
                    type="file"
                    accept="video/*"
                    disabled={active || busy}
                    onChange={(e) => upload(e.target.files, "recordings")}
                  />
                </label>
                <span className="muted">
                  {recordingName ||
                    "MP4 / WebM supported by installed reader · up to 64 MiB · replayed at configured input Hz, 640×480"}
                </span>
              </section>
            )}
            {viewDemo.source === "encode" && (
              <section className="source-input panel">
                <label className="grow">
                  Exact payload
                  <input
                    value={viewDemo.text}
                    disabled={active || busy}
                    onChange={(e) => setDemo({ ...demo, text: e.target.value })}
                  />
                </label>
                <label>
                  Correction
                  <select
                    value={viewDemo.correction}
                    disabled={active || busy}
                    onChange={(e) =>
                      setDemo({ ...demo, correction: e.target.value })
                    }
                  >
                    {["L", "M", "Q", "H"].map((i) => (
                      <option key={i}>{i}</option>
                    ))}
                  </select>
                </label>
                <NumberField
                  label="Pixels/module"
                  value={viewDemo.scale}
                  disabled={active || busy}
                  min={2}
                  max={12}
                  onChange={(scale) => setDemo({ ...demo, scale })}
                />
              </section>
            )}
            {viewDemo.implementations[0].includes(":") && (
              <CloudControls
                config={viewDemo}
                disabled={active || busy}
                setConfig={setDemo}
                providers={boot?.providers || {}}
              />
            )}
            {viewDemo.source === "camera" && (
              <section className="panel">
                <label className="check">
                  <input
                    type="checkbox"
                    disabled={active || busy}
                    checked={!!viewDemo.voice}
                    onChange={(e) =>
                      setDemo({
                        ...demo,
                        voice: e.target.checked,
                        allow_cloud: e.target.checked,
                        implementations: ["plugin"],
                      })
                    }
                  />
                  Enable LiveKit voice control · paid LiveKit Cloud session +
                  microphone
                </label>
                <p className="note">
                  {boot?.voice_configured
                    ? "LiveKit Cloud credentials configured."
                    : "Configure LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET in .env to use voice."}{" "}
                  The agent requests a fresh result from this same QR pipeline.
                  QR latency and voice/tool round-trip timing stay separate.
                </p>
              </section>
            )}
            <div className="metrics-grid">
              <Metric
                label={video ? "Received video" : "Admitted inputs"}
                value={metrics.received_rate}
                unit={unit}
                note={
                  video
                    ? `RTC aggregate · ${live?.streams || 1} source(s) · 5 s window`
                    : "Measured admission rate · current attempt"
                }
                accent="blue"
              />
              <Metric
                label={
                  live?.implementation === "off"
                    ? "Frame handling"
                    : "QR processing"
                }
                value={metrics.processed_rate}
                unit={unit}
                note={
                  live?.implementation === "off"
                    ? "Transport control · QR scanning disabled"
                    : `${metrics.counts?.processed || 0} completions · misses included`
                }
                accent="teal"
              />
              <Metric
                label="Frame / operation latency"
                value={metrics.p50_ms}
                unit="ms"
                note="p50 · receipt/admission to completion"
              />
              <Metric
                label="Tail latency"
                value={metrics.p95_ms}
                unit="ms"
                note={`p95 · ${metrics.latency_samples || 0} measured samples`}
              />
              <Metric
                label={active ? "Worker CPU" : "Peak worker CPU"}
                value={metrics.cpu_percent}
                unit="%"
                note="Isolated worker · 100% = one core"
              />
              <Metric
                label={active ? "Worker memory" : "Peak worker memory"}
                value={metrics.rss_mb}
                unit="MiB"
                note="Resident memory · sampled every 250 ms"
              />
            </div>
            <div className="bench-grid">
              <section className="panel preview-panel">
                <div className="panel-heading">
                  <h2>{selectedSource}</h2>
                  <span className="badge">
                    {active ? "Measuring" : "Preview & result"}
                  </span>
                </div>
                <div className="preview">
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    className={viewDemo.source === "camera" ? "" : "hidden"}
                    aria-label="Local camera preview"
                  />
                  {viewDemo.source !== "camera" &&
                    (live?.result?.artifact && status.run ? (
                      <img
                        src={`/api/runs/${status.run.id}/artifact/${live.result.artifact}`}
                        alt="Generated QR code, independently verified"
                      />
                    ) : live?.preview ? (
                      <img
                        src={live.preview}
                        alt="Input image for the current attempt"
                      />
                    ) : (
                      <div className="preview-empty">
                        <Icon name="qr" />
                        <strong>Your source appears here</strong>
                        <span>
                          Start a fixture test or upload your own input.
                        </span>
                      </div>
                    ))}
                  {viewDemo.source === "camera" && !active && (
                    <div className="camera-hint">
                      Start test to grant camera access.
                      <br />
                      Video is decoded after transport through LiveKit.
                    </div>
                  )}
                  {["video", "recording"].includes(viewDemo.source) && (
                    <div className="preview-caption">
                      Source frame · actual video travels through LiveKit at 640
                      × 480
                    </div>
                  )}
                </div>
                <div className="preview-footer">
                  <span>
                    {viewDemo.source === "camera"
                      ? cameraState
                      : "No automatic URL navigation"}
                  </span>
                  <span>
                    {viewDemo.source === "camera"
                      ? `Preview ${number(previewFps)} fps`
                      : `${names[live?.implementation || viewDemo.implementations[0]]}`}
                  </span>
                </div>
              </section>
              <section className="panel result-panel">
                <div className="panel-heading">
                  <h2>Decoded result</h2>
                  <span className="badge">
                    {live?.result?.score || "Unscored until evaluated"}
                  </span>
                </div>
                <div className="payload">
                  <Payloads
                    payloads={live?.result?.payloads}
                    detections={
                      live?.result?.detections || metrics.latest?.detections
                    }
                    processed={!!metrics.counts?.processed}
                  />
                </div>
                {live?.result?.error && (
                  <p className="error" role="alert">
                    {live.result.error}
                  </p>
                )}
                <dl className="facts">
                  <div>
                    <dt>Worker launch → first text result</dt>
                    <dd>{number(live?.host_to_first_payload_ms)} ms</dd>
                  </div>
                  <div>
                    <dt>First correct payload</dt>
                    <dd>
                      {number(
                        live?.result?.first_correct_ms ??
                          live?.first_correct_ms,
                      )}{" "}
                      ms
                    </dd>
                  </div>
                  <div>
                    <dt>First QR detection</dt>
                    <dd>{number(metrics.first_result_ms)} ms</dd>
                  </div>
                  <div>
                    <dt>Queue age p95</dt>
                    <dd>{number(metrics.queue_p95_ms)} ms</dd>
                  </div>
                  <div>
                    <dt>Received / processed</dt>
                    <dd>
                      {metrics.counts?.received || 0} /{" "}
                      {metrics.counts?.processed || 0}
                    </dd>
                  </div>
                  <div>
                    <dt>Sampled out / replaced</dt>
                    <dd>
                      {metrics.counts?.sampled_out || 0} /{" "}
                      {metrics.counts?.replaced || 0}
                    </dd>
                  </div>
                  <div>
                    <dt>Stale / late rejected</dt>
                    <dd>
                      {metrics.counts?.stale || 0} /{" "}
                      {metrics.counts?.late_rejected || 0}
                    </dd>
                  </div>
                </dl>
                {live?.result?.first_token_ms != null && (
                  <div className="callout">
                    First model output {number(live.result.first_token_ms)} ms ·
                    QR tool ready {number(live.result.tool_result_ms)} ms.
                    Complete answer timing is separate.
                  </div>
                )}
                <p className="note">
                  {viewDemo.source === "camera"
                    ? "Live scenes have no ground truth: accuracy is unscored. Preview FPS is measured in the browser; received FPS is measured in the worker."
                    : viewDemo.source === "encode"
                      ? "Encoding time excludes the independent OpenCV round-trip check."
                      : "First-payload time starts at the measured attempt, after warmup. Frame latency starts at receipt, after transport."}
                </p>
                {status.run && !active && (
                  <button
                    className="secondary"
                    onClick={async () => {
                      setReport(await api(`/api/runs/${status.run!.id}`));
                      location.hash = "reports";
                    }}
                  >
                    Inspect this report
                  </button>
                )}
              </section>
            </div>
            {live?.voice && (
              <section className="panel">
                <div className="panel-heading">
                  <h2>LiveKit voice</h2>
                  <span className="badge">
                    QR worker resources exclude the agent
                  </span>
                </div>
                {live.voice.map((e, i) => (
                  <div className="voice-line" key={i}>
                    <b>{e.type.replaceAll("_", " ")}</b>
                    <span>
                      {typeof e.value === "string"
                        ? e.value
                        : e.type === "transcript"
                          ? `${e.value.role}: ${e.value.text}`
                          : e.type === "tool_completed"
                            ? `Agent tool round trip ${number(e.value.agent_tool_roundtrip_ms)} ms · worker fresh scan ${number(e.value.worker_scan_ms)} ms · ${e.value.status}`
                            : `Final transcript to tool request ${number(e.value.transcript_to_tool_ms)} ms`}
                    </span>
                  </div>
                ))}
              </section>
            )}
            {viewDemo.implementations[0].includes(":") && (
              <section className="panel">
                <div className="panel-heading">
                  <h2>AI workflow timing</h2>
                  <span className="badge">Client-observed stages</span>
                </div>
                <dl className="facts">
                  {[
                    ["Elapsed workflow", (metrics.elapsed_s || 0) * 1000],
                    [
                      "First model output",
                      live?.result?.first_token_ms ??
                        live?.model_stages?.first_model_output,
                    ],
                    [
                      "QR tool requested",
                      live?.result?.tool_requested_ms ??
                        live?.model_stages?.tool_requested,
                    ],
                    [
                      "QR tool result available",
                      live?.result?.tool_result_ms ??
                        live?.model_stages?.tool_result_available,
                    ],
                    [
                      "Complete structured answer",
                      live?.result?.complete_answer_ms ??
                        live?.model_stages?.model_response_completed,
                    ],
                    [
                      "Elapsed after first output",
                      live?.result?.generation_after_first_output_ms,
                    ],
                    [
                      "Provider artifact cleanup",
                      live?.result?.provider_cleanup_ms,
                    ],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <dt>{label}</dt>
                      <dd>{number(value as number | undefined)} ms</dd>
                    </div>
                  ))}
                </dl>
                <p className="note">
                  Tool availability does not establish tool use. Model
                  internals, network-only time, and billed totals are unknown.{" "}
                  {live?.result?.usage
                    ? JSON.stringify(live.result.usage)
                    : "Token usage appears when the provider reports it."}
                </p>
              </section>
            )}
            <div className="two-column">
              <Chart
                title="Throughput over time"
                unit={unit}
                series={live ? status.series : []}
                lines={[
                  { key: "received", label: "Received", color: "#93b4ee" },
                  { key: "processed", label: "Processed", color: "#7dd3c0" },
                ]}
              />
              <Chart
                title="Latency over time"
                unit="ms · attempt p95"
                series={live ? status.series : []}
                lines={[
                  { key: "p95", label: "Receipt to result", color: "#c4b5fd" },
                ]}
              />
            </div>
            <details className="panel trace">
              <summary>
                Execution trace{" "}
                <span className="muted">
                  {live?.events.length || 0} recent lifecycle events · full
                  trace in evidence export
                </span>
              </summary>
              <div className="trace-list">
                {live?.events.map((e, i) => (
                  <div key={i}>
                    <code>{number(e.ms)} ms</code>
                    <span>{e.event.replaceAll("_", " ")}</span>
                  </div>
                ))}
              </div>
            </details>
            <div className="scope-note">
              5-second rolling rates · per-attempt latency samples · worker
              startup and warmup excluded · requests target {viewDemo.scan_hz}{" "}
              Hz / input {viewDemo.input_hz} Hz. Requested limits are not
              measured FPS.
            </div>
          </>
        )}
        {tab === "experiments" && (
          <>
            <div className="experiment-layout">
              <section className="panel setup-panel">
                <div className="panel-heading">
                  <h2>Protocol</h2>
                  <span className="badge">Frozen when started</span>
                </div>
                <fieldset className="protocol-fields" disabled={active || busy}>
                  <label>
                    Experiment suite
                    <select
                      value={experiment.suite}
                      disabled={active || busy}
                      onChange={(e) => preset(e.target.value)}
                    >
                      {Object.entries(boot?.suites || {}).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v.title}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="note">{suiteDescription(experiment.suite)}</p>
                  <fieldset disabled={active || busy}>
                    <legend>Implementations</legend>
                    <div className="check-grid">
                      {Object.entries(names)
                        .filter(([k]) =>
                          experiment.source === "encode"
                            ? ["plugin", "sdk"].includes(k)
                            : experiment.suite === "ai"
                              ? k.includes(":")
                              : !k.includes(":"),
                        )
                        .map(([k, v]) => (
                          <label className="check" key={k}>
                            <input
                              type="checkbox"
                              checked={experiment.implementations.includes(k)}
                              onChange={(e) =>
                                setExperiment({
                                  ...experiment,
                                  implementations: e.target.checked
                                    ? [...experiment.implementations, k]
                                    : experiment.implementations.filter(
                                        (i) => i !== k,
                                      ),
                                })
                              }
                            />
                            {v}
                          </label>
                        ))}
                    </div>
                  </fieldset>
                  <details open={experiment.suite === "robustness"}>
                    <summary>
                      Scenarios{" "}
                      <span className="muted">
                        {experiment.scenarios.length} selected
                      </span>
                    </summary>
                    <div className="check-grid">
                      {Object.entries(boot?.scenarios || {}).map(([k, v]) => (
                        <label className="check" key={k}>
                          <input
                            type="checkbox"
                            disabled={active || busy}
                            checked={experiment.scenarios.includes(k)}
                            onChange={(e) =>
                              setExperiment({
                                ...experiment,
                                scenarios: e.target.checked
                                  ? [...experiment.scenarios, k]
                                  : experiment.scenarios.filter((i) => i !== k),
                              })
                            }
                          />
                          {v}
                        </label>
                      ))}
                    </div>
                  </details>
                  <div className="form-grid">
                    <NumberField
                      label="Independent repetitions"
                      value={experiment.repetitions}
                      min={1}
                      max={100}
                      onChange={(repetitions) =>
                        setExperiment({ ...experiment, repetitions })
                      }
                    />
                    <NumberField
                      label="Warmup operations / worker"
                      value={experiment.warmups}
                      min={0}
                      max={10}
                      onChange={(warmups) =>
                        setExperiment({ ...experiment, warmups })
                      }
                    />
                    <NumberField
                      label="Seed"
                      value={experiment.seed}
                      min={0}
                      max={2147483647}
                      onChange={(seed) =>
                        setExperiment({ ...experiment, seed })
                      }
                    />
                    <label>
                      Corpus split
                      <select
                        value={experiment.split}
                        onChange={(e) =>
                          setExperiment({
                            ...experiment,
                            split: e.target.value,
                          })
                        }
                      >
                        <option value="development">Development</option>
                        <option value="held_out">Held out</option>
                      </select>
                    </label>
                  </div>
                  {["video", "camera", "recording"].includes(
                    experiment.source,
                  ) && (
                    <div className="form-grid">
                      <NumberField
                        label="Duration / attempt (s)"
                        value={experiment.duration_s}
                        min={2}
                        max={3600}
                        onChange={(duration_s) =>
                          setExperiment({ ...experiment, duration_s })
                        }
                      />
                      <NumberField
                        label="Decode target (Hz / stream)"
                        value={experiment.scan_hz}
                        min={0.5}
                        max={60}
                        onChange={(scan_hz) =>
                          setExperiment({ ...experiment, scan_hz })
                        }
                      />
                      <NumberField
                        label="Input target (Hz / stream)"
                        value={experiment.input_hz}
                        min={1}
                        max={60}
                        onChange={(input_hz) =>
                          setExperiment({ ...experiment, input_hz })
                        }
                      />
                    </div>
                  )}
                  {experiment.suite === "load" && (
                    <fieldset>
                      <legend>Concurrent video sources</legend>
                      <label>
                        Load topology
                        <select
                          value={experiment.load_kind || "streams"}
                          onChange={(e) =>
                            setExperiment({
                              ...experiment,
                              load_kind: e.target.value,
                            })
                          }
                        >
                          <option value="streams">
                            Multiple streams in one room
                          </option>
                          <option value="rooms">
                            One stream per independent room
                          </option>
                        </select>
                      </label>
                      <div className="check-grid">
                        {[1, 2, 4, 8].map((n) => (
                          <label className="check" key={n}>
                            <input
                              type="checkbox"
                              checked={experiment.loads.includes(n)}
                              onChange={(e) =>
                                setExperiment({
                                  ...experiment,
                                  loads: e.target.checked
                                    ? [...experiment.loads, n]
                                    : experiment.loads.filter((i) => i !== n),
                                })
                              }
                            />
                            {n}{" "}
                            {experiment.load_kind === "rooms"
                              ? "room"
                              : "stream"}
                            {n > 1 ? "s" : ""}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  )}
                  {experiment.suite === "ai" && (
                    <CloudControls
                      config={experiment}
                      setConfig={setExperiment}
                      providers={boot?.providers || {}}
                    />
                  )}
                  <details>
                    <summary>Corpus and uploaded inputs</summary>
                    {experiment.suite === "recovery" && (
                      <label>
                        Recovery action
                        <select
                          value={experiment.recovery_action || "replace_track"}
                          onChange={(e) =>
                            setExperiment({
                              ...experiment,
                              recovery_action: e.target.value,
                            })
                          }
                        >
                          <option value="replace_track">
                            Unpublish and replace track
                          </option>
                          <option value="reconnect">
                            Publisher leaves and reconnects
                          </option>
                          <option value="pause">
                            Pause and resume frame delivery
                          </option>
                        </select>
                      </label>
                    )}
                    <label>
                      Corpus
                      <select
                        value={experiment.corpus_id || ""}
                        onChange={(e) =>
                          setExperiment({
                            ...experiment,
                            corpus_id: e.target.value || undefined,
                            image_ids: [],
                          })
                        }
                      >
                        <option value="">Synthetic Segno fixtures</option>
                        {boot?.corpora.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name} · {c.cases} cases
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="note">
                      Synthetic fixtures are independent Segno codes. A
                      real-world claim needs an independently labelled corpus.
                    </p>
                    <label className="upload">
                      Import labelled corpus ZIP
                      <input
                        type="file"
                        accept=".zip"
                        onChange={(e) =>
                          upload(e.target.files, "corpora", true)
                        }
                      />
                    </label>
                    <p className="note">
                      {corpusName ||
                        "manifest.json + images · name, version, source, license, split, exact payloads, optional checksums."}
                    </p>
                    <label className="upload">
                      Use image batch
                      <input
                        type="file"
                        multiple
                        accept="image/png,image/jpeg"
                        onChange={(e) => upload(e.target.files, "images", true)}
                      />
                    </label>
                    <label>
                      Expected payloads (one per line; applies to uploaded
                      images)
                      <textarea
                        value={expectedText}
                        onChange={(e) => {
                          setExpectedText(e.target.value);
                          setExperiment({
                            ...experiment,
                            expected: e.target.value
                              ? e.target.value.split("\n")
                              : null,
                          });
                        }}
                        placeholder="Leave blank for unscored"
                      />
                    </label>
                    <button
                      className="quiet"
                      onClick={() =>
                        setExperiment({ ...experiment, expected: [] })
                      }
                    >
                      Mark uploaded inputs as no-code negatives
                    </button>
                    <button
                      className="quiet"
                      onClick={() => {
                        setExperiment({
                          ...experiment,
                          corpus_id: undefined,
                          image_ids: [],
                        });
                        setCorpusName("");
                      }}
                    >
                      Use synthetic corpus
                    </button>
                    <a href="/api/corpus-example" download>
                      Download corpus manifest example
                    </a>
                  </details>
                  <details>
                    <summary>Advanced measurement settings</summary>
                    <div className="form-grid">
                      {["video", "camera", "recording"].includes(
                        experiment.source,
                      ) && (
                        <NumberField
                          label="Decoder workers"
                          value={experiment.workers || 1}
                          min={1}
                          max={8}
                          onChange={(workers) =>
                            setExperiment({ ...experiment, workers })
                          }
                        />
                      )}
                      <NumberField
                        label="Operations / image attempt"
                        value={experiment.operations}
                        min={1}
                        max={10000}
                        onChange={(operations) =>
                          setExperiment({ ...experiment, operations })
                        }
                      />
                      <NumberField
                        label="Worker deadline (s)"
                        value={experiment.deadline_s}
                        min={2}
                        max={3700}
                        onChange={(deadline_s) =>
                          setExperiment({ ...experiment, deadline_s })
                        }
                      />
                      <NumberField
                        label="Maximum queue age (ms)"
                        value={experiment.max_queue_age_ms}
                        min={1}
                        max={10000}
                        onChange={(max_queue_age_ms) =>
                          setExperiment({ ...experiment, max_queue_age_ms })
                        }
                      />
                    </div>
                  </details>
                </fieldset>
              </section>
              <aside>
                <section className="panel targets">
                  <div className="panel-heading">
                    <h2>Acceptance targets</h2>
                    <span className="badge">Optional</span>
                  </div>
                  <p className="note">
                    Enter budgets before the run. Blank targets stay unrated.
                    Failures remain in the denominator.
                  </p>
                  <fieldset
                    className="protocol-fields"
                    disabled={active || busy}
                  >
                    {[
                      ["min_accuracy", "Minimum exact accuracy", "0–1"],
                      [
                        "max_false_detections",
                        "Maximum false detections",
                        "count",
                      ],
                      ["max_p95_ms", "Maximum frame / operation p95", "ms"],
                      ["min_rate", "Minimum processing rate", "/s"],
                      ["max_rss_mb", "Maximum worker RSS", "MiB"],
                      ["max_cpu_percent", "Maximum worker CPU", "%"],
                      ["max_queue_p95_ms", "Maximum queue age p95", "ms"],
                      ["max_recovery_ms", "Maximum recovery time", "ms"],
                    ].map(([key, label, unit]) => (
                      <label key={key}>
                        {label}
                        <div className="unit-input">
                          <input
                            type="number"
                            min="0"
                            step="any"
                            value={experiment.targets[key] ?? ""}
                            onChange={(e) => {
                              const targets = { ...experiment.targets };
                              if (e.target.value === "") delete targets[key];
                              else targets[key] = Number(e.target.value);
                              setExperiment({ ...experiment, targets });
                            }}
                            placeholder="Unrated"
                          />
                          <span>{unit}</span>
                        </div>
                      </label>
                    ))}
                  </fieldset>
                </section>
                <section className="panel protocol-review">
                  <div className="eyebrow">RUN REVIEW</div>
                  <h2>
                    {boot?.suites[experiment.suite]?.title ||
                      "Custom experiment"}
                  </h2>
                  <dl className="facts">
                    <div>
                      <dt>Source</dt>
                      <dd>{experiment.source}</dd>
                    </div>
                    <div>
                      <dt>Attempts (synthetic)</dt>
                      <dd>
                        {experiment.repetitions *
                          experiment.scenarios.length *
                          experiment.implementations.length *
                          experiment.loads.length}
                      </dd>
                    </div>
                    <div>
                      <dt>Order</dt>
                      <dd>Seeded interleaving</dd>
                    </div>
                    <div>
                      <dt>Ground truth</dt>
                      <dd>Evaluator only</dd>
                    </div>
                    <div>
                      <dt>Evidence</dt>
                      <dd>Inputs + raw events + results</dd>
                    </div>
                  </dl>
                  <p className="note">
                    Each attempt gets a fresh worker. Warmups run inside it
                    before measurement. AI requests use fresh conversations,
                    without cloud warmup.
                  </p>
                  <button
                    className={active ? "stop" : "primary"}
                    disabled={!boot || busy}
                    onClick={() => (active ? stop() : start(experiment))}
                  >
                    <Icon name={active ? "stop" : "play"} />
                    {busy
                      ? "Working…"
                      : active
                        ? "Stop experiment"
                        : "Run experiment"}
                  </button>
                  {status.run && (
                    <>
                      <progress
                        max={status.run.progress.total || 1}
                        value={status.run.progress.completed}
                      />
                      <p className="note">
                        {status.run.progress.completed} /{" "}
                        {status.run.progress.total} complete ·{" "}
                        {status.run.status}
                      </p>
                      <button
                        className="secondary"
                        onClick={async () => {
                          setReport(await api(`/api/runs/${status.run!.id}`));
                          location.hash = "reports";
                        }}
                      >
                        Open results
                      </button>
                    </>
                  )}
                </section>
                {active && (
                  <section className="panel">
                    <h2>Live worker</h2>
                    <p>
                      {names[live?.implementation || ""]} · {live?.scenario}
                    </p>
                    <dl className="facts">
                      <div>
                        <dt>Processing</dt>
                        <dd>{number(metrics.processed_rate)} /s</dd>
                      </div>
                      <div>
                        <dt>Tail latency</dt>
                        <dd>{number(metrics.p95_ms)} ms</dd>
                      </div>
                      <div>
                        <dt>Memory</dt>
                        <dd>{number(metrics.rss_mb)} MiB</dd>
                      </div>
                    </dl>
                  </section>
                )}
              </aside>
            </div>
            {status.run?.summary.length ? (
              <SummaryTable rows={status.run.summary} />
            ) : null}
          </>
        )}
        {tab === "reports" && (
          <>
            <section className="panel reports-toolbar">
              <label className="grow">
                Run
                <select
                  value={report?.id || ""}
                  onChange={async (e) => {
                    setReport(
                      e.target.value
                        ? await api(`/api/runs/${e.target.value}`)
                        : null,
                    );
                    setDetail(null);
                  }}
                >
                  <option value="">Select a saved run</option>
                  {history.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.created?.slice(0, 19).replace("T", " ")} ·{" "}
                      {r.suite || r.config?.suite} · {r.status} ·{" "}
                      {r.id.slice(0, 6)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grow">
                Compare with
                <select
                  value={baseline?.id || ""}
                  onChange={async (e) =>
                    setBaseline(
                      e.target.value
                        ? await api(`/api/runs/${e.target.value}`)
                        : null,
                    )
                  }
                >
                  <option value="">No comparison</option>
                  {history
                    .filter((r) => r.id !== report?.id)
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.created?.slice(0, 19)} · {r.id.slice(0, 6)}
                      </option>
                    ))}
                </select>
              </label>
            </section>
            {report ? (
              <>
                <div className="report-heading">
                  <div>
                    <h2>
                      {report.config?.suite} · {report.status}
                    </h2>
                    <p className="muted">
                      {report.id} · {report.created}
                    </p>
                  </div>
                  <div className="exports">
                    {["json", "csv", "html", "zip"].map((format) => (
                      <a
                        className="secondary"
                        key={format}
                        href={`/api/runs/${report.id}?format=${format}`}
                        download={`${report.id}.${format}`}
                      >
                        {format === "zip"
                          ? "Evidence ZIP"
                          : format.toUpperCase()}
                      </a>
                    ))}
                  </div>
                </div>
                {report.error && <p className="error">{report.error}</p>}
                {baseline && (
                  <Comparison current={report} baseline={baseline} />
                )}
                <SummaryTable rows={shownSummary} />
                {report.observer_overhead?.length ? (
                  <section className="panel">
                    <h2>Measured observer overhead</h2>
                    {report.observer_overhead.map((o) => (
                      <div className="callout" key={o.implementation}>
                        <strong>
                          {names[o.implementation]} ·{" "}
                          {number(o.median_overhead_percent)}%
                        </strong>
                        <p>
                          {o.pairs} matched pairs ·{" "}
                          {o.median_ci95
                            ? `${number(o.median_ci95[0])}–${number(o.median_ci95[1])}% median CI`
                            : "More pairs needed for a confidence interval"}
                        </p>
                        <p>{o.scope}</p>
                      </div>
                    ))}
                  </section>
                ) : null}
                {report.component_resource_peaks && (
                  <section className="panel">
                    <h2>Other process costs</h2>
                    <p className="note">
                      Sampled peaks during this run. These processes are
                      separate from the QR worker; browser and provider
                      infrastructure are excluded.
                    </p>
                    <div className="form-grid">
                      {Object.entries(report.component_resource_peaks).map(
                        ([name, values]) => (
                          <dl className="facts" key={name}>
                            <div>
                              <dt>{name.replaceAll("_", " ")}</dt>
                              <dd>
                                {number(values.cpu_percent)}% CPU ·{" "}
                                {number(values.rss_mb)} MiB
                              </dd>
                            </div>
                          </dl>
                        ),
                      )}
                    </div>
                  </section>
                )}
                <div className="callout">
                  Latency is conditional on the documented stage. Negative cases
                  use the full observation window. No-code durations, successful
                  first reads, models, scenarios, stream counts, and warm/cold
                  runs remain separate. Confidence intervals describe
                  independent attempts, not repeated frames.
                </div>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Attempts & failures</h2>
                    <span className="muted">
                      {report.attempts?.length || 0} retained
                    </span>
                  </div>
                  <div className="filter-bar">
                    <label className="grow">
                      Filter attempts
                      <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Implementation, scenario, outcome…"
                      />
                    </label>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={failuresOnly}
                        onChange={(e) => setFailuresOnly(e.target.checked)}
                      />
                      Failures only
                    </label>
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Implementation / model</th>
                          <th>Scenario</th>
                          <th>Outcome</th>
                          <th>Measured duration</th>
                          <th>Startup</th>
                          <th>Details</th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.attempts
                          ?.filter(
                            (a) =>
                              (!failuresOnly ||
                                a.status !== "completed" ||
                                !["correct", "unscored"].includes(a.score)) &&
                              `${a.implementation} ${a.scenario} ${a.score} ${a.status}`
                                .toLowerCase()
                                .includes(query.toLowerCase()),
                          )
                          .map((a) => (
                            <tr key={a.id}>
                              <td>
                                {names[a.implementation]}
                                <small>
                                  {a.model ||
                                    `${a.temperature} · ${a.streams} stream(s)`}
                                </small>
                              </td>
                              <td>{a.scenario}</td>
                              <td>
                                <span
                                  className={`badge ${a.score === "correct" ? "good" : ""}`}
                                >
                                  {a.score}
                                </span>
                                <small>{a.status}</small>
                              </td>
                              <td>{number(a.elapsed_ms)} ms</td>
                              <td>{number(a.startup_ms)} ms</td>
                              <td>
                                <button
                                  className="quiet"
                                  onClick={() => setDetail(a)}
                                >
                                  Inspect
                                </button>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </section>
                <details className="panel">
                  <summary>Environment, corpus, and limitations</summary>
                  <ul>
                    {report.limitations?.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                  <pre>
                    {JSON.stringify(
                      {
                        environment: report.environment,
                        corpus: report.corpus,
                        protocol: report.config,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </>
            ) : (
              <section className="panel empty-state">
                <Icon name="reports" />
                <h2>No report selected</h2>
                <p>Run a smoke experiment or select a saved run above.</p>
                <a className="secondary" href="#experiments">
                  Set up an experiment
                </a>
              </section>
            )}
          </>
        )}
      </main>
      <footer>
        <span>
          REED QR Bench{" "}
          <span className="muted">v{boot?.version || "0.2.0"}</span>
        </span>
        <span>Measured evidence. Explicit limits. Reproducible inputs.</span>
      </footer>
      {detail && report && (
        <div className="scrim" onClick={() => setDetail(null)}>
          <section
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Attempt evidence"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-heading">
              <h2>Attempt evidence</h2>
              <button
                autoFocus
                className="secondary"
                onClick={() => setDetail(null)}
              >
                Close
              </button>
            </div>
            <p>
              {names[detail.implementation]} · {detail.scenario} ·{" "}
              {detail.score}
            </p>
            <div className="two-column">
              <div>
                <h3>Expected</h3>
                <pre>{JSON.stringify(detail.expected, null, 2)}</pre>
              </div>
              <div>
                <h3>Returned</h3>
                <pre>{JSON.stringify(detail.payloads, null, 2)}</pre>
              </div>
            </div>
            {detail.error && <p className="error">{detail.error}</p>}
            <a
              href={`/api/runs/${report.id}/artifact/${detail.events_file}`}
              download
            >
              Download raw lifecycle and completion events
            </a>
            <pre>{JSON.stringify(detail, null, 2)}</pre>
          </section>
        </div>
      )}
      {settings && (
        <div className="scrim" onClick={() => setSettings(false)}>
          <section
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Integration settings"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-heading">
              <h2>Integrations</h2>
              <button
                autoFocus
                className="secondary"
                onClick={() => setSettings(false)}
              >
                Close
              </button>
            </div>
            <p>
              API keys stay in local host memory. You can also configure the
              local .env file.
            </p>
            {Object.keys(boot?.providers || {}).map((p) => (
              <label key={p}>
                {boot?.provider_specs[p].label || p} API key ·{" "}
                {boot?.providers[p] ? "configured" : "not configured"}
                <input
                  type="password"
                  autoComplete="off"
                  value={keys[p] || ""}
                  onChange={(e) => setKeys({ ...keys, [p]: e.target.value })}
                />
              </label>
            ))}
            <button
              className="primary"
              onClick={async () => {
                try {
                  await api(
                    "/api/settings",
                    Object.fromEntries(
                      Object.entries(keys).filter(([, v]) => v.trim()),
                    ),
                  );
                  setKeys({ openai: "", gemini: "" });
                  setKeyNotice("Keys saved in host memory.");
                  setBoot(await api("/api/bootstrap"));
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              Save keys for this session
            </button>
            <p role="status">{keyNotice}</p>
            <h3>Embed the same installed capability</h3>
            <p>
              The model receives a function declaration. Your host resolves the
              authorized image ID, invokes the plugin, and returns its
              structured result.
            </p>
            <pre>{`from reed_qr_tools import QRTools\n\ntools = QRTools(resolve_authorized_image)\nmodel_tools = [tools.declaration()]\nresult = await tools.invoke(name, arguments)\n# return result to the model\nawait tools.aclose()`}</pre>
            <p className="note">
              The Test bench and experiments use this installed package. The
              direct SDK path measures the wrapper overhead; OpenCV provides an
              independent decoder baseline. LiveKit transport is source
              infrastructure, not a competing QR decoder.
            </p>
          </section>
        </div>
      )}
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
