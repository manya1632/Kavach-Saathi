const AGENTS = {
  catalogue_truth: { number: "01", name: "Catalogue Truth" },
  spec_enforcer: { number: "02", name: "Spec Enforcer" },
  size_translator: { number: "03", name: "Size Translator" },
  review_filter: { number: "04", name: "Review Truth" },
  voice_qa: { number: "05", name: "Voice Q&A" },
  address_guardian: { number: "06", name: "Address Guardian" },
  delivery_confirmation: { number: "07", name: "Delivery Confirmation" },
  return_verifier: { number: "08", name: "Return Verifier" },
};

const FLOWS = {
  listing: {
    agents: ["catalogue_truth", "spec_enforcer"],
    path: "/v1/listings/analyze",
    body: {
      seller_id: "S-001",
      product_id: "P-001",
      image_keys: ["assets/mock/products/P-001.png"],
      seller_specs: {
        fabric: "60% Cotton, 40% Viscose",
        gsm: 150,
        color_hex: "#800000",
        wash_care: "Gentle hand wash",
      },
    },
  },
  voice: {
    agents: ["size_translator", "voice_qa"],
    path: "/v1/voice/query",
    body: {
      buyer_id: "B-001",
      product_id: "P-001",
      text: "Mujhe kaunsa size lena chahiye?",
      language: "hi",
    },
  },
  review: {
    agents: ["review_filter"],
    path: "/v1/reviews/analyze",
    body: {
      review_id: "RV-BAD",
      product_id: "P-001",
      image_key: "assets/mock/reviews/RV-BAD.png",
    },
  },
  address: {
    agents: ["address_guardian"],
    path: "/v1/address/verify",
    body: {
      buyer_id: "B-001",
      raw_address: "Hanuman Mandir ke peeche, gali no. 3, Bilaspur",
      postal_pin: "495001",
      coordinates: { latitude: 22.0797, longitude: 82.1409 },
    },
  },
  confirmation: {
    agents: ["delivery_confirmation"],
    path: "/v1/orders/O-GOLDEN/confirm-simulated",
    body: { decision: "confirmed" },
  },
  return: {
    agents: ["return_verifier"],
    path: "/v1/returns/analyze",
    body: {
      order_id: "O-GOLDEN",
      video_key: "assets/mock/returns/return-approve.mp4",
      additional_image_keys: [],
    },
  },
};

const FLOW_ORDER = ["listing", "voice", "review", "address", "confirmation", "return"];
const state = { results: new Map(), evidence: 0, startedAt: 0, running: false };

const $ = (selector) => document.querySelector(selector);
const all = (selector) => [...document.querySelectorAll(selector)];

function setChip(agent, status) {
  const chip = document.querySelector(`[data-agent="${agent}"]`);
  if (!chip) return;
  chip.classList.remove("running", "done");
  if (status) chip.classList.add(status);
}

function reset() {
  state.results.clear();
  state.evidence = 0;
  state.running = false;
  all(".agent-chip").forEach((chip) => chip.classList.remove("running", "done"));
  $("#result-list").replaceChildren();
  $("#empty-state").classList.remove("hidden");
  $("#summary-strip").classList.add("hidden");
  $("#run-all").disabled = false;
  $("#run-all span:last-child").textContent = "Run all 8 agents";
}

function updateSummary() {
  $("#empty-state").classList.add("hidden");
  $("#summary-strip").classList.remove("hidden");
  $("#completed-count").textContent = state.results.size;
  $("#evidence-count").textContent = state.evidence;
  $("#elapsed-time").textContent = `${((performance.now() - state.startedAt) / 1000).toFixed(1)}s`;
}

function renderResult(agentKey, result) {
  if (state.results.has(agentKey)) return;
  state.results.set(agentKey, result);
  state.evidence += result.evidence?.length || 0;
  const meta = AGENTS[agentKey] || { number: "–", name: agentKey.replaceAll("_", " ") };
  const action = result.actions?.[0]?.label;
  const card = document.createElement("article");
  card.className = "result-card";
  card.innerHTML = `
    <div class="result-number">${meta.number}</div>
    <div class="result-copy">
      <strong>${meta.name}</strong>
      <p>${result.summary}</p>
      ${action ? `<span class="result-action">${action}</span>` : ""}
    </div>
    <div class="confidence">
      <strong>${result.confidence}%</strong>
      <small>evidence strength</small>
      <div class="confidence-bar"><span style="width:${result.confidence}%"></span></div>
    </div>`;
  $("#result-list").append(card);
  setChip(agentKey, "done");
  updateSummary();
}

async function runFlow(flowName, keepExisting = false) {
  if (state.running && !keepExisting) return;
  if (!keepExisting) {
    reset();
    state.startedAt = performance.now();
    state.running = true;
    $("#decision-badge").textContent = "Running";
    $("#decision-badge").className = "decision-badge";
  }
  const flow = FLOWS[flowName];
  let succeeded = false;
  flow.agents.forEach((agent) => setChip(agent, "running"));
  updateSummary();
  try {
    const response = await fetch(flow.path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(flow.body),
    });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const payload = await response.json();
    Object.entries(payload.results).forEach(([agent, result]) => renderResult(agent, result));
    succeeded = true;
    return payload;
  } catch (error) {
    flow.agents.forEach((agent) => setChip(agent));
    $("#decision-badge").textContent = "Error";
    $("#decision-badge").className = "decision-badge error";
    throw error;
  } finally {
    if (!keepExisting) {
      state.running = false;
      $("#decision-badge").textContent = succeeded ? "Complete" : "Check failed";
      $("#decision-badge").className = succeeded ? "decision-badge complete" : "decision-badge error";
      updateSummary();
    }
  }
}

async function runAll() {
  if (state.running) return;
  reset();
  state.startedAt = performance.now();
  state.running = true;
  $("#run-all").disabled = true;
  $("#run-all span:last-child").textContent = "Agents are working…";
  $("#decision-badge").textContent = "Running";
  $("#decision-badge").className = "decision-badge";
  updateSummary();
  try {
    for (const flowName of FLOW_ORDER) await runFlow(flowName, true);
    $("#decision-badge").textContent = "Journey verified";
    $("#decision-badge").className = "decision-badge complete";
  } catch (error) {
    $("#decision-badge").textContent = "Check failed";
    $("#decision-badge").className = "decision-badge error";
  } finally {
    state.running = false;
    $("#run-all").disabled = false;
    $("#run-all span:last-child").textContent = "Run all 8 agents";
    updateSummary();
  }
}

async function askGroq(event) {
  event.preventDefault();
  if (state.running) return;
  const question = $("#question").value.trim();
  if (!question) return;
  reset();
  state.startedAt = performance.now();
  state.running = true;
  $("#ask-button").disabled = true;
  $("#ask-button").textContent = "Thinking…";
  $("#decision-badge").textContent = "Groq reasoning";
  $("#decision-badge").className = "decision-badge";
  setChip("voice_qa", "running");
  updateSummary();
  try {
    const response = await fetch("/v1/voice/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        buyer_id: "B-001",
        product_id: "P-001",
        text: question,
        language: "hi",
      }),
    });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const payload = await response.json();
    Object.entries(payload.results).forEach(([agent, result]) => renderResult(agent, result));
    $("#decision-badge").textContent = "Groq answered";
    $("#decision-badge").className = "decision-badge complete";
  } catch {
    setChip("voice_qa");
    $("#decision-badge").textContent = "Groq unavailable";
    $("#decision-badge").className = "decision-badge error";
  } finally {
    state.running = false;
    $("#ask-button").disabled = false;
    $("#ask-button").textContent = "Ask Groq";
    updateSummary();
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    if (!response.ok) throw new Error();
    const health = await response.json();
    const reasoning = health.checks.reasoning === "groq" ? "Groq reasoning" : "fixture rules";
    $("#server-status").classList.add("online");
    $("#status-text").textContent = `${health.mode} data · ${reasoning} · ${health.agents} agents`;
  } catch {
    $("#server-status").classList.add("offline");
    $("#status-text").textContent = "Server unavailable";
  }
}

$("#run-all").addEventListener("click", runAll);
$("#reset").addEventListener("click", reset);
$("#ask-form").addEventListener("submit", askGroq);
all(".agent-chip").forEach((chip) => chip.addEventListener("click", () => runFlow(chip.dataset.flow)));
checkHealth();
