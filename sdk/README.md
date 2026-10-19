# aidap-sdk

Python client and CI gate for AIDAP. Standard library only.

```python
from aidap_sdk import Client
c = Client("https://aidap.example.com", api_key="aidk_…")
result = c.assure("handbook.json", project="prj_…", profile="rag_indexing")
print(result.decision, result.reason_codes)
if result.decision == "pass":
    data = c.artifact(result.run_id)          # released bytes; 403 unless release is authorized
```

CI gate (exit code 0 pass · 10 review · 20 quarantine · 30 block · 2 usage/connection error · 3 run failed):

```bash
python -m aidap_sdk check handbook.json --project prj_… --profile rag_indexing --url https://aidap.example.com --api-key aidk_…
```

Results from tools that already looked at the data can travel with the submission. AIDAP records them as asserted by you:
a failure adds a finding, a pass proves nothing and replaces no check.

```bash
python -m aidap_sdk check data.csv --project prj_… --profile feature_table \
    --gx-result gx_result.json --soda-scan soda.json --upstream monte_carlo:orders_freshness=passed --github
```

`--github` prints workflow annotations and appends a step summary to `$GITHUB_STEP_SUMMARY`.

Golden-set suites (adjudicated examples with the decision each should receive) run in CI the same way; exit code 0 when
every example behaves as adjudicated, 1 otherwise. The API key needs the `runs:write` and `policies:read` scopes.

```bash
python -m aidap_sdk suite sui_… --profile rag_indexing --policy standard
```

Other calls: `insights()`, `metrics()` (Prometheus text, Team plan and above), `rate_finding()`, `run_suite()`, `suggest_profile()`.

**MCP server.** An agent can check content before it reads or stores it:

```bash
AIDAP_URL=… AIDAP_API_KEY=… AIDAP_PROJECT=prj_… AIDAP_PROFILE=agent_tool_output python -m aidap_sdk.mcp
```

Tools: `aidap_check`, `aidap_result`, `aidap_findings`. The server returns decisions and reason codes only, never the checked
content, and `usable` is true only for an authorised PASS.

Environment: `AIDAP_URL`, `AIDAP_API_KEY`. Verify webhooks with `aidap_sdk.webhooks.verify_signature`.
Examples: `examples/gx_gate.py` (Great Expectations), `examples/slack_relay.py` (Slack), `examples/github_actions.yml`.
