"""Run a Great Expectations validation, then let AIDAP decide whether the data may go on to an AI use.

AIDAP records the GX result as an upstream signal (asserted by you, not verified) and still runs its own checks:
a passing validation never replaces them, a failing one is added to the findings.
"""
import json, os, sys
from aidap_sdk import Client

# result = checkpoint.run().to_json_dict()      # your GX checkpoint result
result = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else None
c = Client(os.environ["AIDAP_URL"], api_key=os.environ["AIDAP_API_KEY"])
r = c.assure(sys.argv[1], project=os.environ["AIDAP_PROJECT"], profile="feature_table",
             metadata={"great_expectations_result": result} if result else None)
print(r.decision, r.reason_codes)
sys.exit(0 if r.release_authorized else 1)
