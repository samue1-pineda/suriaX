import json, subprocess, sys, threading, queue, os
prog = os.path.abspath(sys.argv[1])
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
    p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); p.stdin.flush()
manda("initialize", {"adapterID": "suriax"}); manda("launch", {"program": prog})
manda("setExceptionBreakpoints", {"filters": ["sin-atrapar"]}); manda("configurationDone")
while True:
    m = q.get(timeout=60)
    if m is None: break
    if m.get("type") == "event": print("evento:", m["event"], (m.get("body") or {}).get("reason", ""), (m.get("body") or {}).get("output", "").strip()[:120])
    if m.get("event") == "stopped": manda("disconnect"); 
    if m.get("event") in ("terminated", "exited") : break
manda("disconnect"); p.wait(timeout=30)
