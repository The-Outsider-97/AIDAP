"""Validate a file and only read it back through the pull gate if release is authorized."""
import os, sys
from aidap_sdk import Client, AidapError

c = Client(os.environ["AIDAP_URL"], api_key=os.environ["AIDAP_API_KEY"])
try:
    r = c.assure(sys.argv[1], project=os.environ["AIDAP_PROJECT"], profile="rag_indexing")
except AidapError as e:
    sys.exit(f"AIDAP error {e.status} {e.code}: {e}")
print(r.decision, r.reason_codes)
if r.release_authorized:
    open("released.bin", "wb").write(c.artifact(r.run_id))
else:
    sys.exit(f"not released: {r.summary}")
