import json, re, sys, urllib.request, urllib.error

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SENIOR = "janus-demo-senior-margaret"   # should only access margaret_01
CARE = "janus-demo-caregiver-sarah"     # should only access margaret_01

def call(tok, tool, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream",
         "MCP-Protocol-Version": "2025-11-25"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(URL + "/mcp", data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, str(e)

results = []
def check(label, ok, status, text):
    results.append(ok)
    print(("PASS" if ok else "FAIL"), "|", label, "| HTTP", status)
    print("     ", text[:220].replace("\n", " "))

try:
    with urllib.request.urlopen(URL + "/health", timeout=5) as r:
        print("health:", r.status, r.read().decode()[:100])
except Exception as e:
    print("health FAILED:", e); sys.exit(1)

summary = {"senior_id": "margaret_01"}
s, t = call(None, "get_caregiver_summary", summary)
check("A no token -> 401", s == 401, s, t)
s, t = call("totally-bad", "get_caregiver_summary", summary)
check("B garbage token -> 401", s == 401, s, t)
s, t = call("janus-demo-x", "get_caregiver_summary", summary)
check("C wildcard-prefix token -> 401", s == 401, s, t)
s, t = call(SENIOR, "get_caregiver_summary", {"senior_id": "arthur_02"})
check("D margaret reads arthur_02 -> FORBIDDEN, no data",
      "forbidden" in t.lower() and "completion_percentage" not in t, s, t)
s, t = call(SENIOR, "verify_routine_state",
            {"confirm": False, "senior_id": "margaret_01",
             "action_type": "shift_handoff",
             "payload": {"incoming_caregiver": "Test"}})
check("E senior token on handoff -> FORBIDDEN", "forbidden" in t.lower(), s, t)
s, t = call(CARE, "get_caregiver_summary", summary)
check("F caregiver reads own senior -> OK",
      s == 200 and "forbidden" not in t.lower(), s, t)
s, t = call(SENIOR, "log_daily_routine",
            {"senior_id": "margaret_01", "category": "hydration",
             "details": "glass of water"})
m = re.search(r"tx_[0-9a-f]+", t)
check("G log -> pending tx id", m is not None, s, t)
s, t = call(SENIOR, "verify_routine_state", {"confirm": True})
check("H confirm with no transaction_id -> error", "error" in t.lower(), s, t)
if m:
    tx = m.group(0)
    s, t = call(SENIOR, "verify_routine_state", {"confirm": True, "transaction_id": tx})
    check("I1 confirm real tx -> COMMITTED", "COMMITTED" in t and "ALREADY" not in t, s, t)
    s, t = call(SENIOR, "verify_routine_state", {"confirm": True, "transaction_id": tx})
    check("I2 replay -> ALREADY_COMMITTED", "ALREADY_COMMITTED" in t, s, t)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)