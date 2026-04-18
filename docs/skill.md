---
name: deploy
description: Safely restart the live trading system after code changes
disable-model-invocation: true
allowed-tools: Bash, Read
---

Deploy the trading system safely. $ARGUMENTS

## Pre-flight checks

1. Check for running process: `./scripts/run.sh status`
2. Run test suite: `pytest tests/ -x -q` — STOP if any failures
3. Check for syntax errors: `python3 -m py_compile quant/agents/scanner_agent.py quant/agents/risk_agent.py quant/agents/execution_agent.py quant/tools/paper.py`

## Deploy

4. Stop current process: `./scripts/run.sh stop`
5. Wait 3 seconds: `sleep 3`
6. Confirm stopped: `./scripts/run.sh status`
7. Start fresh: `./scripts/run.sh start`
8. Wait 10 seconds for startup: `sleep 10`

## Verify

9. `./scripts/run.sh status` — confirm alive
10. `tail -30 data/paper_fund.log` — confirm no Traceback on startup
11. Report: PID, startup log tail, any errors found

## Abort conditions
- Any test failures → stop, do not deploy
- Any syntax errors → stop, fix first
- Process won't stop cleanly → report, do not force-kill without explicit instruction
