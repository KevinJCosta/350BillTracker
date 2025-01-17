from flask import render_template
from werkzeug import exceptions

from . import settings
from .app import app


@app.route("/healthz", methods=["GET"])
def healthz():
    return "Healthy!"


@app.route("/api/<path:path>")
def api_not_found(path):
    raise exceptions.NotFound()


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    return render_template("index.html")


@app.after_request
def after_request(response):
    response.headers[
        "Content-Security-Policy"
    ] = "default-src 'self'; style-src 'self' fonts.googleapis.com; font-src fonts.googleapis.com fonts.gstatic.com"
    response.headers["X-Frame-Options"] = "DENY"

    if not settings.DISABLE_STRICT_TRANSPORT_SECURITY:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


# BUG: This seems to leave open stale SQLA sessions
