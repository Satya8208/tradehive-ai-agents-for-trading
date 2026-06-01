// Live Blackjack Table — frontend

const PREFS_KEY = "tradehive-live-blackjack-prefs";

function loadPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return { showTotals: false, showShoeMath: false };
    const parsed = JSON.parse(raw);
    return {
      showTotals: Boolean(parsed.showTotals),
      showShoeMath: Boolean(parsed.showShoeMath),
    };
  } catch {
    return { showTotals: false, showShoeMath: false };
  }
}

const state = {
  snapshot: null,
  busy: false,
  betPending: 0,
  humanSeatIndex: null,
  displayPnl: 0,
  statusMessage: "",
  suitCache: new Map(),
  prefs: loadPrefs(),
};

// ---------- Utility ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const SUITS = ["♠", "♥", "♦", "♣"];

function createCard(rank, suit) {
  const div = document.createElement("div");
  if (rank === "__BACK__") {
    div.className = "card back";
    div.dataset.rank = "__BACK__";
    div.innerHTML = '<span class="rank-tl"></span><span class="suit-center"></span><span class="rank-br"></span>';
    return div;
  }
  const isRed = suit === "♥" || suit === "♦";
  div.className = "card" + (isRed ? " red" : "");
  div.dataset.rank = rank;
  div.dataset.suit = suit;
  div.setAttribute("aria-label", `${rank}${suit}`);
  div.innerHTML = `
    <span class="rank-tl">${rank}</span>
    <span class="suit-center">${suit}</span>
    <span class="rank-br">${rank}</span>
  `;
  return div;
}

function hasCents(v) {
  return Math.abs(v - Math.round(v)) > 0.004;
}

function fmtMoney(v, { showPlus = false } = {}) {
  const amount = Number(v) || 0;
  const sign = amount < 0 ? "-" : showPlus && amount > 0 ? "+" : "";
  const abs = Math.abs(amount);
  const digits = hasCents(abs) ? 2 : 0;
  return sign + "$" + abs.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: 2,
  });
}

function fmtSigned(value, digits = 1) {
  const amount = Number(value) || 0;
  const sign = amount >= 0 ? "+" : "";
  return `${sign}${amount.toFixed(digits)}`;
}

function hashString(input) {
  let hash = 0;
  for (let i = 0; i < input.length; i += 1) {
    hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

function getStableSuit(slotKey, rank) {
  if (!rank || rank === "__BACK__") return "";
  const roundKey = state.snapshot?.hand_number ?? 0;
  const cacheKey = `${roundKey}:${slotKey}:${rank}`;
  if (!state.suitCache.has(cacheKey)) {
    state.suitCache.set(cacheKey, SUITS[hashString(cacheKey) % SUITS.length]);
  }
  return state.suitCache.get(cacheKey);
}

function blackjackPayText(pays) {
  if (Math.abs(pays - 1.5) < 0.001) return "3 TO 2";
  if (Math.abs(pays - 1.2) < 0.001) return "6 TO 5";
  return `${(pays + 1).toFixed(2)} TOTAL`;
}

function renderRules(rules) {
  if (!rules) return;
  const main = $("#rules-main-copy");
  const sub = $("#rules-sub-copy");
  if (main) {
    main.textContent = `BLACKJACK PAYS ${blackjackPayText(rules.blackjack_pays)}`;
  }
  if (sub) {
    const soft17 = rules.dealer_hits_soft_17 ? "H17" : "S17";
    const surrender = rules.late_surrender ? "LATE SURRENDER" : "NO SURRENDER";
    const das = rules.double_after_split ? "DAS" : "NO DAS";
    sub.textContent = `${rules.num_decks} DECK SHOE · ${soft17} · ${das} · ${surrender}`;
  }
}

function renderTableTag(rules) {
  const tag = $("#table-tag");
  if (!tag || !rules) return;
  tag.textContent = `${rules.table_name || "LIVE BLACKJACK"} · ${rules.num_decks}D · ${rules.dealer_hits_soft_17 ? "H17" : "S17"}`;
}

function renderCoach(snap) {
  const coach = snap.coach || {};
  const count = coach.count || {};
  const feedback = coach.last_feedback;
  const recommendation = coach.current_recommendation;
  const insurance = coach.insurance_recommendation;

  $("#coach-system").textContent = (count.system || "hi_lo").replace(/_/g, "-").toUpperCase();
  $("#coach-rc").textContent = fmtSigned(count.running_count || 0, 1);
  $("#coach-tc").textContent = fmtSigned(count.true_count || 0, 1);
  $("#coach-edge").textContent = `${fmtSigned(count.edge || 0, 2)}%`;
  $("#coach-decks").textContent = `${Number(count.decks_remaining || 0).toFixed(1)}D`;

  const kickerEl = $("#coach-kicker");
  const actionEl = $("#coach-action");
  const sourceEl = $("#coach-source");
  const feedbackEl = $("#coach-feedback");
  const insuranceCoachEl = $("#insurance-coach");

  let kicker = "COUNT COACH";
  let action = "WAITING";
  let source = "Waiting for your next decision.";

  if (snap.phase === "insurance" && insurance) {
    kicker = "INSURANCE";
    action = insurance.recommended_action;
    source = `Count-based insurance check at TC ${fmtSigned(insurance.true_count || 0, 1)}.`;
    if (insuranceCoachEl) {
      insuranceCoachEl.textContent = `${insurance.recommended_action} at TC ${fmtSigned(insurance.true_count || 0, 1)}.`;
    }
  } else if (recommendation) {
    kicker = "IDEAL MOVE";
    action = recommendation.action;
    source = recommendation.source === "deviation"
      ? `Deviation at TC ${fmtSigned(recommendation.true_count || 0, 1)}.`
      : "Basic strategy play.";
    if (insuranceCoachEl) {
      insuranceCoachEl.textContent = "Coach says no insurance right now.";
    }
  } else if (snap.phase === "betting") {
    kicker = "BETTING";
    action = "WAITING FOR DEAL";
    source = "Count stays live across hands until the next shuffle.";
    if (insuranceCoachEl) {
      insuranceCoachEl.textContent = "Coach says no insurance right now.";
    }
  } else if (insuranceCoachEl) {
    insuranceCoachEl.textContent = "Coach says no insurance right now.";
  }

  kickerEl.textContent = kicker;
  actionEl.textContent = action;
  actionEl.dataset.action = action.toLowerCase().replace(/\s+/g, "-");
  sourceEl.textContent = source;

  if (feedback?.message) {
    feedbackEl.textContent = feedback.message;
    feedbackEl.dataset.tone = feedback.is_correct ? "correct" : "miss";
    feedbackEl.classList.remove("hidden");
  } else {
    feedbackEl.textContent = "";
    feedbackEl.dataset.tone = "";
    feedbackEl.classList.add("hidden");
  }
}

function renderShoeDisplay(snap) {
  const shoe = snap.shoe || {};
  const decksLeft = Number(shoe.decks_remaining || 0).toFixed(1);
  const fill = $("#shoe-meter-fill");
  const cut = $("#shoe-cut-marker");
  if (fill) {
    fill.style.width = `${Math.max(0, Math.min((shoe.discard_tray_ratio || 0) * 100, 100))}%`;
  }
  if (cut) {
    cut.style.left = `${Math.max(0, Math.min((shoe.cut_card_ratio || 0) * 100, 100))}%`;
  }

  const summary = $("#stat-shoe");
  if (!summary) return;
  if (state.prefs.showShoeMath) {
    if (shoe.cut_card_reached) {
      summary.textContent = `CUT CARD · ${decksLeft}D LEFT`;
    } else {
      summary.textContent = `${decksLeft} DECKS LEFT`;
    }
    return;
  }
  summary.textContent = shoe.cut_card_reached
    ? "SHUFFLE NEXT HAND"
    : `${snap.rules?.num_decks ?? 0}D LIVE SHOE`;
}

function formatHandValueText(hand) {
  if (hand.is_bust) return "BUST";
  if (hand.is_blackjack) return "BJ";
  if (hand.is_surrendered) return "SURRENDER";
  if (!state.prefs.showTotals) return "";
  return hand.is_soft ? `soft ${hand.value}` : String(hand.value);
}

function makeHandRow(handIdx) {
  const row = document.createElement("div");
  row.className = "hand-row";
  row.dataset.handIdx = handIdx;
  row.innerHTML = '<div class="cards"></div><div class="hand-value"></div>';
  return row;
}

function normalizeHandRows(handGroup) {
  Array.from(handGroup.children).forEach((row, idx) => {
    row.dataset.handIdx = idx;
  });
}

function savePrefs() {
  localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs));
}

function togglePref(key) {
  state.prefs[key] = !state.prefs[key];
  savePrefs();
  renderPrefs();
  if (state.snapshot) {
    renderFromSnapshot(state.snapshot);
  }
}

function renderPrefs() {
  $("#btn-toggle-totals").classList.toggle("active", state.prefs.showTotals);
  $("#btn-toggle-shoe").classList.toggle("active", state.prefs.showShoeMath);
  $("#btn-toggle-totals").textContent = `TOTALS ${state.prefs.showTotals ? "ON" : "OFF"}`;
  $("#btn-toggle-shoe").textContent = `SHOE DATA ${state.prefs.showShoeMath ? "ON" : "OFF"}`;
}

function setTableStatus(message, tone = "error") {
  const el = $("#table-status");
  if (!el) return;
  state.statusMessage = message || "";
  if (!message) {
    el.textContent = "";
    el.dataset.tone = "";
    el.classList.add("hidden");
    return;
  }
  el.textContent = message;
  el.dataset.tone = tone;
  el.classList.remove("hidden");
}

// Approximate hand value from visible card ranks (UI-only; backend is authoritative)
function computeHandValue(cards) {
  let total = 0;
  let aces = 0;
  for (const c of cards) {
    if (!c || c === "__BACK__") continue;
    if (c === "A") { aces++; total += 11; }
    else if (c === "K" || c === "Q" || c === "J" || c === "T" || c === "10") total += 10;
    else total += parseInt(c, 10) || 0;
  }
  while (total > 21 && aces > 0) { total -= 10; aces--; }
  const isSoft = aces > 0 && total <= 21;
  return { value: total, isSoft };
}

// ---------- Rendering (full snapshot render — used for initial boot and final reconcile) ----------
function renderFromSnapshot(snap) {
  const previousHandNumber = state.snapshot?.hand_number ?? null;
  state.snapshot = snap;
  state.humanSeatIndex = snap.human_seat_index;
  state.displayPnl = snap.session_pnl;
  if (previousHandNumber !== null && previousHandNumber !== snap.hand_number) {
    state.suitCache.clear();
  }

  // Topbar
  $("#stat-hand").textContent = snap.hand_number || 0;
  updatePnL(snap.session_pnl);
  renderShoeDisplay(snap);

  const humanSeat = snap.seats[snap.human_seat_index];
  $("#stat-bank").textContent = fmtMoney(humanSeat.bankroll);
  const totalBet = humanSeat.hands?.length
    ? humanSeat.hands.reduce((sum, hand) => sum + (Number(hand.bet) || 0), 0)
    : Number(humanSeat.bet) || 0;
  $("#stat-bet").textContent = fmtMoney(
    snap.phase === "betting" && state.betPending > 0 ? state.betPending : totalBet,
  );
  setTableStatus("");

  // Speech
  $("#speech").textContent = snap.message || "";

  renderPrefs();
  renderRules(snap.rules);
  renderTableTag(snap.rules);
  renderCoach(snap);

  // Dealer
  renderDealer(snap.dealer);

  // Seats
  const container = $("#seats");
  container.innerHTML = "";
  for (const seat of snap.seats) {
    container.appendChild(buildSeatElement(seat, snap));
  }

  // Action area
  renderActionBar(snap);

  // Insurance modal
  if (snap.phase === "insurance") {
    $("#insurance-amount").textContent = fmtMoney(snap.insurance_offer_amount ?? 0);
    $("#insurance-modal").classList.remove("hidden");
  } else {
    $("#insurance-modal").classList.add("hidden");
  }
}

function renderDealer(dealer) {
  const el = $("#dealer-cards");
  el.innerHTML = "";
  for (const [idx, card] of dealer.cards.entries()) {
    const suit = getStableSuit(`dealer-${idx}`, card);
    el.appendChild(createCard(card, suit));
  }
  if (state.prefs.showTotals) {
    $("#dealer-value").textContent = dealer.value != null ? dealer.value : "";
  } else {
    $("#dealer-value").textContent = "";
  }
}

function buildSeatElement(seat, snap) {
  const div = document.createElement("div");
  div.className = "seat";
  div.dataset.seatIndex = seat.index;

  if (!seat.occupant) {
    div.classList.add("empty");
    div.innerHTML = `<div class="name">EMPTY SEAT</div>`;
    return div;
  }
  if (seat.is_human) div.classList.add("human");
  if (snap && snap.actor && snap.actor.seat === seat.index) div.classList.add("active");

  const nameHtml = `<div class="name">${seat.occupant}</div>`;
  const bankHtml = `<div class="bank">${fmtMoney(seat.bankroll)}</div>`;

  let handsHtml = "";
  if (!seat.hands || seat.hands.length === 0) {
    handsHtml = `<div class="hand-group"></div>`;
  } else {
    const handRows = seat.hands.map((h, idx) => {
      const isCurrent = snap && snap.actor && snap.actor.seat === seat.index && snap.actor.hand_idx === idx;
      const valTxt = formatHandValueText(h);
      const result = seat.results[idx];
      const resultTag = result
        ? `<div class="result-tag ${result.outcome}">${result.outcome} ${fmtMoney(result.payout, { showPlus: true })}</div>`
        : "";
      const doubledTag = state.prefs.showTotals && h.is_doubled ? " ×2" : "";
      const cardsInner = h.cards.map((c, cardIdx) => {
        const suit = getStableSuit(`seat-${seat.index}-hand-${idx}-card-${cardIdx}`, c);
        const tmp = createCard(c, suit);
        return tmp.outerHTML;
      }).join("");
      return `
        <div class="hand-row ${isCurrent ? "current" : ""}" data-hand-idx="${idx}">
          <div class="cards">${cardsInner}</div>
          <div class="hand-value">${valTxt}${doubledTag}</div>
          ${resultTag}
        </div>
      `;
    }).join("");
    handsHtml = `<div class="hand-group">${handRows}</div>`;
  }

  const betCircle = seat.bet > 0
    ? `<div class="bet-circle has-bet">${fmtMoney(seat.bet)}</div>`
    : `<div class="bet-circle">—</div>`;

  div.innerHTML = nameHtml + bankHtml + handsHtml + betCircle;
  return div;
}

function renderActionBar(snap) {
  const betBuilder = $("#bet-builder");
  const actionButtons = $("#action-buttons");
  const betweenRound = $("#between-round");

  betBuilder.classList.add("hidden");
  actionButtons.classList.add("hidden");
  betweenRound.classList.add("hidden");

  if (snap.phase === "betting") {
    betBuilder.classList.remove("hidden");
    $("#bet-amount").textContent = fmtMoney(state.betPending);
    const humanSeat = snap.seats[snap.human_seat_index];
    $("#btn-deal").disabled = (
      state.betPending < snap.min_bet
      || state.betPending > snap.max_bet
      || state.betPending > humanSeat.bankroll
    );
  } else if (snap.phase === "player_turn" && snap.actor && snap.actor.seat === snap.human_seat_index) {
    actionButtons.classList.remove("hidden");
    const allowed = snap.allowed_actions || {};
    $("#btn-hit").disabled = !allowed.hit;
    $("#btn-stand").disabled = !allowed.stand;
    $("#btn-double").disabled = !allowed.double;
    $("#btn-split").disabled = !allowed.split;
    $("#btn-surrender").disabled = !allowed.surrender;
  } else if (snap.phase === "payout" || snap.phase === "settle") {
    betweenRound.classList.remove("hidden");
  }
}

// ---------- Event player ----------
async function playEvents(events) {
  state.busy = true;
  document.body.classList.add("busy");
  // Hide the action bar controls during animation to prevent mid-animation clicks
  $("#action-buttons").classList.add("hidden");
  $("#between-round").classList.add("hidden");
  // Track PnL incrementally starting from whatever the user currently sees
  state.displayPnl = state.snapshot ? state.snapshot.session_pnl : 0;
  for (const ev of events) {
    await applyEvent(ev);
  }
  state.busy = false;
  document.body.classList.remove("busy");
}

async function applyEvent(ev) {
  switch (ev.type) {
    case "deal_card": {
      await animateDealCard(ev);
      await sleep(160);
      break;
    }
    case "reveal_hole": {
      await animateRevealHole(ev);
      updateDealerVisibleValue(false);
      await sleep(350);
      break;
    }
    case "action": {
      flashActionTag(ev.seat, ev.hand_idx, ev.action);
      await sleep(520);
      break;
    }
    case "bust": {
      flashActionTag(ev.seat, ev.hand_idx, "BUST");
      await sleep(420);
      break;
    }
    case "hand_result": {
      showResultTag(ev);
      updateSeatBankroll(ev.seat, ev.bankroll);
      if (ev.seat === state.humanSeatIndex) {
        state.displayPnl += ev.payout;
        updatePnL(state.displayPnl);
        $("#stat-bank").textContent = fmtMoney(ev.bankroll);
      }
      await sleep(260);
      break;
    }
    case "split": {
      animateSplit(ev);
      updateSeatBankroll(ev.seat, ev.bankroll);
      if (ev.seat === state.humanSeatIndex) {
        $("#stat-bank").textContent = fmtMoney(ev.bankroll);
      }
      await sleep(120);
      break;
    }
    case "bet_placed": {
      updateSeatBet(ev.seat, ev.amount);
      updateSeatBankroll(ev.seat, ev.bankroll);
      if (ev.seat === state.humanSeatIndex) {
        $("#stat-bank").textContent = fmtMoney(ev.bankroll);
      }
      await sleep(120);
      break;
    }
    case "seat_change": {
      updateSeatOccupant(ev.seat, ev.occupant, ev.is_human, ev.bankroll);
      await sleep(80);
      break;
    }
    case "phase": {
      if (ev.phase === "betting") {
        clearTableForNewRound();
      }
      break;
    }
    case "message": {
      $("#speech").textContent = ev.text;
      break;
    }
    case "shuffle": {
      $("#speech").textContent = "Shuffling the shoe…";
      await sleep(800);
      break;
    }
    case "insurance_placed":
    case "insurance_won":
    case "insurance_lost":
      // Silent for now
      break;
  }
}

function getSeatEl(seatIndex) {
  return document.querySelector(`.seat[data-seat-index="${seatIndex}"]`);
}

async function animateDealCard(ev) {
  if (ev.seat === "dealer") {
    const el = $("#dealer-cards");
    const cardIndex = el.children.length;
    const suit = getStableSuit(`dealer-${cardIndex}`, ev.card);
    el.appendChild(createCard(ev.card, suit));
    updateDealerVisibleValue(true);
    return;
  }
  const seatEl = getSeatEl(ev.seat);
  if (!seatEl) return;
  let handGroup = seatEl.querySelector(".hand-group");
  if (!handGroup) {
    handGroup = document.createElement("div");
    handGroup.className = "hand-group";
    seatEl.insertBefore(handGroup, seatEl.querySelector(".bet-circle"));
  }
  while (handGroup.children.length <= ev.hand_idx) {
    handGroup.appendChild(makeHandRow(handGroup.children.length));
  }
  const row = handGroup.children[ev.hand_idx];
  const cardsEl = row.querySelector(".cards");
  const cardIndex = cardsEl.children.length;
  const suit = getStableSuit(`seat-${ev.seat}-hand-${ev.hand_idx}-card-${cardIndex}`, ev.card);
  cardsEl.appendChild(createCard(ev.card, suit));
  updateHandValueFromRow(row);
}

async function animateRevealHole(ev) {
  const dealerCards = $("#dealer-cards");
  const backs = dealerCards.querySelectorAll(".card.back");
  if (backs.length === 0) return;
  const backEl = backs[backs.length - 1];
  const cardIndex = Array.from(dealerCards.children).indexOf(backEl);
  const suit = getStableSuit(`dealer-${cardIndex}`, ev.card);
  const newCard = createCard(ev.card, suit);
  backEl.replaceWith(newCard);
}

function animateSplit(ev) {
  const seatEl = getSeatEl(ev.seat);
  if (!seatEl) return;
  let handGroup = seatEl.querySelector(".hand-group");
  if (!handGroup) {
    handGroup = document.createElement("div");
    handGroup.className = "hand-group";
    seatEl.insertBefore(handGroup, seatEl.querySelector(".bet-circle"));
  }
  const sourceRow = handGroup.children[ev.hand_idx];
  if (!sourceRow) return;
  const sourceCards = sourceRow.querySelector(".cards");
  const movedCard = sourceCards?.lastElementChild;
  if (!movedCard) return;

  const newRow = makeHandRow(ev.new_hand_idx);
  const insertBefore = handGroup.children[ev.new_hand_idx] || null;
  handGroup.insertBefore(newRow, insertBefore);
  newRow.querySelector(".cards").appendChild(movedCard);
  normalizeHandRows(handGroup);
  updateHandValueFromRow(sourceRow);
  updateHandValueFromRow(newRow);
}

function flashActionTag(seatIdx, handIdx, text) {
  const seatEl = getSeatEl(seatIdx);
  if (!seatEl) return;
  // Prefer per-hand-row tag (important for split scenarios)
  if (handIdx != null) {
    const rows = seatEl.querySelectorAll(".hand-row");
    const row = rows[handIdx];
    if (row) {
      let tag = row.querySelector(".action-tag");
      if (!tag) {
        tag = document.createElement("div");
        tag.className = "action-tag";
        row.appendChild(tag);
      }
      tag.textContent = text;
      return;
    }
  }
  // Fallback seat-level
  let tag = seatEl.querySelector(":scope > .action-tag");
  if (!tag) {
    tag = document.createElement("div");
    tag.className = "action-tag";
    seatEl.appendChild(tag);
  }
  tag.textContent = text;
}

function showResultTag(ev) {
  const seatEl = getSeatEl(ev.seat);
  if (!seatEl) return;
  const row = seatEl.querySelectorAll(".hand-row")[ev.hand_idx];
  if (!row) return;
  const existing = row.querySelector(".result-tag");
  if (existing) existing.remove();
  const tag = document.createElement("div");
  tag.className = "result-tag " + ev.outcome;
  tag.textContent = `${ev.outcome} ${fmtMoney(ev.payout, { showPlus: true })}`;
  row.appendChild(tag);
}

// ---------- Incremental DOM helpers (no snapshot reads) ----------
function updateSeatBet(seatIdx, amount) {
  const el = getSeatEl(seatIdx);
  if (!el) return;
  const circle = el.querySelector(".bet-circle");
  if (!circle) return;
  if (amount > 0) {
    circle.className = "bet-circle has-bet";
    circle.textContent = fmtMoney(amount);
  } else {
    circle.className = "bet-circle";
    circle.textContent = "—";
  }
}

function updateSeatBankroll(seatIdx, bankroll) {
  const el = getSeatEl(seatIdx);
  if (!el) return;
  const bank = el.querySelector(".bank");
  if (bank) bank.textContent = fmtMoney(bankroll);
}

function updateSeatOccupant(seatIdx, occupant, isHuman, bankroll) {
  const el = getSeatEl(seatIdx);
  if (!el) return;
  el.className = "seat";
  el.dataset.seatIndex = seatIdx;
  if (!occupant) {
    el.classList.add("empty");
    el.innerHTML = `<div class="name">EMPTY SEAT</div>`;
    return;
  }
  if (isHuman) el.classList.add("human");
  el.innerHTML =
    `<div class="name">${occupant}</div>` +
    `<div class="bank">${fmtMoney(bankroll)}</div>` +
    `<div class="hand-group"></div>` +
    `<div class="bet-circle">—</div>`;
}

function clearTableForNewRound() {
  // Clear dealer
  $("#dealer-cards").innerHTML = "";
  $("#dealer-value").textContent = "";
  // Clear per-seat dynamic content
  for (const seatEl of $$(".seat")) {
    seatEl.classList.remove("active");
    const hg = seatEl.querySelector(".hand-group");
    if (hg) hg.innerHTML = "";
    const circle = seatEl.querySelector(".bet-circle");
    if (circle) {
      circle.className = "bet-circle";
      circle.textContent = "—";
    }
    // Remove seat-level action/result tags
    seatEl.querySelectorAll(":scope > .action-tag, :scope > .result-tag").forEach(t => t.remove());
  }
}

function updateHandValueFromRow(row) {
  const cards = Array.from(row.querySelectorAll(".card")).map(c => c.dataset.rank || "");
  const { value, isSoft } = computeHandValue(cards);
  const label = row.querySelector(".hand-value");
  if (!label) return;
  if (value > 21) label.textContent = "BUST";
  else if (cards.length === 0) label.textContent = "";
  else if (cards.length === 2 && value === 21) label.textContent = "BJ";
  else if (!state.prefs.showTotals) label.textContent = "";
  else label.textContent = isSoft ? `soft ${value}` : String(value);
}

function updateDealerVisibleValue(hideHoleIfPresent) {
  if (!state.prefs.showTotals) {
    $("#dealer-value").textContent = "";
    return;
  }
  const cardEls = $("#dealer-cards").querySelectorAll(".card");
  const ranks = Array.from(cardEls).map(c => c.dataset.rank || "");
  const hasHole = ranks.includes("__BACK__");
  let visibleRanks;
  if (hideHoleIfPresent && hasHole) {
    visibleRanks = ranks.filter(r => r !== "__BACK__");
  } else {
    visibleRanks = ranks.filter(r => r !== "__BACK__");
  }
  if (visibleRanks.length === 0) {
    $("#dealer-value").textContent = "";
    return;
  }
  const { value } = computeHandValue(visibleRanks);
  $("#dealer-value").textContent = value > 21 ? "BUST" : String(value);
}

function updatePnL(pnl) {
  const pnlEl = $("#stat-pnl");
  pnlEl.textContent = fmtMoney(pnl, { showPlus: true });
  pnlEl.className = pnl > 0 ? "pos" : pnl < 0 ? "neg" : "";
}

// ---------- API calls ----------
async function api(path, { method = "GET", body } = {}) {
  try {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = data?.detail || `Request failed (${res.status})`;
      console.error("API error:", path, res.status, detail);
      setTableStatus(`Table request failed. ${detail}`, "error");
      return null;
    }
    return data;
  } catch (error) {
    console.error("Network error:", path, error);
    setTableStatus("Table connection failed. Reload the page or restart the local server.", "warning");
    return null;
  }
}

async function refreshState() {
  const data = await api("/state");
  if (!data) return;
  state.humanSeatIndex = data.snapshot.human_seat_index;
  renderFromSnapshot(data.snapshot);
}

async function callEndpoint(path, body = undefined, method = "POST") {
  if (state.busy) return;
  const data = await api(path, { method, body });
  if (!data) return;
  state.humanSeatIndex = data.snapshot.human_seat_index;
  await playEvents(data.events || []);
  // Final reconcile — DOM should already match but this guarantees consistency.
  renderFromSnapshot(data.snapshot);
}

// ---------- Bet builder ----------
function resetBet() {
  state.betPending = 0;
  $("#bet-amount").textContent = fmtMoney(0);
  $("#stat-bet").textContent = fmtMoney(0);
  if (state.snapshot) renderActionBar(state.snapshot);
}

function addChip(val) {
  if (!state.snapshot || state.snapshot.phase !== "betting") return;
  const humanSeat = state.snapshot.seats[state.snapshot.human_seat_index];
  const newBet = state.betPending + val;
  if (newBet > humanSeat.bankroll) return;
  if (newBet > state.snapshot.max_bet) return;
  state.betPending = newBet;
  $("#bet-amount").textContent = fmtMoney(state.betPending);
  $("#stat-bet").textContent = fmtMoney(state.betPending);
  renderActionBar(state.snapshot);
}

// ---------- Wiring ----------
function wire() {
  $$(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const v = btn.dataset.val;
      if (v === "clear") resetBet();
      else addChip(parseInt(v, 10));
    });
  });

  $("#btn-deal").addEventListener("click", async () => {
    if (state.betPending <= 0) return;
    const bet = state.betPending;
    state.betPending = 0;
    await callEndpoint("/start_round", { bet });
  });

  $("#btn-hit").addEventListener("click", () => callEndpoint("/action", { action: "H" }));
  $("#btn-stand").addEventListener("click", () => callEndpoint("/action", { action: "S" }));
  $("#btn-double").addEventListener("click", () => callEndpoint("/action", { action: "D" }));
  $("#btn-split").addEventListener("click", () => callEndpoint("/action", { action: "P" }));
  $("#btn-surrender").addEventListener("click", () => callEndpoint("/action", { action: "R" }));

  $("#btn-next").addEventListener("click", () => callEndpoint("/next_round"));

  $("#btn-insurance-yes").addEventListener("click", () => callEndpoint("/insurance", { take: true }));
  $("#btn-insurance-no").addEventListener("click", () => callEndpoint("/insurance", { take: false }));
  $("#btn-toggle-totals").addEventListener("click", () => togglePref("showTotals"));
  $("#btn-toggle-shoe").addEventListener("click", () => togglePref("showShoeMath"));

  $("#btn-reset").addEventListener("click", async () => {
    if (!confirm("Reset the session? This will restore your $1,000 bankroll and shuffle a new shoe.")) return;
    await callEndpoint("/reset");
  });
}

// ---------- Boot ----------
(async function boot() {
  wire();
  renderPrefs();
  await refreshState();
})();
