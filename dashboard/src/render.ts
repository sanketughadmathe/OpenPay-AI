// DOM rendering for all three views. No state here — main.ts owns state.

import type { AuditEvent, Explanation, Payment, Summary } from "./api";

declare const Chart: any;

// One accent plus cool neutrals; semantic colors only where the meaning is semantic.
const PALETTE = ["#5eead4", "#7dd3fc", "#8a95aa", "#65718a", "#4b5669"];
const FAILURE_COLORS: Record<string, string> = {
  TIMEOUT: "#fbbf24",
  PROVIDER_ERROR: "#f87171",
  PROVIDER_DOWN: "#f87171",
  DECLINED: "#fb923c",
  INSUFFICIENT_FUNDS: "#fb923c",
  NO_ELIGIBLE_PROVIDER: "#8a95aa",
};

export function el(tag: string, className?: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function badge(status: string): HTMLElement {
  const node = el("span", `badge ${status}`, status);
  return node;
}

export function fmtAmount(amount: number, currency: string): string {
  const formatted = amount.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency === "INR" ? `₹${formatted}` : `${currency} ${formatted}`;
}

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour12: false });
}

export function toast(message: string): void {
  const node = document.getElementById("toast") as HTMLElement;
  node.textContent = message;
  node.hidden = false;
  window.setTimeout(() => (node.hidden = true), 4000);
}

// ---- Overview ----

function kpi(label: string, value: string, sub?: string): HTMLElement {
  const card = el("div", "kpi");
  card.append(el("div", "kpi-label", label));
  card.append(el("div", "kpi-value", value));
  if (sub) card.append(el("div", "kpi-sub", sub));
  return card;
}

export function renderKpis(summary: Summary): void {
  const row = document.getElementById("kpi-row")!;
  row.replaceChildren();
  row.append(kpi("Payments", String(summary.totals.payments ?? 0)));
  row.append(kpi("Succeeded", String(summary.totals.succeeded ?? 0)));
  row.append(kpi("Failed", String(summary.totals.failed ?? 0)));
  row.append(kpi("Success %", `${Math.round(summary.success_rate * 1000) / 10}%`));
  // Seed mixes INR and USD — show the INR bucket, mention USD when present.
  const inr = summary.value_by_currency.INR ?? 0;
  const usd = summary.value_by_currency.USD;
  row.append(
    kpi(
      "Simulated value",
      `₹${inr.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`,
      usd ? `+ ${usd.toLocaleString("en-IN", { maximumFractionDigits: 2 })} USD` : "INR bucket"
    )
  );

  document.getElementById("overview-note")!.textContent =
    `${summary.totals.attempts ?? 0} attempts · ${summary.retry_count} retries · ${summary.totals.pending ?? 0} pending review`;
}

const chartState: Record<string, any> = {};

function upsertChart(
  key: string,
  canvasId: string,
  labels: string[],
  data: number[],
  formatter: (value: number) => string
): void {
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
  if (!canvas) return;
  if (chartState[key]) {
    chartState[key].data.labels = labels;
    chartState[key].data.datasets[0].data = data;
    chartState[key].data.datasets[0].backgroundColor = labels.map(
      (label, i) => FAILURE_COLORS[label] ?? PALETTE[i % PALETTE.length]
    );
    chartState[key].update();
    return;
  }
  chartState[key] = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          data,
          backgroundColor: labels.map((label, i) => FAILURE_COLORS[label] ?? PALETTE[i % PALETTE.length]),
          borderRadius: 4,
          maxBarThickness: 64,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          ticks: { color: "#65718a", font: { family: "Geist Mono, ui-monospace, monospace", size: 11 } },
          grid: { color: "rgba(36, 48, 67, 0.7)" },
          border: { display: false },
          beginAtZero: true,
        },
        x: {
          ticks: { color: "#8a95aa", font: { family: "Geist, system-ui, sans-serif", size: 12 } },
          grid: { display: false },
          border: { color: "#243043" },
        },
      },
      tooltip: { callbacks: { label: (ctx: any) => formatter(ctx.parsed.y) } },
    },
  });
}

export function renderCharts(summary: Summary): void {
  const providerIds = Object.keys(summary.per_provider);
  upsertChart(
    "providers",
    "chart-providers",
    providerIds,
    providerIds.map((id) => summary.per_provider[id].success_rate * 100),
    (v) => `${v.toFixed(1)}%`
  );

  const codes = Object.keys(summary.failure_codes);
  upsertChart(
    "failures",
    "chart-failures",
    codes,
    codes.map((c) => summary.failure_codes[c]),
    (v) => `${v} attempts`
  );
}

// ---- Transactions ----

export function renderTransactions(payments: Payment[]): void {
  const tbody = document.getElementById("tx-tbody")!;
  tbody.replaceChildren();
  for (const payment of payments) {
    const tr = el("tr", "clickable");
    tr.dataset.paymentId = payment.id;

    tr.append(
      el("td", undefined, payment.id.slice(-12)),
      el("td", undefined, payment.order_id),
      el("td", undefined, fmtAmount(payment.amount, payment.currency)),
      el("td", undefined, payment.payment_method)
    );

    const statusCell = el("td");
    statusCell.append(badge(payment.status));
    tr.append(statusCell);

    tr.append(
      el("td", undefined, payment.selected_provider ?? "—"),
      el("td", undefined, String(payment.attempt_count)),
      el("td", undefined, fmtTime(payment.created_at))
    );
    tbody.append(tr);
  }
  if (payments.length === 0) {
    const tr = el("tr");
    const td = el("td", "muted", "No payments match the filters.") as HTMLTableCellElement;
    td.colSpan = 8;
    tr.append(td);
    tbody.append(tr);
  }
}

// ---- Payment detail ----

export function renderDetailHeader(payment: Payment): void {
  const header = document.getElementById("detail-header")!;
  header.replaceChildren();
  const title = el("div", "detail-title");
  title.append(el("span", undefined, payment.id));
  title.append(badge(payment.status));
  header.append(title);

  const meta = el(
    "div",
    "detail-meta",
    `${payment.order_id} · ${fmtAmount(payment.amount, payment.currency)} · ${payment.payment_method} · created ${fmtTime(payment.created_at)}`
  );
  header.append(meta);
}

export function renderDetailAttempts(payment: Payment): void {
  const tbody = document.getElementById("detail-attempts")!;
  tbody.replaceChildren();
  for (const attempt of payment.attempts) {
    const tr = el("tr");
    tr.append(el("td", undefined, `#${attempt.attempt_number}`));
    tr.append(el("td", undefined, attempt.provider_id));
    const outcome = el("td");
    outcome.append(badge(attempt.status));
    tr.append(outcome);
    tr.append(
      el("td", undefined, attempt.failure_code ?? "—"),
      el("td", undefined, attempt.latency_ms !== null ? `${attempt.latency_ms} ms` : "—"),
      el(
        "td",
        undefined,
        attempt.simulated_cost !== null ? attempt.simulated_cost.toFixed(4) : "—"
      )
    );
    tbody.append(tr);
  }
  if (payment.attempts.length === 0) {
    const tr = el("tr");
    const td = el(
      "td",
      "muted",
      "No attempts — no provider was eligible at routing time."
    ) as HTMLTableCellElement;
    td.colSpan = 6;
    tr.append(td);
    tbody.append(tr);
  }
}

export function renderRoutingDecisions(payment: Payment): void {
  const container = document.getElementById("detail-routing")!;
  container.replaceChildren();
  for (const attempt of payment.attempts) {
    const decision = attempt.routing_decision;
    const block = el("div", "routing-block");
    block.append(
      el("h3", undefined, `Attempt #${attempt.attempt_number} → ${attempt.provider_id}`)
    );
    if (!decision) {
      block.append(el("p", "muted", "No routing decision stored."));
      container.append(block);
      continue;
    }
    const cols = el("div", "routing-cols");

    const scoresCol = el("div");
    scoresCol.append(el("h4", undefined, "Candidates & scores"));
    const scoreList = el("ul");
    for (const candidate of decision.candidates) {
      const score = decision.scores[candidate] ?? 0;
      const marker = candidate === decision.selected ? " ← selected" : "";
      scoreList.append(
        el("li", undefined, `${candidate} — ${score.toFixed(3)}${marker}`)
      );
    }
    if (decision.candidates.length === 0) scoreList.append(el("li", "muted", "none"));
    scoresCol.append(scoreList);

    const excludedCol = el("div");
    excludedCol.append(el("h4", undefined, "Excluded"));
    const excludedList = el("ul");
    for (const [providerId, reason] of Object.entries(decision.excluded)) {
      excludedList.append(el("li", undefined, `${providerId} — ${reason}`));
    }
    if (Object.keys(decision.excluded).length === 0) excludedList.append(el("li", "muted", "none"));
    excludedCol.append(excludedList);

    cols.append(scoresCol, excludedCol);
    block.append(cols);
    container.append(block);
  }
}

export function renderEvents(events: AuditEvent[]): void {
  const list = document.getElementById("detail-events")!;
  list.replaceChildren();
  for (const event of events) {
    const li = el("li");
    li.append(el("span", "event-type", event.event_type));
    li.append(
      el("span", undefined, JSON.stringify(event.event_payload))
    );
    li.append(el("span", "event-time", fmtTime(event.created_at)));
    list.append(li);
  }
  if (events.length === 0) {
    const li = el("li", "muted", "No audit events recorded for this payment.");
    list.append(li);
  }
}

// ---- Copilot result card ----

export function renderExplanation(
  explanation: Explanation,
  status: "final" | "polling"
): void {
  const card = document.getElementById("explain-card")!;
  card.hidden = false;
  card.replaceChildren();

  const head = el("div", "explain-head");
  head.append(el("h3", undefined, "AI explanation"));
  const isModel = explanation.source !== "rule-based";
  const source = el("span", `source-badge ${isModel ? "glm" : ""}`, isModel ? explanation.source.replace(/^[a-z]+:/, "") : "rule-based");
  head.append(source);
  card.append(head);

  card.append(el("p", undefined, explanation.summary));

  const section = (title: string, items: string[]) => {
    if (items.length === 0) return;
    card.append(el("h3", undefined, title));
    const ul = el("ul");
    for (const item of items) ul.append(el("li", undefined, item));
    card.append(ul);
  };

  section("Evidence", explanation.evidence);
  section("Hypotheses", explanation.possible_causes);
  section("Recommended actions", explanation.recommended_actions);

  card.append(el("h3", undefined, "Confidence"));
  card.append(el("p", "muted", explanation.confidence_note));

  if (status === "polling") {
    card.append(el("p", "muted", "Rule-based answer shown now; the model answer will replace it when it arrives."));
  }
}