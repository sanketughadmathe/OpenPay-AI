// Dashboard entrypoint: state, view switching, controls, refresh loop.

import { api } from "./api";
import * as render from "./render";

type View = "overview" | "transactions" | "detail";
type CopilotMode = "payment" | "incident";

const state = {
  view: "overview" as View,
  paymentId: null as string | null,
  filters: { status: "", provider: "" },
  busyCount: 0,
  pollTimer: null as number | null,
  pollDeadline: 0,
  copilotMode: "payment" as CopilotMode,
};

// ---- busy handling: disable buttons while a request is in flight ----

function controlButtons(): HTMLButtonElement[] {
  return Array.from(
    document.querySelectorAll<HTMLButtonElement>(".sidebar .btn, .copilot-row .btn")
  );
}

function setBusy(delta: number): void {
  state.busyCount = Math.max(0, state.busyCount + delta);
  const busy = state.busyCount > 0;
  for (const button of controlButtons()) button.disabled = busy;
}

async function control<T>(action: () => Promise<T>): Promise<T | null> {
  setBusy(1);
  try {
    const result = await action();
    await refreshAll();
    return result;
  } catch (error) {
    render.toast(`Request failed: ${errorMessage(error)}`);
    return null;
  } finally {
    setBusy(-1);
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// ---- data refresh ----

async function refreshOverview(): Promise<void> {
  try {
    const [summary, providers] = await Promise.all([api.summary(), api.providers()]);
    render.renderKpis(summary);
    render.renderCharts(summary);
    syncControls(providers);
  } catch {
    /* server briefly away — next tick retries */
  }
}

async function refreshTransactions(): Promise<void> {
  try {
    const payments = await api.payments({
      status: state.filters.status || undefined,
      provider: state.filters.provider || undefined,
      limit: 200,
    });
    render.renderTransactions(payments);
  } catch (error) {
    render.toast(`Could not load payments: ${errorMessage(error)}`);
  }
}

async function refreshDetail(): Promise<void> {
  if (!state.paymentId) {
    document.getElementById("detail-header")!.replaceChildren(
      render.el("p", "muted", "Pick a payment from Transactions, or paste a payment ID below.")
    );
    return;
  }
  try {
    const [payment, events] = await Promise.all([
      api.payment(state.paymentId),
      api.events(state.paymentId),
    ]);
    render.renderDetailHeader(payment);
    render.renderDetailAttempts(payment);
    render.renderRoutingDecisions(payment);
    render.renderEvents(events);
  } catch (error) {
    render.toast(`Could not load payment: ${errorMessage(error)}`);
  }
}

async function refreshAll(): Promise<void> {
  await refreshOverview();
  if (state.view === "transactions") await refreshTransactions();
  if (state.view === "detail") await refreshDetail();
}

// ---- sidebar controls reflect server state (unless the user is on them) ----

function syncControls(providers: { id: string; is_healthy: boolean; simulated_success_rate: number }[]): void {
  for (const provider of providers) {
    const suffix = provider.id.replace("provider_", "");
    const health = document.getElementById(`ctl-${suffix}-healthy`) as HTMLInputElement | null;
    const rate = document.getElementById(`ctl-${suffix}-rate`) as HTMLInputElement | null;
    const out = document.getElementById(`ctl-${suffix}-rate-val`);
    const dot = document.getElementById(`dot-${suffix}`);
    if (!health || !rate || !out) continue;
    if (document.activeElement !== health) health.checked = provider.is_healthy;
    if (document.activeElement !== rate) {
      rate.value = String(Math.round(provider.simulated_success_rate * 100));
    }
    out.textContent = `${rate.value}%`;
    dot?.classList.toggle("down", !provider.is_healthy);
  }
}

// ---- view switching ----

function setView(view: View): void {
  state.view = view;
  stopPolling();
  for (const section of document.querySelectorAll<HTMLElement>(".view")) {
    section.hidden = section.id !== `view-${view}`;
  }
  for (const button of document.querySelectorAll<HTMLElement>(".nav-btn")) {
    button.classList.toggle("active", button.dataset.view === view);
  }
  if (view === "transactions") void refreshTransactions();
  if (view === "detail") void refreshDetail();
}

// ---- copilot ----

function stopPolling(): void {
  if (state.pollTimer !== null) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function startPolling(): void {
  state.pollDeadline = Date.now() + 30_000;
  state.pollTimer = window.setInterval(async () => {
    if (Date.now() > state.pollDeadline) return stopPolling();
    try {
      const latest =
        state.copilotMode === "payment" && state.paymentId
          ? await api.cachedExplanation(state.paymentId)
          : await api.cachedIncident();
      if (latest.source !== "rule-based") {
        render.renderExplanation(latest, "final");
        stopPolling();
      }
    } catch {
      stopPolling(); // cache GET not available — keep the rule-based answer
    }
  }, 2_000);
}

function showExplainError(message: string): void {
  const card = document.getElementById("explain-card")!;
  card.hidden = false;
  card.replaceChildren(
    render.el("h3", undefined, "AI copilot"),
    render.el("p", "muted", message)
  );
}

async function runCopilot(mode: CopilotMode): Promise<void> {
  stopPolling();
  state.copilotMode = mode;
  try {
    const result =
      mode === "payment" && state.paymentId
        ? await api.explain(state.paymentId)
        : await api.incident();
    render.renderExplanation(result, "polling");
    startPolling();
  } catch (error) {
    showExplainError(
      `Copilot endpoint unavailable (${errorMessage(error)}). The AI epic (E4) wires this up — ` +
        "routing, retry and audit data on this page are fully live."
    );
  }
}

// ---- wiring ----

function wireNav(): void {
  for (const button of document.querySelectorAll<HTMLElement>(".nav-btn")) {
    button.addEventListener("click", () => setView(button.dataset.view as View));
  }
  document.getElementById("detail-back")!.addEventListener("click", () => setView("transactions"));
}

function wireFilters(): void {
  document.getElementById("filter-status")!.addEventListener("change", (event) => {
    state.filters.status = (event.target as HTMLSelectElement).value;
    void refreshTransactions();
  });
  document.getElementById("filter-provider")!.addEventListener("change", (event) => {
    state.filters.provider = (event.target as HTMLSelectElement).value;
    void refreshTransactions();
  });
}

function wireTransactions(): void {
  document.getElementById("tx-tbody")!.addEventListener("click", (event) => {
    const row = (event.target as HTMLElement).closest<HTMLElement>("tr[data-payment-id]");
    if (!row) return;
    state.paymentId = row.dataset.paymentId ?? null;
    setView("detail");
  });
}

function wireDetailIdInput(): void {
  const input = document.getElementById("detail-id-input") as HTMLInputElement | null;
  const go = document.getElementById("detail-id-go");
  if (!input || !go) return;
  const open = () => {
    const id = input.value.trim();
    if (!id) return;
    state.paymentId = id;
    void refreshDetail();
  };
  go.addEventListener("click", open);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") open();
  });
}

function wireControls(): void {
  for (const suffix of ["a", "b"]) {
    const health = document.getElementById(`ctl-${suffix}-healthy`) as HTMLInputElement;
    const rate = document.getElementById(`ctl-${suffix}-rate`) as HTMLInputElement;
    const out = document.getElementById(`ctl-${suffix}-rate-val`) as HTMLElement;

    health.addEventListener("change", () =>
      void control(() =>
        api.patchHealth(`provider_${suffix}`, { is_healthy: health.checked })
      )
    );
    rate.addEventListener("input", () => {
      out.textContent = `${rate.value}%`;
    });
    rate.addEventListener("change", () =>
      void control(() =>
        api.patchHealth(`provider_${suffix}`, { success_rate: Number(rate.value) / 100 })
      )
    );
  }

  document.getElementById("btn-seed")!.addEventListener("click", () =>
    void control(async () => {
      const result = await api.seed(100);
      const outcomeText = Object.entries(result.outcomes)
        .map(([status, count]) => `${count} ${status.toLowerCase()}`)
        .join(", ");
      render.toast(`Seeded ${result.seeded} payments — ${outcomeText}`);
    })
  );

  document.getElementById("btn-degrade-a")!.addEventListener("click", () =>
    void control(() => api.patchHealth("provider_a", { success_rate: 0.2 }))
  );

  document.getElementById("btn-outage-a")!.addEventListener("click", () =>
    void control(() => api.patchHealth("provider_a", { is_healthy: false }))
  );

  document.getElementById("btn-reset")!.addEventListener("click", () =>
    void control(async () => {
      await api.reset();
      render.toast("Demo reset — tables truncated, providers restored");
    })
  );

  document.getElementById("btn-explain")!.addEventListener("click", () =>
    void runCopilot("payment")
  );
  document.getElementById("btn-incident")!.addEventListener("click", () =>
    void runCopilot("incident")
  );
}

// ---- boot ----

wireNav();
wireFilters();
wireTransactions();
wireDetailIdInput();
wireControls();
void refreshAll();

window.setInterval(() => {
  void refreshOverview();
  if (state.view === "transactions") void refreshTransactions();
}, 3_000);