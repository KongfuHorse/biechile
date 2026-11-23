"""biechile NAS agent (bootstrap).

This file is built into the Docker image and rarely changes. It:
  1. checks in with Supabase every few seconds (heartbeat),
  2. downloads the current "jobs" code bundle from Supabase when its version changes,
     checks its sha256 and restarts itself to load it,
  3. takes queued jobs one at a time, runs the matching handler from the bundle,
     and sends the result and log back.

It only talks to Supabase through the nas_* database functions, with its own token.
It never runs shell commands sent from the database; it can only run handlers that exist
in a code bundle, and only the service role can publish a bundle.

Environment:
  SUPABASE_URL, SUPABASE_ANON_KEY  project URL and public (anon/publishable) key
  NAS_TOKEN                         this agent's token
  AGENT_NAME                        default "nas1"
  DATA_DIR                          default /data (mount a NAS folder here)
"""
import base64
import hashlib
import io
import json
import logging
import logging.handlers
import os
import platform
import shutil
import socket
import sys
import threading
import time
import traceback
import zipfile

import requests

BOOT_VERSION = "boot-1"
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_ANON_KEY", "")
TOKEN = os.environ.get("NAS_TOKEN", "")
AGENT = os.environ.get("AGENT_NAME", "nas1")
DATA = os.environ.get("DATA_DIR", "/data")
JOB_TIMEOUT = int(os.environ.get("JOB_TIMEOUT", "3600"))

os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
log = logging.getLogger("agent")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
_h = logging.handlers.RotatingFileHandler(os.path.join(DATA, "logs", "agent.log"), maxBytes=5_000_000, backupCount=3)
_h.setFormatter(_fmt)
log.addHandler(_h)
_s = logging.StreamHandler(sys.stdout)
_s.setFormatter(_fmt)
log.addHandler(_s)


def rpc(_fn, **args):
    r = requests.post(f"{URL}/rest/v1/rpc/{_fn}",
                      headers={"apikey": KEY, "Content-Type": "application/json"},
                      json={f"p_{k}": v for k, v in args.items()}, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"{_fn}: HTTP {r.status_code} {r.text[:300]}")
    return r.json() if r.content else None


# ---------------- code bundle ----------------
CODE_DIR = os.path.join(DATA, "code")
CURRENT = os.path.join(CODE_DIR, "current.txt")


def current_version():
    try:
        return open(CURRENT).read().strip()
    except OSError:
        return ""


def install_bundle(version):
    b = rpc("nas_get_code", token=TOKEN, agent=AGENT, version=version)
    if not b:
        raise RuntimeError(f"code version {version} not found")
    raw = base64.b64decode(b["zip_b64"])
    if hashlib.sha256(raw).hexdigest() != b["sha256"]:
        raise RuntimeError("code bundle sha256 mismatch")
    dest = os.path.join(CODE_DIR, version)
    tmp = dest + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in n.split("/"):
                raise RuntimeError(f"unsafe path in bundle: {n}")
        z.extractall(tmp)
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)
    with open(CURRENT + ".tmp", "w") as f:
        f.write(version)
    os.replace(CURRENT + ".tmp", CURRENT)
    log.info("installed code %s", version)


def load_handlers():
    v = current_version()
    if not v or not os.path.isdir(os.path.join(CODE_DIR, v)):
        return v, {}
    sys.path.insert(0, os.path.join(CODE_DIR, v))
    try:
        import jobs  # noqa: E402  (from the bundle)
        return v, dict(jobs.HANDLERS)
    except Exception:
        log.error("cannot load code %s:\n%s", v, traceback.format_exc())
        return v + "(broken)", {}


def restart():
    log.info("restarting")
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ---------------- machine info ----------------
def machine_info(extra=None):
    du = shutil.disk_usage(DATA)
    mem = {}
    try:
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.split()[0]) // 1024
    except OSError:
        pass
    info = {"boot": BOOT_VERSION, "host": socket.gethostname(), "python": platform.python_version(),
            "disk_free_gb": round(du.free / 1e9, 1), "mem_mb": mem, "time": time.strftime("%Y-%m-%d %H:%M:%S %z")}
    info.update(extra or {})
    return info


# ---------------- jobs ----------------
class Ctx:
    """Passed to every handler."""
    def __init__(self, job_id, logger):
        self.job_id = job_id
        self.log = logger
        self.data_dir = DATA
        self.agent = AGENT

    def put_file(self, name, mime, data: bytes):
        rpc("nas_put_file", token=TOKEN, agent=AGENT, job=self.job_id, name=name, mime=mime,
            b64=base64.b64encode(data).decode())


def builtin_ping(args, ctx):
    ctx.log.info("pong")
    return machine_info({"code": current_version()})


def run_job(job, handlers):
    buf = io.StringIO()
    jl = logging.getLogger(f"job{job['id']}")
    jl.setLevel(logging.INFO)
    h = logging.StreamHandler(buf)
    h.setFormatter(_fmt)
    jl.addHandler(h)
    jl.addHandler(_h)
    fn = handlers.get(job["kind"]) or {"ping": builtin_ping}.get(job["kind"])
    out = {}

    def target():
        try:
            if fn is None:
                raise RuntimeError(f"unknown job kind: {job['kind']} (known: {sorted(handlers) + ['ping']})")
            out["result"] = fn(job.get("args") or {}, Ctx(job["id"], jl))
            out["ok"] = True
        except Exception:
            jl.error(traceback.format_exc())
            out["ok"] = False

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(int((job.get("args") or {}).get("timeout", JOB_TIMEOUT)))
    timed_out = t.is_alive()
    if timed_out:
        jl.error("job timed out")
    try:
        result = json.loads(json.dumps(out.get("result"), default=str))
    except Exception:
        result = {"repr": repr(out.get("result"))[:5000]}
    rpc("nas_finish_job", token=TOKEN, agent=AGENT, id=job["id"], ok=bool(out.get("ok")) and not timed_out,
        result=result, log=buf.getvalue())
    log.info("job %s %s: %s", job["id"], job["kind"], "ok" if out.get("ok") and not timed_out else "failed")
    if timed_out:
        restart()  # the only way to stop a stuck thread


def main():
    if not (URL and KEY and TOKEN):
        log.error("SUPABASE_URL, SUPABASE_ANON_KEY and NAS_TOKEN must be set")
        time.sleep(300)
        return
    version, handlers = load_handlers()
    log.info("agent %s started, boot %s, code %s, handlers %s", AGENT, BOOT_VERSION, version or "-", sorted(handlers))
    poll, last_err, backoff = 30, None, 30
    while True:
        try:
            cfg = rpc("nas_checkin", token=TOKEN, agent=AGENT, version=version or "", info=machine_info({"last_error": last_err}))
            poll = max(5, int(cfg.get("poll_seconds") or 30))
            want = cfg.get("code_version") or ""
            if want and want != current_version():
                install_bundle(want)
                restart()
            job = rpc("nas_next_job", token=TOKEN, agent=AGENT)
            backoff = 30
            if job:
                run_job(job, handlers)
                continue  # look for the next job right away
        except Exception as e:
            last_err = f"{time.strftime('%F %T')} {e}"[:500]
            log.warning("loop error: %s", e)
            time.sleep(backoff)
            backoff = min(backoff * 2, 900)
            continue
        time.sleep(poll)


if __name__ == "__main__":
    main()
