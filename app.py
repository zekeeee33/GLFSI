from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
import uuid
import warnings
from datetime import timedelta
from io import BytesIO
from typing import Any

from flask import Flask, g, jsonify, redirect, request, send_file, send_from_directory, session, url_for
from dotenv import dotenv_values
from PIL import Image, UnidentifiedImageError
from supabase import Client, create_client

from excel_report import build_excel_report, build_trip_excel_report
from fleet_management import (
    FleetManagementError,
    FleetManager,
    _supabase_project_url,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["DOCUMENT_IMAGE_MAX_BYTES"] = int(
    os.environ.get("DOCUMENT_IMAGE_MAX_BYTES", str(10 * 1024 * 1024))
)
app.config["MAX_CONTENT_LENGTH"] = max(
    16 * 1024 * 1024, app.config["DOCUMENT_IMAGE_MAX_BYTES"] + 1024 * 1024
)
app.config["DOCUMENT_IMAGE_BUCKET"] = os.environ.get(
    "DOCUMENT_IMAGE_BUCKET", "fleet-trip-documents"
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "").strip().lower() in {
    "1", "true", "yes", "on",
}
SESSION_IDLE_TIMEOUT_SECONDS = 3 * 60
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(seconds=SESSION_IDLE_TIMEOUT_SECONDS)

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


def _user_role() -> str:
    return str((g.current_user or {}).get("role") or "administrator").lower()


def _is_dispatcher() -> bool:
    return _user_role() == "dispatcher"


def _role_for_auth_user(user: Any) -> str:
    app_metadata = getattr(user, "app_metadata", None) or {}
    user_metadata = getattr(user, "user_metadata", None) or {}
    trusted_role = str(app_metadata.get("role") or "").strip().lower()
    # A user-metadata dispatcher designation can only reduce access, never grant it.
    if str(user_metadata.get("role") or "").strip().lower() == "dispatcher":
        return "dispatcher"
    if trusted_role in {"administrator", "dispatcher"}:
        return trusted_role
    return "administrator"


def _authorize_dispatcher_request() -> Any:
    if not _is_dispatcher():
        return None
    if request.path.startswith("/api/payroll") or request.path == "/api/export":
        return _json_error("This function is only available to administrators.", 403)
    if request.path.startswith("/api/") and request.path not in {
        "/api/auth/me",
        "/api/bootstrap",
        "/api/export/trips",
    }:
        resource = request.path.split("/")[2] if len(request.path.split("/")) > 2 else ""
        if resource not in {"trips", "fuel", "maintenance"}:
            return _json_error("Dispatchers are not authorized to access this function.", 403)
        if request.method == "DELETE":
            return _json_error("Dispatchers cannot delete submitted records.", 403)
        is_trip_update = (
            request.method == "PATCH"
            and request.path.startswith("/api/trips/")
            and request.path.removeprefix("/api/trips/").isdigit()
        )
        if request.method not in {"GET", "POST"} and not is_trip_update:
            return _json_error("Dispatchers cannot modify submitted records this way.", 403)
    return None


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

    protected_path = (
        request.path in {"/", "/static/index.html"}
        or request.path.startswith("/api/")
    )
    if (
        protected_path
        and not (app.testing and app.config.get("TEST_AUTH_BYPASS"))
        and session.get("user_id")
        and time.time() - session.get("last_activity", 0) >= SESSION_IDLE_TIMEOUT_SECONDS
    ):
        _clear_auth()
        if request.path.startswith("/api/") and request.endpoint not in {
            "auth_csrf", "auth_login", "auth_logout",
        }:
            return _json_error("Your session expired due to inactivity. Please sign in again.", 401)
        if request.path in {"/", "/static/index.html"}:
            return redirect(url_for("login_page", expired="1"))

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

    if not protected_path:
        return None

    if app.testing and app.config.get("TEST_AUTH_BYPASS"):
        g.current_user = {"id": "test-user", "email": "test@example.com", "role": "administrator"}
        session.setdefault("user_role", "administrator")
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
                session["last_activity"] = time.time()
                role = _role_for_auth_user(user)
                session["user_role"] = role
                g.current_user = {
                    "id": str(user.id),
                    "email": getattr(user, "email", None) or session.get("email", ""),
                    "role": role,
                    "full_name": (
                        (getattr(user, "user_metadata", None) or {}).get("full_name")
                        or (getattr(user, "user_metadata", None) or {}).get("name")
                    ),
                }
                return _authorize_dispatcher_request()
        except Exception:
            pass

    if refresh_token:
        try:
            refreshed = auth.refresh_session(refresh_token)
            refreshed_session = getattr(refreshed, "session", None)
            user = getattr(refreshed, "user", None)
            if refreshed_session and user and str(getattr(user, "id", "")) == str(session.get("user_id")):
                g.auth_tokens = refreshed_session
                session["last_activity"] = time.time()
                role = _role_for_auth_user(user)
                session["user_role"] = role
                g.current_user = {
                    "id": str(user.id),
                    "email": getattr(user, "email", None) or session.get("email", ""),
                    "role": role,
                    "full_name": (
                        (getattr(user, "user_metadata", None) or {}).get("full_name")
                        or (getattr(user, "user_metadata", None) or {}).get("name")
                    ),
                }
                return _authorize_dispatcher_request()
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
    if request.path.startswith("/api/") or request.path in {
        "/", "/static/index.html", "/static/app.js", "/static/style.css",
    }:
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
                httponly=True,
                secure=secure,
                samesite="Lax",
                path="/",
            )
        if refresh_token:
            response.set_cookie(
                "glfs_refresh_token",
                refresh_token,
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


@app.errorhandler(413)
def handle_request_too_large(_error: Any) -> tuple[Any, int]:
    return _json_error("The uploaded image exceeds the request size limit.", 413)


@app.route("/")
def index() -> Any:
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/login")
def login_page() -> Any:
    if request.args.get("expired") == "1":
        _clear_auth()
        return send_from_directory(STATIC_DIR, "login.html")
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
    role = _role_for_auth_user(user)
    session["user_id"] = str(user.id)
    session["email"] = getattr(user, "email", None) or email
    session["user_role"] = role
    session["csrf_token"] = secrets.token_urlsafe(32)
    session["last_activity"] = time.time()
    g.auth_tokens = auth_session
    return jsonify(
        {
            "user": {
                "id": session["user_id"],
                "email": session["email"],
                "role": role,
                "full_name": (
                    (getattr(user, "user_metadata", None) or {}).get("full_name")
                    or (getattr(user, "user_metadata", None) or {}).get("name")
                ),
            },
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
    user_id = str((g.current_user or {}).get("id") or session.get("user_id") or "")
    if _is_dispatcher():
        if not user_id:
            return _json_error("Authenticated dispatcher identity is missing.", 403)
        trips = fleet.list_trips(user_id=user_id)
        fuel_logs = fleet.list_fuel_logs(user_id=user_id)
        maintenance = fleet.list_maintenance(user_id=user_id)
        today = time.strftime("%Y-%m-%d")
        _add_document_links(trips, "manifest_object_path", "manifest_image_url", "trip_manifest_image")
        _add_document_links(fuel_logs, "invoice_object_path", "invoice_image_url", "fuel_invoice_image")
        return jsonify(
            {
                "dashboard": {
                    "total_trips": len(trips),
                    "today_trips": sum(
                        str(trip.get("shipment_date") or "")[:10] == today
                        for trip in trips
                    ),
                    "total_fuel_logs": len(fuel_logs),
                    "total_maintenance": len(maintenance),
                },
                "vehicles": [
                    {key: row.get(key) for key in ("id", "plate_number", "make", "model")}
                    for row in fleet.list_vehicles()
                ],
                "drivers": [
                    {key: row.get(key) for key in ("id", "name", "status")}
                    for row in fleet.list_drivers()
                ],
                "assignments": [],
                "maintenance": maintenance,
                "fuel_logs": fuel_logs,
                "trips": trips,
                "csrf_token": session.get("csrf_token"),
                "user": g.current_user,
            }
        )
    trips = fleet.list_trips()
    fuel_logs = fleet.list_fuel_logs()
    _add_document_links(trips, "manifest_object_path", "manifest_image_url", "trip_manifest_image")
    _add_document_links(fuel_logs, "invoice_object_path", "invoice_image_url", "fuel_invoice_image")
    return jsonify(
        {
            "dashboard": fleet.dashboard(),
            "vehicles": fleet.list_vehicles(),
            "drivers": fleet.list_drivers(),
            "assignments": fleet.list_assignments(),
            "maintenance": fleet.list_maintenance(),
            "fuel_logs": fuel_logs,
            "trips": trips,
            "csrf_token": session.get("csrf_token"),
            "user": g.current_user,
        }
    )


def _add_document_links(
    rows: list[dict[str, Any]], path_field: str, url_field: str, endpoint: str
) -> None:
    for row in rows:
        object_path = row.pop(path_field, None)
        if object_path:
            row[url_field] = url_for(endpoint, **{
                "trip_id" if endpoint == "trip_manifest_image" else "fuel_id": row["id"]
            })


def _validated_image(file_storage: Any) -> tuple[bytes, str, str]:
    filename = str(file_storage.filename or "").strip()
    if not filename:
        raise ValueError("Choose an image file.")
    max_bytes = app.config["DOCUMENT_IMAGE_MAX_BYTES"]
    image_bytes = file_storage.stream.read(max_bytes + 1)
    if len(image_bytes) > max_bytes:
        raise ValueError(f"Image must be no larger than {max_bytes // (1024 * 1024)} MB.")
    if not image_bytes:
        raise ValueError("The selected image is empty.")

    formats = {
        "JPEG": ("image/jpeg", "jpg"),
        "PNG": ("image/png", "png"),
        "WEBP": ("image/webp", "webp"),
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(image_bytes))
            image_format = image.format
            if image_format not in formats:
                raise ValueError("Use a JPG, PNG, or WEBP image.")
            if image.width < 1 or image.height < 1 or image.width * image.height > 40_000_000:
                raise ValueError("Image dimensions are invalid or too large.")
            image.verify()
    except ValueError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("The selected file is not a valid image.") from exc
    mime_type, extension = formats[image_format]
    return image_bytes, mime_type, extension


def _document_user_id() -> str | None:
    if not _is_dispatcher():
        return None
    return str((g.current_user or {}).get("id") or session.get("user_id") or "")


def _record_for_document(kind: str, record_id: int) -> dict[str, Any]:
    fleet = get_manager()
    user_id = _document_user_id()
    try:
        if kind == "trip":
            return fleet.get_trip(record_id, user_id=user_id)
        return fleet.get_fuel(record_id, user_id=user_id)
    except FleetManagementError as exc:
        status = 403 if _is_dispatcher() else 404
        return {"_error": str(exc), "_status": status}


def _handle_document_image(kind: str, record_id: int) -> Any:
    record = _record_for_document(kind, record_id)
    if "_error" in record:
        return _json_error(record["_error"], record["_status"])

    is_trip = kind == "trip"
    path_field = "manifest_object_path" if is_trip else "invoice_object_path"
    if request.method == "POST":
        image_file = request.files.get("image")
        if image_file is None:
            return _json_error("Attach an image using the 'image' field.", 400)
        try:
            image_bytes, mime_type, extension = _validated_image(image_file)
        except ValueError as exc:
            return _json_error(str(exc), 400)
        owner_id = str(record.get("created_by") or (g.current_user or {}).get("id") or "admin")
        object_path = f"{kind}s/{record_id}/{owner_id}/{uuid.uuid4().hex}.{extension}"
        storage = get_manager().client.storage.from_(app.config["DOCUMENT_IMAGE_BUCKET"])
        uploaded = False
        try:
            storage.upload(object_path, image_bytes, {"content-type": mime_type})
            uploaded = True
            if is_trip:
                get_manager().set_trip_manifest_path(
                    record_id,
                    object_path,
                    user_id=_document_user_id(),
                    edited_by=str((g.current_user or {}).get("id") or session.get("user_id") or ""),
                    editor_email=(g.current_user or {}).get("email") or session.get("email"),
                )
            else:
                get_manager().set_fuel_invoice_path(
                    record_id, object_path, user_id=_document_user_id()
                )
            if record.get(path_field):
                try:
                    storage.remove([record[path_field]])
                except Exception:
                    logger.warning("Could not remove replaced document object.", exc_info=True)
        except Exception:
            if uploaded:
                try:
                    storage.remove([object_path])
                except Exception:
                    logger.exception("Could not clean up an unlinked document object.")
            logger.exception("Could not store a trip document image.")
            return _json_error("Could not save the image. Please retry.", 503)
        return jsonify({"message": "Image uploaded successfully."}), 201

    object_path = record.get(path_field)
    if not object_path:
        return _json_error("No image has been uploaded for this record.", 404)
    try:
        image_bytes = get_manager().client.storage.from_(
            app.config["DOCUMENT_IMAGE_BUCKET"]
        ).download(object_path)
    except Exception:
        logger.exception("Could not retrieve a trip document image.")
        return _json_error("Could not retrieve the image. Please retry.", 503)

    mime_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(os.path.splitext(object_path)[1].lower(), "application/octet-stream")
    response = send_file(
        BytesIO(image_bytes),
        mimetype=mime_type,
        as_attachment=False,
        download_name=f"{kind}-{record_id}{os.path.splitext(object_path)[1].lower()}",
        max_age=0,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    return response


@app.route("/api/trips/<int:trip_id>/manifest", methods=["GET", "POST"])
def trip_manifest_image(trip_id: int) -> Any:
    return _handle_document_image("trip", trip_id)


@app.route("/api/trips/<int:trip_id>/history")
def trip_edit_history(trip_id: int) -> Any:
    user_id = _document_user_id()
    try:
        history = get_manager().list_trip_edit_history(trip_id, user_id=user_id)
    except FleetManagementError as exc:
        message = str(exc)
        if "not found" in message.lower():
            return _json_error(message, 403 if _is_dispatcher() else 404)
        if "do not have access" in message.lower():
            return _json_error(message, 403)
        raise
    return jsonify({"history": history})


@app.route("/api/trips/<int:trip_id>", methods=["PATCH"])
def update_trip(trip_id: int) -> Any:
    try:
        payload = _body()
        origin = _required_text(payload, "origin")
        destination = _required_text(payload, "destination")
        actor = g.current_user or {}
        editor_id = str(actor.get("id") or session.get("user_id") or "")
        record = get_manager().update_trip(
            trip_id,
            {
                "ism_no": _optional_text(payload, "ism_no"),
                "shipment_date": _required_text(payload, "shipment_date"),
                "time_in": _optional_text(payload, "time_in"),
                "time_out": _optional_text(payload, "time_out"),
                "origin": origin,
                "destination": destination,
                "vehicle_id": (
                    _integer(payload, "vehicle_id")
                    if payload.get("vehicle_id") not in (None, "")
                    else None
                ),
                "driver_id": (
                    _integer(payload, "driver_id")
                    if payload.get("driver_id") not in (None, "")
                    else None
                ),
                "load_details": _optional_text(payload, "load_details"),
                "trip_fuel": _optional_text(payload, "trip_fuel"),
                "notes": _optional_text(payload, "notes"),
                "route": f"{origin} to {destination}",
            },
            edited_by=editor_id,
            editor_email=actor.get("email") or session.get("email"),
            user_id=editor_id if _is_dispatcher() else None,
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except FleetManagementError as exc:
        message = str(exc)
        if "not found" in message.lower():
            return _json_error(message, 403 if _is_dispatcher() else 404)
        if "do not have access" in message.lower():
            return _json_error(message, 403)
        raise
    return jsonify({"data": record})


@app.route("/api/fuel/<int:fuel_id>/invoice", methods=["GET", "POST"])
def fuel_invoice_image(fuel_id: int) -> Any:
    return _handle_document_image("fuel", fuel_id)


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
    if any(key in payload for key in ("created_by", "dispatcher_id", "user_id")):
        raise ValueError("Ownership is assigned automatically by the authenticated user.")
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
        created_by = str(g.current_user["id"]) if _is_dispatcher() else None
        return fleet.add_maintenance(
            vehicle_id=_integer(payload, "vehicle_id"),
            service_type=_required_text(payload, "service_type"),
            description=_optional_text(payload, "description"),
            cost=_number(payload, "cost", 0),
            performed_on=_optional_text(payload, "performed_on"),
            created_by=created_by,
        )
    if resource == "fuel":
        created_by = str(g.current_user["id"]) if _is_dispatcher() else None
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
            created_by=created_by,
        )
    if resource == "trips":
        origin = _required_text(payload, "origin")
        destination = _required_text(payload, "destination")
        shipment_date = _optional_text(payload, "shipment_date")
        created_by = str(g.current_user["id"]) if _is_dispatcher() else None
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
            notes=_optional_text(payload, "notes"),
            created_by=created_by,
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
    try:
        manager = get_manager()
        if _is_dispatcher():
            return _json_error("Dispatchers cannot delete this record type.", 403)
        getattr(manager, method_name)(record_id)
        return jsonify({"message": "Record deleted"})
    except FleetManagementError as exc:
        return _json_error(str(exc), 403 if _is_dispatcher() else 400)


@app.route("/api/export")
def export_report() -> Any:
    fleet = get_manager()
    user_id = str((g.current_user or {}).get("id") or session.get("user_id") or "")
    if _is_dispatcher() and user_id:
        report = {
            "vehicles": fleet.list_vehicles(),
            "drivers": fleet.list_drivers(),
            "assignments": fleet.list_assignments(),
            "trips": fleet.list_trips(user_id=user_id),
            "maintenance": fleet.list_maintenance(user_id=user_id),
            "fuel_logs": fleet.list_fuel_logs(user_id=user_id),
            "dashboard": fleet.dashboard(user_id=user_id),
        }
    else:
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


@app.route("/api/export/trips")
def export_trip_history() -> Any:
    group_by = request.args.get("group_by", "")
    valid_group_fields = {"", "driver_name", "plate_number", "origin", "destination"}
    if group_by not in valid_group_fields:
        return _json_error("Choose a valid trip grouping.", 400)

    user_id = str((g.current_user or {}).get("id") or session.get("user_id") or "")
    trips = get_manager().list_trips(user_id=user_id if _is_dispatcher() and user_id else None)
    search_term = request.args.get("search", "").strip().casefold()
    if search_term:
        searchable_fields = (
            "ism_no", "shipment_date", "time_in", "time_out", "origin",
            "destination", "plate_number", "load_details", "driver_name", "trip_fuel",
        )
        trips = [
            trip for trip in trips
            if any(
                search_term in str(trip.get(field) or "").casefold()
                for field in searchable_fields
            )
        ]

    return send_file(
        build_trip_excel_report(trips, group_by or None),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="trip_history.xlsx",
    )


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
