from __future__ import annotations

import json
import hmac
import logging
import os
import secrets
from typing import Any

from flask import Flask, g, jsonify, redirect, request, send_file, send_from_directory, session, url_for
from dotenv import dotenv_values
from supabase import Client, create_client

from excel_report import build_excel_report
from fleet_management import (
    FleetManagementError,
    FleetManager,
    _supabase_project_url,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "").strip().lower() in {
    "1", "true", "yes", "on",
}
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 14

manager: FleetManager | None = None
logger = logging.getLogger(__name__)

def _supabase_setting(name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    return dotenv_values(os.path.join(BASE_DIR, ".env")).get(name)


def get_auth_client() -> Client:
    request_client = getattr(g, "supabase_auth_client", None)
    if request_client is not None:
        return request_client
    project_url = _supabase_setting("SUPABASE_URL")
    anon_key = _supabase_setting("SUPABASE_ANON_KEY")
    if not project_url or not anon_key:
        raise FleetManagementError(
            "Supabase login is not configured. Set SUPABASE_URL and "
            "SUPABASE_ANON_KEY in the project .env file."
        )
    try:
        request_client = create_client(_supabase_project_url(project_url), anon_key)
        g.supabase_auth_client = request_client
        return request_client
    except Exception as exc:
        raise FleetManagementError(f"Could not initialize Supabase Auth: {exc}") from exc


def get_manager() -> FleetManager:
    global manager
    if manager is None:
        manager = FleetManager()
    return manager


def _json_error(message: str, status: int) -> tuple[Any, int]:
    return jsonify({"error": message}), status


def _clear_auth() -> None:
    session.clear()
    g.clear_auth_cookies = True


def _secure_cookies() -> bool:
    configured = os.environ.get("COOKIE_SECURE")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes", "on"}
    return request.is_secure


@app.teardown_request
def close_auth_client(_error: BaseException | None) -> None:
    request_client = getattr(g, "supabase_auth_client", None)
    if request_client is None:
        return
    request_client.auth.close()
    request_client.postgrest.session.close()


@app.before_request
def enforce_authentication() -> Any:
    if request.endpoint == "auth_logout" and request.method == "POST":
        return None

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.path.startswith("/api/"):
        expected = session.get("csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            return _json_error("Your session token is missing or expired. Refresh and try again.", 403)

    public_endpoints = {"login_page", "auth_csrf", "auth_login", "auth_logout"}
    if request.endpoint == "static" and request.path != "/static/index.html":
        return None
    if request.endpoint in public_endpoints:
        return None

    protected_path = (
        request.path in {"/", "/static/index.html"}
        or request.path.startswith("/api/")
    )
    if not protected_path:
        return None

    if app.testing and app.config.get("TEST_AUTH_BYPASS"):
        g.current_user = {"id": "test-user", "email": "test@example.com"}
        return None

    if not session.get("user_id"):
        _clear_auth()
        if request.path.startswith("/api/"):
            return _json_error("Authentication required.", 401)
        return redirect(url_for("login_page"))

    access_token = request.cookies.get("glfs_access_token")
    refresh_token = request.cookies.get("glfs_refresh_token")
    auth = get_auth_client().auth

    if access_token:
        try:
            user_response = auth.get_user(access_token)
            user = getattr(user_response, "user", None)
            if user and str(getattr(user, "id", "")) == str(session.get("user_id")):
                g.current_user = {
                    "id": str(user.id),
                    "email": getattr(user, "email", None) or session.get("email", ""),
                }
                return None
        except Exception:
            pass

    if refresh_token:
        try:
            refreshed = auth.refresh_session(refresh_token)
            refreshed_session = getattr(refreshed, "session", None)
            user = getattr(refreshed, "user", None)
            if refreshed_session and user and str(getattr(user, "id", "")) == str(session.get("user_id")):
                g.auth_tokens = refreshed_session
                g.current_user = {
                    "id": str(user.id),
                    "email": getattr(user, "email", None) or session.get("email", ""),
                }
                return None
        except Exception as exc:
            status = getattr(exc, "status", None)
            if status not in {400, 401}:
                logger.warning("Supabase Auth could not refresh the session (status %s).", status)
                return _json_error("Authentication is temporarily unavailable. Please retry.", 503)

    _clear_auth()
    if request.path.startswith("/api/"):
        return _json_error("Your sign-in expired. Please sign in again.", 401)
    return redirect(url_for("login_page"))


@app.after_request
def set_auth_cookies(response: Any) -> Any:
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    auth_tokens = getattr(g, "auth_tokens", None)
    secure = _secure_cookies()
    if auth_tokens is not None:
        access_token = getattr(auth_tokens, "access_token", None)
        refresh_token = getattr(auth_tokens, "refresh_token", None)
        if access_token:
            response.set_cookie(
                "glfs_access_token",
                access_token,
                max_age=getattr(auth_tokens, "expires_in", 3600),
                httponly=True,
                secure=secure,
                samesite="Lax",
                path="/",
            )
        if refresh_token:
            response.set_cookie(
                "glfs_refresh_token",
                refresh_token,
                max_age=60 * 60 * 24 * 30,
                httponly=True,
                secure=secure,
                samesite="Lax",
                path="/",
            )
    if getattr(g, "clear_auth_cookies", False):
        for cookie_name in ("glfs_access_token", "glfs_refresh_token"):
            response.delete_cookie(
                cookie_name,
                path="/",
                secure=secure,
                httponly=True,
                samesite="Lax",
            )
    return response


@app.errorhandler(FleetManagementError)
def handle_fleet_error(error: FleetManagementError) -> tuple[Any, int]:
    return jsonify({"error": str(error)}), 503


@app.errorhandler(404)
def handle_not_found(_error: Any) -> tuple[Any, int]:
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(405)
def handle_method_not_allowed(_error: Any) -> tuple[Any, int]:
    return jsonify({"error": "Method not allowed"}), 405


@app.route("/")
def index() -> Any:
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/login")
def login_page() -> Any:
    if session.get("user_id"):
        return redirect(url_for("index"))
    return send_from_directory(STATIC_DIR, "login.html")


@app.route("/api/auth/csrf")
def auth_csrf() -> Any:
    token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return jsonify({"csrf_token": token})


@app.route("/api/auth/login", methods=["POST"])
def auth_login() -> Any:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json_error("Provide your email and password.", 400)
    email = str(payload.get("email", "")).strip()
    password = payload.get("password")
    if not email or not isinstance(password, str) or not password:
        return _json_error("Enter your email and password.", 400)
    try:
        auth_response = get_auth_client().auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except FleetManagementError:
        raise
    except Exception as exc:
        status = getattr(exc, "status", None)
        error_code = getattr(exc, "code", None)
        if status in {400, 401} or error_code == "invalid_credentials":
            return _json_error("Sign-in failed. Check your email and password and try again.", 401)
        logger.warning("Supabase Auth sign-in request failed (status %s).", status)
        return _json_error("Supabase authentication is temporarily unavailable.", 502)

    auth_session = getattr(auth_response, "session", None)
    user = getattr(auth_response, "user", None)
    if not auth_session or not user or not getattr(auth_session, "access_token", None):
        return _json_error("Supabase did not return a valid sign-in session.", 502)

    session.clear()
    session.permanent = True
    session["user_id"] = str(user.id)
    session["email"] = getattr(user, "email", None) or email
    session["csrf_token"] = secrets.token_urlsafe(32)
    g.auth_tokens = auth_session
    return jsonify(
        {
            "user": {"id": session["user_id"], "email": session["email"]},
            "redirect": url_for("index"),
        }
    )


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout() -> Any:
    _clear_auth()
    return jsonify({"redirect": url_for("login_page")})


@app.route("/api/auth/me")
def auth_me() -> Any:
    return jsonify(
        {
            "user": g.current_user,
            "csrf_token": session.get("csrf_token"),
        }
    )


@app.route("/api/bootstrap")
def bootstrap() -> Any:
    fleet = get_manager()
    return jsonify(
        {
            "dashboard": fleet.dashboard(),
            "vehicles": fleet.list_vehicles(),
            "drivers": fleet.list_drivers(),
            "assignments": fleet.list_assignments(),
            "maintenance": fleet.list_maintenance(),
            "fuel_logs": fleet.list_fuel_logs(),
            "trips": fleet.list_trips(),
            "csrf_token": session.get("csrf_token"),
            "user": g.current_user,
        }
    )


def _body() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    return payload


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field, "")).strip()
    if not value:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is required")
    return value


def _integer(payload: dict[str, Any], field: str, default: int | None = None) -> int:
    value = payload.get(field, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a whole number") from exc


def _number(payload: dict[str, Any], field: str, default: float | None = None) -> float:
    value = payload.get(field, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a number") from exc


def _optional_text(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    return str(value).strip() or None if value is not None else None


def _payroll_period_from_request(payload: dict[str, Any]) -> tuple[str, str]:
    start_date = _required_text(payload, "start_date")
    end_date = _required_text(payload, "end_date")
    return start_date, end_date


@app.route("/api/payroll")
def payroll_report() -> Any:
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    try:
        return jsonify(get_manager().payroll_report(start_date, end_date))
    except ValueError as exc:
        return _json_error(str(exc), 400)


@app.route("/api/payroll/review", methods=["POST"])
def payroll_review() -> Any:
    try:
        payload = _body()
        start_date, end_date = _payroll_period_from_request(payload)
        result = get_manager().review_payroll(
            start_date, end_date, str(g.current_user["id"])
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)
    return jsonify(result)


@app.route("/api/payroll/cash-advances", methods=["POST"])
def payroll_cash_advance() -> Any:
    try:
        payload = _body()
        start_date, end_date = _payroll_period_from_request(payload)
        result = get_manager().add_cash_advance(
            start_date=start_date,
            end_date=end_date,
            driver_id=_integer(payload, "driver_id"),
            advance_date=_required_text(payload, "advance_date"),
            amount=payload.get("amount"),
            remarks=_optional_text(payload, "remarks"),
            reference=_optional_text(payload, "reference"),
            actor_id=str(g.current_user["id"]),
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)
    return jsonify({"data": result}), 201


@app.route("/api/payroll/overdrafts", methods=["POST"])
def payroll_overdraft() -> Any:
    try:
        payload = _body()
        result = get_manager().add_overdraft(
            driver_id=_integer(payload, "driver_id"),
            transaction_type=_required_text(payload, "transaction_type"),
            amount=payload.get("amount"),
            effective_date=_required_text(payload, "effective_date"),
            remarks=_optional_text(payload, "remarks"),
            actor_id=str(g.current_user["id"]),
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)
    return jsonify({"data": result}), 201


@app.route("/api/payroll/finalize", methods=["POST"])
def payroll_finalize() -> Any:
    try:
        payload = _body()
        start_date, end_date = _payroll_period_from_request(payload)
        settle_overdraft = payload.get("settle_overdraft", False)
        if not isinstance(settle_overdraft, bool):
            raise ValueError("settle_overdraft must be true or false")
        result = get_manager().finalize_payroll(
            start_date,
            end_date,
            settle_overdraft,
            str(g.current_user["id"]),
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)
    return jsonify(result)


def _create_record(resource: str, payload: dict[str, Any]) -> dict[str, Any]:
    fleet = get_manager()
    if resource == "vehicles":
        return fleet.add_vehicle(
            plate_number=_required_text(payload, "plate_number"),
            make=_required_text(payload, "make"),
            model=_required_text(payload, "model"),
            year=_integer(payload, "year"),
            color=_optional_text(payload, "color"),
            status=_optional_text(payload, "status") or "available",
            odometer=_integer(payload, "odometer", 0),
            registration_expiry=_optional_text(payload, "registration_expiry"),
            insurance_expiry=_optional_text(payload, "insurance_expiry"),
        )
    if resource == "drivers":
        return fleet.add_driver(
            name=_required_text(payload, "name"),
            license_number=_required_text(payload, "license_number"),
            phone=_optional_text(payload, "phone"),
            email=_optional_text(payload, "email"),
            status=_optional_text(payload, "status") or "active",
        )
    if resource == "assignments":
        return fleet.assign_vehicle(
            driver_id=_integer(payload, "driver_id"),
            vehicle_id=_integer(payload, "vehicle_id"),
            assigned_date=_optional_text(payload, "assigned_date"),
            notes=_optional_text(payload, "notes"),
        )
    if resource == "maintenance":
        return fleet.add_maintenance(
            vehicle_id=_integer(payload, "vehicle_id"),
            service_type=_required_text(payload, "service_type"),
            description=_optional_text(payload, "description"),
            cost=_number(payload, "cost", 0),
            performed_on=_optional_text(payload, "performed_on"),
        )
    if resource == "fuel":
        return fleet.add_fuel(
            vehicle_id=_integer(payload, "vehicle_id"),
            fuel_type=_required_text(payload, "fuel_type"),
            quantity=_number(payload, "quantity"),
            price_per_liter=_number(payload, "price_per_liter"),
            total_cost=(
                _number(payload, "total_cost")
                if payload.get("total_cost") not in (None, "")
                else None
            ),
            logged_on=_optional_text(payload, "logged_on"),
        )
    if resource == "trips":
        origin = _required_text(payload, "origin")
        destination = _required_text(payload, "destination")
        shipment_date = _optional_text(payload, "shipment_date")
        return fleet.add_trip(
            vehicle_id=_integer(payload, "vehicle_id"),
            driver_id=_integer(payload, "driver_id"),
            route=f"{origin} to {destination}",
            start_odometer=0,
            end_odometer=0,
            trip_date=shipment_date,
            ism_no=_optional_text(payload, "ism_no"),
            shipment_date=shipment_date,
            time_in=_optional_text(payload, "time_in"),
            time_out=_optional_text(payload, "time_out"),
            origin=origin,
            destination=destination,
            load_details=_optional_text(payload, "load_details"),
            trip_fuel=_optional_text(payload, "trip_fuel"),
        )
    raise ValueError("Unknown resource")


@app.route(
    "/api/<any(vehicles,drivers,assignments,maintenance,fuel,trips):resource>",
    methods=["POST"],
)
def create_record(resource: str) -> Any:
    if resource not in {"vehicles", "drivers", "assignments", "maintenance", "fuel", "trips"}:
        return jsonify({"error": "Unknown resource"}), 404
    try:
        record = _create_record(resource, _body())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"data": record}), 201


@app.route(
    "/api/<any(vehicles,drivers,assignments,maintenance,fuel,trips):resource>/<int:record_id>",
    methods=["DELETE"],
)
def delete_record(resource: str, record_id: int) -> Any:
    method_names = {
        "vehicles": "delete_vehicle",
        "drivers": "delete_driver",
        "assignments": "delete_assignment",
        "maintenance": "delete_maintenance",
        "fuel": "delete_fuel_log",
        "trips": "delete_trip",
    }
    method_name = method_names.get(resource)
    if method_name is None:
        return jsonify({"error": "Unknown resource"}), 404
    getattr(get_manager(), method_name)(record_id)
    return jsonify({"message": "Record deleted"})


@app.route("/api/export")
def export_report() -> Any:
    fleet = get_manager()
    report = {
        "vehicles": fleet.list_vehicles(),
        "drivers": fleet.list_drivers(),
        "assignments": fleet.list_assignments(),
        "trips": fleet.list_trips(),
        "maintenance": fleet.list_maintenance(),
        "fuel_logs": fleet.list_fuel_logs(),
        "dashboard": fleet.dashboard(),
    }
    return send_file(
        build_excel_report(report),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="fleet_system_report.xlsx",
    )


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
