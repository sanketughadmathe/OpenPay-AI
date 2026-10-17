#!/usr/bin/env bash
# OpenPay AI: the 90-second demo as curl calls. Backup for the dashboard demo.
# Usage: ./demo.sh [base_url]   (API must be running: uv run uvicorn app.main:app --port 8000)
set -euo pipefail
B="${1:-http://127.0.0.1:8000}/api/v1"
J='Content-Type: application/json'
py() { python3 -c "import sys,json;d=json.load(sys.stdin);$1"; }
step() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

step "0. Reset simulation (all data is SIMULATED, no real money)"
curl -s -X POST "$B/demo/reset" | py 'print("reset:", d["reset"])'

step "1. Normal operation: seed 100 payments, both providers healthy"
curl -s -X POST "$B/demo/seed" -H "$J" -d '{"count":100,"seed":42}' | py 'print("outcomes:", d["outcomes"])'
curl -s "$B/analytics/summary" | py 'print("success rate:", d["success_rate"]); [print("  %s: %d attempts, %.1f%% ok, avg %s ms" % (k, v["attempts"], v["success_rate"]*100, v["avg_latency_ms"])) for k,v in d["per_provider"].items()]'

step "2. Simulate degradation: mark Provider A unhealthy"
curl -s -X PATCH "$B/providers/provider_a/health" -H "$J" -d '{"is_healthy":false}' | py 'print("provider_a healthy:", d["is_healthy"])'

step "3. Intelligent routing: seed 50 more, router must avoid A"
curl -s -X POST "$B/demo/seed" -H "$J" -d '{"count":50,"seed":7}' | py 'print("outcomes:", d["outcomes"])'
curl -s "$B/analytics/summary" | py 'print("success rate:", d["success_rate"]); [print("  %s: %d attempts, %.1f%% ok" % (k, v["attempts"], v["success_rate"]*100)) for k,v in d["per_provider"].items()]'

step "4. Inspect a payment that failed on A and was retried on B"
PID=$(curl -s "$B/payments?limit=500" | py 'print(next(p["id"] for p in d if p["attempt_count"]==2))')
echo "payment: $PID"
curl -s "$B/payments/$PID/attempts" | py '[print("  attempt %d: %s -> %s %s (%s ms)" % (a["attempt_number"], a["provider_id"], a["status"], a["failure_code"] or "", a["latency_ms"])) for a in d]'
curl -s "$B/payments/$PID/attempts" | py 'rd=d[-1]["routing_decision"]; print("  retry routing excluded:", rd["excluded"]); print("  retry routing scores:", rd["scores"])'

step "5. Ask the AI copilot (rule-based now, model answer follows)"
curl -s "$B/ai/status" | py 'print("backend:", d["llm_provider"], d["model"] or "")'
curl -s -X POST "$B/ai/explain/$PID" | py 'print("[%s]" % d["source"], d["summary"])'
for i in $(seq 1 20); do
  sleep 1
  SRC=$(curl -s "$B/ai/explain/$PID" | py 'print(d["source"])')
  [ "$SRC" != "rule-based" ] && break
done
curl -s "$B/ai/explain/$PID" | py 'print("[%s] after wait" % d["source"]); print("  summary:", d["summary"]); print("  evidence:"); [print("   -", e) for e in d["evidence"][:4]]; print("  confidence:", d["confidence_note"][:160])'

step "6. Incident summary: what changed after Provider A went down"
curl -s -X POST "$B/ai/incident" | py 'print("[%s]" % d["source"], d["summary"])'
for i in $(seq 1 20); do
  sleep 1
  SRC=$(curl -s "$B/ai/incident" | py 'print(d["source"])')
  [ "$SRC" != "rule-based" ] && break
done
curl -s "$B/ai/incident" | py 'print("[%s] after wait" % d["source"]); print("  summary:", d["summary"])'

step "Done. Dashboard: ${1:-http://127.0.0.1:8000}/ui/"
