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

Environment: `AIDAP_URL`, `AIDAP_API_KEY`. Verify webhooks with `aidap_sdk.webhooks.verify_signature`.
