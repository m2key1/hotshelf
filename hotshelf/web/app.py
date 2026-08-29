import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import generate_latest

from .. import runner
from ..config import Config
from ..state import State

CONFIG_PATH = os.environ.get("HOTSHELF_CONFIG", "/config/config.yaml")
STATE_PATH = os.environ.get("HOTSHELF_STATE", "/config/state.db")

cfg = Config(CONFIG_PATH)
state = State(STATE_PATH)
scheduler = BackgroundScheduler()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
templates.env.filters["gb"] = lambda b: f"{(b or 0) / 10**9:.1f}"
templates.env.filters["ts"] = lambda t: (
    datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M") if t else "never")


def scheduled_run():
    try:
        cfg.reload()
        runner.run(cfg, state)
    except Exception as exc:
        state.log("error", detail=f"scheduled run failed: {exc}")


def reschedule():
    scheduler.add_job(scheduled_run, "interval",
                      minutes=cfg["run"]["interval_minutes"],
                      id="policy", replace_existing=True)


@asynccontextmanager
async def lifespan(app):
    reschedule()
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(
    directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


def page(request, template, **context):
    last = state.get_kv("last_run", {})
    return templates.TemplateResponse(request, template, {
        "last": last, "dry_run": cfg["run"]["dry_run"], "cfg": cfg.data, **context})


@app.get("/", response_class=HTMLResponse)
def status(request: Request):
    last = state.get_kv("last_run", {})
    pinned = {p["key"] for p in state.pins()}
    return page(request, "status.html", hot=last.get("hot", []), pinned=pinned)


@app.get("/plan", response_class=HTMLResponse)
def plan_view(request: Request):
    """Compute and show what the next run would do, without moving anything."""
    try:
        _, wants, promotes, demotes, warnings = runner.compute(cfg, state)
    except Exception as exc:
        return page(request, "plan.html", error=str(exc),
                    promotes=[], demotes=[], warnings=[])
    return page(request, "plan.html", error=None,
                promotes=promotes, demotes=demotes, warnings=warnings)


@app.get("/pins", response_class=HTMLResponse)
def pins_view(request: Request):
    last = state.get_kv("last_run", {})
    return page(request, "pins.html", pins=state.pins(),
                series=last.get("series", []), movies=last.get("movies", []))


@app.post("/pins/add")
def pin_add(kind: str = Form(), key: str = Form(), name: str = Form(""),
            granularity: str = Form("")):
    state.add_pin(kind, key, name or key, granularity or None)
    state.log("pin", key, detail=f"{kind} granularity={granularity or 'default'}")
    return RedirectResponse("/pins", status_code=303)


@app.post("/pins/remove")
def pin_remove(kind: str = Form(), key: str = Form()):
    state.remove_pin(kind, key)
    state.log("unpin", key, detail=kind)
    return RedirectResponse("/pins", status_code=303)


@app.get("/config", response_class=HTMLResponse)
def config_view(request: Request):
    return page(request, "config.html", raw=cfg.raw(), saved=False, error=None)


@app.post("/config", response_class=HTMLResponse)
def config_save(request: Request, raw: str = Form()):
    try:
        cfg.save(raw)
        reschedule()
        state.log("config", detail="saved")
        return page(request, "config.html", raw=cfg.raw(), saved=True, error=None)
    except Exception as exc:
        return page(request, "config.html", raw=raw, saved=False, error=str(exc))


@app.post("/settings", response_class=HTMLResponse)
def settings_save(request: Request,
                  budget_mode: str = Form(), size_gb: int = Form(),
                  max_series: int = Form(), max_movies: int = Form(),
                  activity_window_days: int = Form(), episodes_ahead: str = Form(),
                  resume: str = Form(), fresh_imports: str = Form(),
                  fresh_keep_days: int = Form(), watched_grace_days: int = Form(),
                  users: str = Form(""), interval_minutes: int = Form(),
                  webhook_debounce_minutes: int = Form(), log_keep: int = Form(),
                  move_sidecars: str = Form(None), dry_run: str = Form(None),
                  jellyfin_url: str = Form(), union_prefix: str = Form(),
                  api_key: str = Form(""), movies_dir: str = Form(),
                  video_exts: str = Form(), verify: str = Form(),
                  free_space_margin_gb: int = Form()):
    """Apply the settings form onto the YAML config."""
    import yaml
    data = yaml.safe_load(cfg.raw()) or {}
    ahead = episodes_ahead if episodes_ahead in ("season", "series") else int(episodes_ahead)
    data["budget"] = {"mode": budget_mode, "size_gb": size_gb,
                      "max_series": max_series, "max_movies": max_movies}
    data.setdefault("policy", {}).update({
        "activity_window_days": activity_window_days, "episodes_ahead": ahead,
        "resume": resume, "fresh_imports": fresh_imports,
        "fresh_keep_days": fresh_keep_days, "watched_grace_days": watched_grace_days,
        "users": [u.strip() for u in users.split(",") if u.strip()],
        "move_sidecars": move_sidecars is not None,
    })
    data.setdefault("run", {}).update({
        "interval_minutes": interval_minutes, "dry_run": dry_run is not None,
        "webhook_debounce_minutes": webhook_debounce_minutes, "log_keep": log_keep})
    jf = data.setdefault("jellyfin", {})
    jf.update({"url": jellyfin_url, "union_prefix": union_prefix})
    if api_key:
        jf["api_key"] = api_key
    data["library"] = {
        "movies_dir": movies_dir.strip("/"),
        "video_exts": [e.strip() if e.strip().startswith(".") else "." + e.strip()
                       for e in video_exts.split(",") if e.strip()],
    }
    data["mover"] = {"verify": verify, "free_space_margin_gb": free_space_margin_gb}
    try:
        cfg.save(yaml.safe_dump(data, sort_keys=False))
        reschedule()
        state.log("config", detail="settings saved")
        return page(request, "config.html", raw=cfg.raw(), saved=True, error=None)
    except Exception as exc:
        return page(request, "config.html", raw=cfg.raw(), saved=False, error=str(exc))


@app.get("/log", response_class=HTMLResponse)
def log_view(request: Request):
    return page(request, "log.html", entries=state.log_entries())


@app.post("/run")
def run_now():
    threading.Thread(target=scheduled_run, daemon=True).start()
    return RedirectResponse("/log", status_code=303)


@app.post("/dryrun")
def toggle_dry_run():
    import yaml
    data = yaml.safe_load(cfg.raw()) or {}
    data.setdefault("run", {})["dry_run"] = not cfg["run"]["dry_run"]
    cfg.save(yaml.safe_dump(data, sort_keys=False))
    state.log("config", detail=f"dry_run={cfg['run']['dry_run']}")
    return RedirectResponse("/", status_code=303)


@app.post("/evict")
def evict(relpath: str = Form()):
    from ..mover import Mover
    if cfg["run"]["dry_run"]:
        state.log("would demote", relpath, detail="manual")
    else:
        mover = Mover(cfg["branches"]["fast"], cfg["branches"]["slow"],
                      cfg["policy"]["move_sidecars"],
                      cfg["mover"]["verify"], cfg["mover"]["free_space_margin_gb"])
        try:
            mover.demote(relpath)
            state.log("demote", relpath, detail="manual")
        except OSError as exc:
            state.log("demote", relpath, ok=False, detail=str(exc))
    return RedirectResponse("/", status_code=303)


@app.post("/webhook/jellyfin")
async def jellyfin_webhook(request: Request):
    """Playback events: count cache hit or miss, then run policy (debounced)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    _count_hit(payload.get("ItemId"))
    last = state.get_kv("last_run", {}).get("ts", 0)
    debounce = cfg["run"]["webhook_debounce_minutes"] * 60
    if time.time() - last > debounce:
        state.log("webhook", detail="jellyfin event, run triggered")
        threading.Thread(target=scheduled_run, daemon=True).start()
    else:
        state.log("webhook", detail="jellyfin event, debounced")
    return {"ok": True}


def _count_hit(item_id):
    """Best-effort: was this playback served from the fast branch?"""
    if not item_id:
        return
    from .. import metrics
    from ..jellyfin import Jellyfin
    try:
        jf = Jellyfin(cfg["jellyfin"]["url"], cfg["jellyfin"]["api_key"],
                      cfg["jellyfin"]["union_prefix"])
        relpath = jf.item_path(item_id)
        if not relpath:
            return
        if os.path.exists(os.path.join(cfg["branches"]["fast"], relpath)):
            metrics.cache_hits.inc()
        else:
            metrics.cache_misses.inc()
    except Exception:
        pass


@app.post("/flush")
def flush():
    """Demote everything on the fast branch, for rollback or a fresh start."""
    from ..library import scan
    from ..mover import Mover
    files = scan(cfg["branches"]["fast"], cfg["library"]["video_exts"])
    if cfg["run"]["dry_run"]:
        for relpath in sorted(files):
            state.log("would demote", relpath, files[relpath][0], detail="flush")
        return RedirectResponse("/log", status_code=303)
    mover = Mover(cfg["branches"]["fast"], cfg["branches"]["slow"],
                  cfg["policy"]["move_sidecars"],
                  cfg["mover"]["verify"], cfg["mover"]["free_space_margin_gb"])
    def work():
        for relpath in sorted(files):
            try:
                mover.demote(relpath)
                state.log("demote", relpath, files[relpath][0], detail="flush")
            except OSError as exc:
                state.log("demote", relpath, ok=False, detail=str(exc))
    threading.Thread(target=work, daemon=True).start()
    return RedirectResponse("/log", status_code=303)


@app.get("/metrics")
def metrics_endpoint():
    return PlainTextResponse(generate_latest(), media_type="text/plain")


@app.get("/api/homepage")
def homepage_widget():
    """Compact JSON for the Homepage dashboard customapi widget."""
    last = state.get_kv("last_run", {})
    used = last.get("cache_used", 0)
    budget = cfg["budget"]["size_gb"] * 10**9
    return JSONResponse({
        "used_gb": round(used / 10**9, 1),
        "budget_gb": cfg["budget"]["size_gb"],
        "percent": round(100 * used / budget, 1) if budget else 0,
        "hot_items": last.get("cache_items", 0),
        "dry_run": cfg["run"]["dry_run"],
    })
