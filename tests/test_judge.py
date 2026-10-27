"""Judge checks with hand-built Muse Spark reports (no API calls). Run: uv run python tests/test_judge.py"""

from pr.judge import judge

KEYSTEPS = ["open", "battery", "ram", "close", "test"]
# Parts go in any order; open first, close after the parts, test last.
BEFORE = {("open", "battery"), ("open", "ram"), ("open", "close"), ("open", "test"),
          ("battery", "close"), ("ram", "close"), ("battery", "test"), ("ram", "test"), ("close", "test")}
# Checklist step 3 and 4 both belong to "ram" (Muse Spark split it in two).
KEYSTEP_OF = {1: "open", 2: "battery", 3: "ram", 4: "ram", 5: "close", 6: "test"}


def m(index, start, end=None, performed=True, confidence="high"):
    return {"index": index, "performed": performed, "start_s": start if performed else -1,
            "end_s": (end or start + 5) if performed else -1, "confidence": confidence, "evidence": "seen"}


def raised(flags):
    return sorted((f["type"], f["name"]) for f in flags if f["type"] != "ok")


clean = [m(1, 0), m(2, 30), m(3, 10), m(4, 15), m(5, 50), m(6, 60)]           # ram before battery: allowed
assert raised(judge(clean, KEYSTEP_OF, KEYSTEPS, BEFORE)) == [], judge(clean, KEYSTEP_OF, KEYSTEPS, BEFORE)

no_ram = [m(1, 0), m(2, 30), m(3, 0, performed=False), m(4, 0, performed=False), m(5, 50), m(6, 60)]
f = judge(no_ram, KEYSTEP_OF, KEYSTEPS, BEFORE)
assert raised(f) == [("missing", "ram")], f
assert next(x for x in f if x["type"] == "missing")["ts"] == 50   # noticed when the case is closed
assert next(x for x in f if x["type"] == "missing")["step"] == 3

half_ram = [m(1, 0), m(2, 30), m(3, 10), m(4, 0, performed=False), m(5, 50), m(6, 60)]
assert raised(judge(half_ram, KEYSTEP_OF, KEYSTEPS, BEFORE)) == []           # one of two sub-steps is enough

unsure = [m(1, 0), m(2, 30), m(3, 0, False, "low"), m(4, 0, False, "low"), m(5, 50), m(6, 60)]
assert raised(judge(unsure, KEYSTEP_OF, KEYSTEPS, BEFORE)) == []             # low confidence never flags

closed_early = [m(1, 0), m(2, 30), m(3, 40), m(4, 45), m(5, 20), m(6, 60)]   # case closed before parts
f = judge(closed_early, KEYSTEP_OF, KEYSTEPS, BEFORE)
assert raised(f) == [("out_of_order", "close")], f
assert next(x for x in f if x["type"] == "out_of_order")["ts"] == 20

jitter = [m(1, 0), m(2, 30), m(3, 10), m(4, 15), m(5, 49), m(6, 48)]         # 1 s apart: within MARGIN
assert raised(judge(jitter, KEYSTEP_OF, KEYSTEPS, BEFORE)) == []

print("7 judge cases pass")
