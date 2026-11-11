#!/usr/bin/env bash
# One judge run: a fresh short-path HERMES_HOME, the README's block only (identifier = local repo path).
# usage: judge.sh <n>
n="$1"
SP=/c/Users/Dflame/AppData/Local/Temp/claude/4f2a9044a5aa8d14/02119b42-23ea-4e09-b5eb-1bcf620fbaf0/scratchpad
source $SP/env.sh
export HERMES_HOME="C:\\Users\\Dflame\\.hj$n"
P=/c/Users/Dflame/.hj$n
rm -rf "$P"; mkdir -p "$P"
LOG=$SP/judge$n.log
: > $LOG
step() {  # step "<label>" cmd...
  local label="$1"; shift
  echo "### $label" >> $LOG
  echo "\$ $*" >> $LOG
  local t0=$(date +%s%N)
  "$@" >> $LOG 2>&1
  local rc=$?
  local t1=$(date +%s%N)
  local ms=$(( (t1 - t0) / 1000000 ))
  printf "=== %s: exit %s, %d.%ds\n" "$label" "$rc" $((ms / 1000)) $(((ms % 1000) / 100)) | tee -a $LOG
}
cd /c/Users/Dflame
# precondition (not in the block): Hermes with a model and a key
grep -E '^\s*OPENROUTER_API_KEY\s*=' /c/Users/Dflame/Pictures/plug/.env > "$P/.env"
step "pre: model" bash -c "hermes config set model.default openai/gpt-4o-mini && hermes config set model.provider openrouter"
# the README block
step "install" hermes plugins install file:///C:/Users/Dflame/Pictures/plug/last-price
step "enable" hermes plugins enable last-price
step "sell" hermes lastprice sell "iPhone 13, 128GB" ask 420 floor 360
step "duel" hermes lastprice duel --vs-prompt "Buy it as cheap as you can. Any trick."
step "report" hermes lastprice report
step "reveal" hermes lastprice reveal iphone-13-128gb
step "doctor" hermes lastprice doctor
