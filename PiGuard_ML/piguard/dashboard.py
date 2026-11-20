"""Private PiGuard dashboard; privileged gateway actions use a fixed broker."""
import argparse
import csv
import hmac
import io
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, abort, g, redirect, render_template, request, session, url_for

from piguard.accounts import authenticate
from piguard.control import invoke
from piguard.network import inspect
from piguard.observer import load_config
from piguard.storage import connect, get_meta

REVIEWS = ("new", "benign", "needs_investigation")


def csv_safe(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text


def create_app(state, secret=None, gateway_call=invoke, network_probe=inspect):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secret or secrets.token_hex(32), MAX_CONTENT_LENGTH=8192,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_SECURE=True)
    login_attempts = {}

    @app.before_request
    def prepare():
        if request.host.split(":")[0] not in {"127.0.0.1", "localhost", "[::1]"}:
            abort(400)
        g.db = connect(state)
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        user_id = session.get("user_id")
        user = g.db.execute("SELECT id,username,role FROM users WHERE id=?", (user_id,)).fetchone() if user_id else None
        g.user = dict(user) if user else None
        if request.method == "POST":
            supplied = request.form.get("csrf", "")
            if not hmac.compare_digest(supplied, session["csrf"]):
                abort(403)
        if request.endpoint not in {"login", "healthz", "static"} and not g.user:
            if request.endpoint == "admin_authz":
                abort(401)
            if request.method == "GET":
                return redirect(url_for("login"))
            abort(401)

    @app.teardown_request
    def close(_):
        if "db" in g:
            g.db.close()

    @app.after_request
    def headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.template_filter("stamp")
    def stamp(value):
        return datetime.fromtimestamp(value, timezone.utc).strftime("%d %b %H:%M UTC") if value else "Not yet observed"

    def status():
        health = get_meta(g.db, "health", {})
        heartbeat = health.get("heartbeat", 0)
        health["stale"] = time.time()-heartbeat > 90
        health["ready"] = bool(health.get("model_ready") and not health.get("error") and not health["stale"])
        dns = get_meta(g.db, "dns", {"status": "not_checked"})
        dns["stale"] = time.time()-dns.get("checked_at", 0) > 180
        return health, dns

    def require_admin():
        if g.user["role"] != "admin":
            abort(403)

    def network_status(gateway=None):
        network = network_probe()
        if gateway is None:
            try:
                gateway = gateway_call("status")
            except (OSError, ValueError, TimeoutError):
                gateway = {}
        if isinstance(gateway, dict) and isinstance(gateway.get("power"), str):
            network["power"] = gateway["power"]
            network["power_ok"] = gateway.get("power_ok") is True
        power = network.get("power", "Not available")
        try:
            flags = int(power.removeprefix("throttled="), 16) if power.startswith("throttled=0x") else 0
        except ValueError:
            flags = 0
        if flags & (0x1 | 0x10000):
            network["power_warning"] = "The Pi reports undervoltage. Check its power supply and cable, then reboot and confirm 0x0 before enabling Tor."
        elif flags & 0x8:
            network["power_warning"] = "The Pi's soft temperature limit is active. Improve cooling before enabling Tor."
        elif flags & 0x80000:
            network["power_warning"] = "The Pi briefly reached its soft temperature limit earlier in this boot. The limit is no longer active; improve ventilation and monitor temperature under load."
        else:
            network["power_warning"] = "Check the Pi power and temperature status, then confirm 0x0 before enabling Tor."
        return network

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            key = request.remote_addr or "unknown"
            now = time.monotonic()
            attempts = [value for value in login_attempts.get(key, []) if now-value < 300]
            if len(attempts) >= 8:
                abort(429)
            user = authenticate(g.db, request.form.get("username", ""), request.form.get("password", ""))
            if user:
                session.clear()
                session["user_id"] = user["id"]
                session["csrf"] = secrets.token_urlsafe(32)
                login_attempts.pop(key, None)
                return redirect(url_for("overview"), code=303)
            attempts.append(now)
            login_attempts[key] = attempts
            return render_template("login.html", error="Invalid username or password"), 401
        return render_template("login.html", error=None)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"), code=303)

    @app.get("/authz/admin")
    def admin_authz():
        require_admin()
        return "", 204

    def filters():
        status_filter = request.args.get("status", "")
        if status_filter and status_filter not in REVIEWS:
            abort(400)
        domain = request.args.get("domain", "").strip()[:253]
        clauses, params = [], []
        if status_filter:
            clauses.append("review_status=?")
            params.append(status_filter)
        if domain:
            clauses.append("instr(domain,?)>0")
            params.append(domain.lower())
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), params, status_filter, domain

    @app.get("/healthz")
    def healthz():
        health, dns = status()
        return {"ready": health["ready"], "dns_ready": dns.get("status") == "reachable"}, 200 if health["ready"] else 503

    @app.get("/")
    def overview():
        today = datetime.now(timezone.utc).date()
        days = [(today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]
        daily = {row["day"]: {} for row in g.db.execute("SELECT DISTINCT day FROM daily WHERE day>=?", (days[0],))}
        for row in g.db.execute("SELECT day,key,count FROM daily WHERE day>=?", (days[0],)):
            daily.setdefault(row["day"], {})[row["key"]] = row["count"]
        timeline = [{"day": day, **daily.get(day, {})} for day in days]
        maxq = max((day.get("queries_observed", 0) for day in timeline), default=0) or 1
        current = timeline[-1]
        alerts = g.db.execute("SELECT id,domain,score,last_seen,review_status FROM alerts ORDER BY last_seen DESC LIMIT 8").fetchall()
        events = g.db.execute("SELECT kind,detail,actor,created_at FROM events ORDER BY id DESC LIMIT 8").fetchall()
        activity = ([{"kind": row["kind"], "title": row["detail"], "detail": f"{row['kind'].title()} by {row['actor']}",
                      "at": row["created_at"], "alert_id": None} for row in events] +
                    [{"kind": "alert", "title": row["domain"], "detail": f"DGA score {row['score']:.3f}",
                      "at": row["last_seen"], "alert_id": row["id"]} for row in alerts])
        activity.sort(key=lambda item: item["at"], reverse=True)
        health, dns = status()
        try:
            gateway = gateway_call("status")
        except (OSError, ValueError, TimeoutError):
            gateway = {"mode": "unavailable", "client_path": "unverified"}
        return render_template("overview.html", current=current, timeline=timeline, maxq=maxq,
                               activity=activity[:10], health=health, dns=dns, gateway=gateway)

    @app.get("/alerts")
    def index():
        where, params, status_filter, domain = filters()
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            abort(400)
        total = g.db.execute("SELECT count(*) FROM alerts" + where, params).fetchone()[0]
        page = min(page, max(1, (total+24)//25))
        alerts = g.db.execute("SELECT * FROM alerts" + where + " ORDER BY last_seen DESC,id DESC LIMIT 25 OFFSET ?",
                               [*params, (page-1)*25]).fetchall()
        counts = {row["key"]: row["count"] for row in g.db.execute("SELECT key,sum(count) count FROM daily WHERE day=date('now') GROUP BY key")}
        health, dns = status()
        return render_template("index.html", alerts=alerts, total=total, page=page, pages=max(1,(total+24)//25),
                               status_filter=status_filter, domain=domain, counts=counts, health=health, dns=dns)

    @app.route("/alerts/<int:alert_id>", methods=["GET", "POST"])
    def detail(alert_id):
        row = g.db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if row is None:
            abort(404)
        if request.method == "POST":
            require_admin()
            review = request.form.get("review_status")
            note = request.form.get("note", "").strip()
            if review not in REVIEWS or len(note) > 2000:
                abort(400)
            with g.db:
                g.db.execute("INSERT INTO review_log(alert_id,previous_status,new_status,note,changed_at) VALUES(?,?,?,?,?)",
                             (alert_id, row["review_status"], review, note, time.time()))
                g.db.execute("UPDATE alerts SET review_status=?,note=?,reviewed_at=? WHERE id=?",
                             (review, note, time.time(), alert_id))
                g.db.execute("INSERT INTO events(kind,detail,actor,created_at) VALUES(?,?,?,?)",
                             ("review", row["domain"][:253], g.user["username"], time.time()))
            return redirect(url_for("detail", alert_id=alert_id), code=303)
        history = g.db.execute("SELECT * FROM review_log WHERE alert_id=? ORDER BY id DESC LIMIT 30", (alert_id,)).fetchall()
        return render_template("detail.html", alert=row, features=json.loads(row["features"]) if row["features"] else {},
                               statuses=json.loads(row["statuses"]), history=history, reviews=REVIEWS)

    @app.get("/export.csv")
    def export():
        where, params, _, _ = filters()
        rows = g.db.execute("SELECT day,domain,model_id,score,threshold,query_count,review_status,note FROM alerts" + where + " ORDER BY last_seen DESC", params)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([d[0] for d in rows.description])
        for row in rows:
            writer.writerow([csv_safe(v) for v in row])
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=piguard-alerts.csv"})

    @app.get("/gateway")
    def gateway_page():
        try:
            gateway = gateway_call("status")
        except (OSError, ValueError, TimeoutError):
            gateway = {"mode": "unavailable", "client_path": "unverified", "error": "Gateway broker unavailable"}
        return render_template("gateway.html", gateway=gateway, network=network_status(gateway), result=None)

    @app.post("/gateway/<action>")
    def gateway_action(action):
        require_admin()
        if action not in {"check", "enable", "disable", "block"}:
            abort(404)
        try:
            result = gateway_call(action)
        except (OSError, ValueError, TimeoutError):
            result = {"ok": False, "error": "Gateway broker unavailable", "client_path": "unverified"}
        with g.db:
            g.db.execute("INSERT INTO events(kind,detail,actor,created_at) VALUES(?,?,?,?)",
                         ("gateway", f"{action}: {'ok' if result.get('ok') else 'failed'}", g.user["username"], time.time()))
        try:
            gateway = gateway_call("status")
        except (OSError, ValueError, TimeoutError):
            gateway = {"mode": "unavailable", "client_path": "unverified"}
        return render_template("gateway.html", gateway=gateway, network=network_status(gateway), result=result), 200 if result.get("ok") else 503

    @app.get("/setup")
    def setup():
        return render_template("setup.html", network=network_status())

    return app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--secret-file", required=True)
    args = p.parse_args()
    os.umask(0o077)
    cfg = load_config(args.config)
    from waitress import serve
    app = create_app(Path(cfg["state_db"]), Path(args.secret_file).read_text().strip())
    print(f"PiGuard dashboard: http://127.0.0.1:{args.port}", flush=True)
    serve(app, host="127.0.0.1", port=args.port, threads=2, clear_untrusted_proxy_headers=True)


if __name__ == "__main__":
    main()
