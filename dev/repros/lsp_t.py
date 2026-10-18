import json, subprocess, sys, threading, queue, os, time, pathlib
f = os.path.abspath(sys.argv[1]); uri = pathlib.Path(f).as_uri(); txt = open(f, encoding="utf-8").read()
p = subprocess.Popen([sys.executable, "V0/main.py", "--lsp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
q = queue.Queue()
def lector():
    while True:
        h = p.stdout.readline()
        if not h: q.put(None); return
        if h.startswith(b"Content-Length"):
            n = int(h.split(b":")[1]); p.stdout.readline(); q.put(json.loads(p.stdout.read(n)))
threading.Thread(target=lector, daemon=True).start()
def manda(o):
    b = json.dumps(o).encode(); p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); p.stdin.flush()
manda({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}})
while (m := q.get()).get("id") != 1: pass
manda({"jsonrpc":"2.0","method":"initialized","params":{}})
for v in range(1, 4):
    t = time.perf_counter()
    if v == 1: manda({"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":{"uri":uri,"languageId":"suriax","version":1,"text":txt}}})
    else: manda({"jsonrpc":"2.0","method":"textDocument/didChange","params":{"textDocument":{"uri":uri,"version":v},"contentChanges":[{"text":txt + "\n"*v}]}})
    while True:
        m = q.get(timeout=120)
        if m and m.get("method") == "textDocument/publishDiagnostics": break
    print(f"analisis {v}: {time.perf_counter()-t:.2f} s, {len(m['params']['diagnostics'])} diagnosticos")
manda({"jsonrpc":"2.0","id":9,"method":"shutdown"}); manda({"jsonrpc":"2.0","method":"exit"}); p.wait(timeout=30)
