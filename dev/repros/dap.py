import json, subprocess, sys, threading, queue, os
prog = os.path.abspath(sys.argv[1]); linea = int(sys.argv[2]); flags = sys.argv[3:]
p = subprocess.Popen([sys.executable, "V0/main.py", "--dap"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
q = queue.Queue()
def lector():
    while True:
        h = p.stdout.readline()
        if not h: q.put(None); return
        if h.startswith(b"Content-Length"):
            n = int(h.split(b":")[1]); p.stdout.readline(); q.put(json.loads(p.stdout.read(n)))
threading.Thread(target=lector, daemon=True).start()
seq = [0]
def manda(cmd, args=None):
    seq[0] += 1; b = json.dumps({"seq": seq[0], "type": "request", "command": cmd, "arguments": args or {}}).encode()
    p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); p.stdin.flush(); return seq[0]
def espera(pred, t=60):
    while True:
        m = q.get(timeout=t)
        if m is None: return None
        if pred(m): return m
manda("initialize", {"adapterID": "suriax"}); espera(lambda m: m.get("command") == "initialize")
manda("launch", {"program": prog, "flags": flags})
manda("setBreakpoints", {"source": {"path": prog}, "breakpoints": [{"line": linea, "condition": "a == 0"}]})
r = espera(lambda m: m.get("command") == "setBreakpoints"); print("setBreakpoints:", r.get("body"))
manda("configurationDone")
st = espera(lambda m: m.get("event") == "stopped"); print("stopped:", st["body"].get("reason"))
s = manda("stackTrace", {"threadId": 1}); r = espera(lambda m: m.get("request_seq") == s); print("frames:", [f["name"] for f in r["body"]["stackFrames"]])
fid = r["body"]["stackFrames"][0]["id"]
for e in sys_exprs if False else ["a", "b", "a + 1"]:
    s = manda("evaluate", {"expression": e, "frameId": fid, "context": "watch"}); r = espera(lambda m: m.get("request_seq") == s)
    print(f"evaluate {e!r}:", r.get("success"), r.get("body"), r.get("message"))
s = manda("setVariable", {"variablesReference": 1, "name": "a", "value": "5"}); r = espera(lambda m: m.get("request_seq") == s); print("setVariable:", r.get("success"), r.get("message"))
manda("disconnect"); p.wait(timeout=30)
