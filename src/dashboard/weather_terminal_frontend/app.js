const API_BASE = "http://localhost:8020";

const state = {
  snapshot: null,
  candidates: [],
  tail: null,
  selectedLane: "known_outcome",
  selectedCandidate: null,
  jobs: {},
  runningAction: "",
};

const $ = (id) => document.getElementById(id);

function text(value, fallback = "--") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(3);
  }
  return String(value);
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function make(tag, className = "", content = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== "") node.textContent = content;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `API request failed (${response.status})`);
  }
  return data;
}

function setError(message = "") {
  const line = $("errorLine");
  line.hidden = !message;
  line.textContent = message;
}

function statusClass(value) {
  const raw = String(value || "").toLowerCase();
  if (["fresh", "succeeded", "pass", "ready"].includes(raw)) return "fresh";
  if (["stale", "queued", "running", "provisional"].includes(raw)) return raw;
  if (["missing", "failed", "timed_out", "blocked", "hard_blocked"].includes(raw)) return raw;
  return "";
}

async function loadSnapshot() {
  state.snapshot = await api("/api/polymarket/weather/snapshot");
  renderSnapshot();
}

async function loadCandidates() {
  const lane = state.selectedLane === "replay" ? "evidence" : state.selectedLane;
  const data = await api(`/api/polymarket/weather/candidates?lane=${encodeURIComponent(lane)}&limit=100`);
  state.candidates = data.items || [];
  state.selectedCandidate = state.candidates[0] || null;
  renderCandidates();
  renderTicket();
}

async function loadTail() {
  const stream = $("streamSelect").value || "candidate_decisions";
  state.tail = await api(`/api/polymarket/weather/evidence/tail?stream=${encodeURIComponent(stream)}&limit=80`);
  renderTape();
}

async function loadAll() {
  setError("");
  await Promise.all([loadSnapshot(), loadCandidates(), loadTail()]);
}

function renderSnapshot() {
  const snapshot = state.snapshot || {};
  const summary = snapshot.summary || {};
  const live = snapshot.live_status || {};
  const qa = snapshot.qa_gate || {};

  $("modeValue").textContent = text(snapshot.operating_state, "loading");
  $("liveValue").textContent = text(live.status, "hard_blocked");
  $("marketsValue").textContent = text(summary.markets_scanned);
  $("routedValue").textContent = text(summary.routed_markets);
  $("replayValue").textContent = `${text(summary.tradeable_replay_count)} tradeable`;
  $("qaValue").textContent = text(summary.qa_status || qa.status, "blocked");
  $("qaValue").className = statusClass(summary.qa_status || qa.status);
  $("gateStatus").textContent = text(qa.status, "blocked");
  $("gateStatus").className = statusClass(qa.status);
  $("liveState").textContent = String(live.status || "LIVE HARD BLOCKED").toUpperCase();

  renderCommands(snapshot.actions || []);
  renderLanes(snapshot.lanes || []);
  renderArtifacts(Object.values(snapshot.artifacts || {}));
  renderReleaseGate(snapshot);
}

function renderCommands(actions) {
  const deck = $("commandDeck");
  clear(deck);
  actions.forEach((action) => {
    const button = make("button", "action-button", state.runningAction === action.id ? "Running" : action.label);
    button.type = "button";
    button.title = action.description || action.id;
    button.dataset.risk = action.risk || "read_only";
    button.disabled = !action.wired || state.runningAction === action.id;
    button.addEventListener("click", () => runAction(action.id));
    deck.appendChild(button);
  });
}

function renderLanes(lanes) {
  const list = $("laneList");
  clear(list);
  $("laneCount").textContent = String(lanes.length);
  lanes.forEach((lane) => {
    const apiLane = lane.id === "replay" ? "evidence" : lane.id;
    const button = make("button", `lane-button ${state.selectedLane === apiLane ? "active" : ""}`);
    button.type = "button";
    button.appendChild(make("span", "", lane.label || lane.id));
    button.appendChild(make("strong", "", text(lane.status)));
    button.appendChild(make("small", "", `${text(lane.count)} signals / ${text(lane.markets)} markets`));
    button.addEventListener("click", async () => {
      state.selectedLane = apiLane;
      await Promise.all([loadCandidates(), loadTail()]).catch((error) => setError(error.message));
      renderLanes(state.snapshot?.lanes || []);
    });
    list.appendChild(button);
  });
}

function renderCandidates() {
  const body = $("candidateRows");
  clear(body);
  $("candidateCount").textContent = String(state.candidates.length);

  if (state.candidates.length === 0) {
    const row = make("tr");
    const cell = make("td", "", "No candidates found for this lane.");
    cell.colSpan = 6;
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  state.candidates.forEach((candidate, index) => {
    const row = make("tr", state.selectedCandidate === candidate ? "selected" : "");
    row.addEventListener("click", () => {
      state.selectedCandidate = candidate;
      renderCandidates();
      renderTicket();
    });
    [
      candidate.status,
      candidate.side,
      candidate.station_id,
      candidate.fill_status,
      candidate.edge_after_cost,
      candidate.question || candidate.market_id || `candidate ${index + 1}`,
    ].forEach((value) => row.appendChild(make("td", "", text(value))));
    body.appendChild(row);
  });
}

function renderTicket() {
  const candidate = state.selectedCandidate || {};
  const qa = state.snapshot?.qa_gate || {};
  $("ticketLane").textContent = text(candidate.lane || state.selectedLane || "QA").toUpperCase();
  $("ticketMarket").textContent = text(candidate.market_id, "No selected market");
  $("ticketQuestion").textContent = text(candidate.question, "Waiting for candidate data.");

  renderLines($("proofLines"), candidate.proof || [], "No proof lines available.");
  renderLines($("disproofLines"), candidate.disproof || [], "Waiting on replay or lane disproof.");

  const blockers = candidate.blockers?.length ? candidate.blockers : qa.blockers || [];
  const blockerList = $("blockerList");
  clear(blockerList);
  blockers.slice(0, 10).forEach((blocker) => blockerList.appendChild(make("span", "blocker", text(blocker))));
}

function renderLines(target, lines, emptyText) {
  clear(target);
  if (!lines || lines.length === 0) {
    target.appendChild(make("p", "", emptyText));
    return;
  }
  lines.slice(0, 5).forEach((line) => target.appendChild(make("p", "", text(line))));
}

function renderArtifacts(artifacts) {
  const list = $("artifactList");
  clear(list);
  $("artifactCount").textContent = String(artifacts.length);
  artifacts.forEach((artifact) => {
    const row = make("div", "artifact-row");
    row.appendChild(make("span", "", artifact.label || artifact.key));
    row.appendChild(make("strong", statusClass(artifact.freshness), text(artifact.freshness)));
    row.appendChild(make("small", "", artifact.age_hours === null ? "missing" : `${artifact.age_hours}h`));
    list.appendChild(row);
  });
}

function renderReleaseGate(snapshot) {
  const body = $("releaseBody");
  clear(body);
  const live = snapshot.live_status || {};
  const qa = snapshot.qa_gate || {};
  const certificate = live.release_certificate || {};
  const evidence = live.evidence || {};
  const lines = [
    `State chain: ${(snapshot.mode_chain || []).join(" -> ")}`,
    `Live allow flag: ${text(live.allow_live_weather_trading, "false")}`,
    `Release certificate: ${text(certificate.status, "missing")} / present=${text(certificate.present, "false")}`,
    `Evidence live accepted: ${text(evidence.accepted_for_live_weather_trading, "false")}`,
    `QA blockers: ${(qa.blockers || []).length}`,
  ];
  lines.forEach((line) => body.appendChild(make("p", "", line)));
  (live.blockers || []).slice(0, 8).forEach((blocker) => body.appendChild(make("span", "blocker", text(blocker))));
}

function renderTape() {
  const tape = $("tapeList");
  clear(tape);
  const items = state.tail?.items || [];
  if (items.length === 0) {
    tape.appendChild(make("pre", "", `No rows in ${state.tail?.stream || $("streamSelect").value}.`));
    return;
  }
  items.slice(-8).reverse().forEach((item) => {
    tape.appendChild(make("pre", "", JSON.stringify(item, null, 2)));
  });
}

function renderJobs() {
  const list = $("jobList");
  clear(list);
  const jobs = Object.values(state.jobs).slice(-5).reverse();
  jobs.forEach((job) => {
    const row = make("div", "job-row");
    row.appendChild(make("span", "", job.action));
    row.appendChild(make("strong", statusClass(job.status), job.status));
    row.appendChild(make("small", "", job.message || job.job_id));
    list.appendChild(row);
  });
}

async function runAction(actionId) {
  state.runningAction = actionId;
  renderCommands(state.snapshot?.actions || []);
  setError("");
  try {
    const job = await api(`/api/polymarket/weather/actions/${encodeURIComponent(actionId)}`, { method: "POST" });
    state.jobs[job.job_id] = job;
    renderJobs();
    if (["queued", "running"].includes(job.status)) {
      pollJob(job.job_id);
    } else {
      state.runningAction = "";
      renderCommands(state.snapshot?.actions || []);
      await Promise.all([loadSnapshot(), loadTail()]);
    }
  } catch (error) {
    state.runningAction = "";
    renderCommands(state.snapshot?.actions || []);
    setError(error.message);
  }
}

function pollJob(jobId) {
  const timer = window.setInterval(async () => {
    try {
      const job = await api(`/api/polymarket/weather/actions/${encodeURIComponent(jobId)}`);
      state.jobs[job.job_id] = job;
      renderJobs();
      if (!["queued", "running"].includes(job.status)) {
        window.clearInterval(timer);
        state.runningAction = "";
        await Promise.all([loadSnapshot(), loadTail()]);
      }
    } catch (error) {
      window.clearInterval(timer);
      state.runningAction = "";
      setError(error.message);
      renderCommands(state.snapshot?.actions || []);
    }
  }, 2500);
}

$("syncViewButton").addEventListener("click", () => {
  loadAll().catch((error) => setError(error.message));
});

$("streamSelect").addEventListener("change", () => {
  loadTail().catch((error) => setError(error.message));
});

loadAll().catch((error) => setError(error.message));
