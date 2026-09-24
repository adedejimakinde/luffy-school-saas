#!/usr/bin/env bash
# Wait for test AND image on the exact head of #145, then report. Never merges on its own.
export PATH=~/bin:$PATH
FULL=$1
R=adedejimakinde/luffy-school-saas
for i in $(seq 1 120); do
  out=$(gh api repos/$R/commits/$FULL/check-runs --jq '[.check_runs[] | select(.name=="test" or .name=="image")] | map("\(.name)=\(.status)/\(.conclusion)") | join(" ")' 2>/dev/null || echo "api-error")
  if echo "$out" | grep -qE "=completed/(failure|cancelled|timed_out|action_required|neutral|skipped|stale)"; then echo "GATE=RED $out"; exit 1; fi
  if echo "$out" | grep -q "test=completed/success" && echo "$out" | grep -q "image=completed/success"; then echo "GATE=GREEN $out"; exit 0; fi
  sleep 60
done
echo "GATE=TIMEOUT $out"; exit 2
