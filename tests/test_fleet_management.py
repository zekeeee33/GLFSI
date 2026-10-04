import json
import os
import tempfile
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import app as web_app
from fleet_management import FleetManagementError, FleetManager, _supabase_project_url
from openpyxl import load_workbook


class FakeAuthApiError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status
        self.code = "invalid_credentials"


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.action = "select"
        self.columns = "*"
        self.values = None
        self.filters = []
        self.sort = None
        self.row_limit = None
        self.row_range = None

    def select(self, columns="*", **kwargs):
        self.columns = columns
        return self

    def insert(self, values):
        self.action = "insert"
        self.values = values
        return self

    def update(self, values):
        self.action = "update"
        self.values = values
        return self

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False):
        self.sort = (column, desc)
        return self

    def limit(self, count):
        self.row_limit = count
        return self

    def range(self, start, end):
        self.row_range = (start, end)
        return self

    def _matches(self, row):
        return all(row.get(key) == value for key, value in self.filters)

    def execute(self):
        rows = self.client.tables.setdefault(self.table_name, [])
        if self.action == "insert":
            row = dict(self.values)
            row["id"] = self.client.next_ids.get(self.table_name, 0) + 1
            self.client.next_ids[self.table_name] = row["id"]
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        if self.action == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(self.values)
                    updated.append(row)
            return SimpleNamespace(data=[dict(row) for row in updated])
        if self.action == "delete":
            self.client.tables[self.table_name] = [
                row for row in rows if not self._matches(row)
            ]
            return SimpleNamespace(data=[])

        result = [dict(row) for row in rows if self._matches(row)]
        if self.sort:
            column, desc = self.sort
            result.sort(key=lambda row: row.get(column) or "", reverse=desc)
        if self.row_limit is not None:
            result = result[: self.row_limit]
        if self.row_range is not None:
            start, end = self.row_range
            result = result[start : end + 1]
        if (
            self.columns not in ("*",)
            and "driver:" not in self.columns
            and "vehicle:" not in self.columns
        ):
            selected = [column.strip() for column in self.columns.split(",")]
            result = [{key: row.get(key) for key in selected} for row in result]
        for row in result:
            if "driver:drivers(" in self.columns:
                driver = next(
                    (
                        item
                        for item in self.client.tables.get("drivers", [])
                        if item["id"] == row["driver_id"]
                    ),
                    None,
                )
                row["driver"] = {"name": driver["name"]} if driver else None
            if "vehicle:vehicles(" in self.columns:
                vehicle = next(
                    (
                        item
                        for item in self.client.tables.get("vehicles", [])
                        if item["id"] == row["vehicle_id"]
                    ),
                    None,
                )
                if vehicle:
                    row["vehicle"] = {
                        key: vehicle.get(key)
                        for key in ("plate_number", "make", "model")
                    }
                else:
                    row["vehicle"] = None
        return SimpleNamespace(data=result)


class FakeSupabaseClient:
    def __init__(self):
        self.tables = {}
        self.next_ids = {}

    def table(self, table_name):
        return FakeQuery(self, table_name)


class FakeAuthClient:
    def __init__(self):
        self.auth = self
        self.user = SimpleNamespace(id="auth-user-1", email="fleet@example.com")
        self.auth_session = SimpleNamespace(
            access_token="valid-access-token",
            refresh_token="valid-refresh-token",
            expires_in=3600,
        )

    def sign_in_with_password(self, credentials):
        if credentials != {"email": "fleet@example.com", "password": "correct-password"}:
            raise FakeAuthApiError("Invalid credentials", 400)
        return SimpleNamespace(session=self.auth_session, user=self.user)

    def get_user(self, access_token):
        if access_token != self.auth_session.access_token:
            raise ValueError("Expired access token")
        return SimpleNamespace(user=self.user)

    def refresh_session(self, refresh_token):
        if refresh_token != self.auth_session.refresh_token:
            raise ValueError("Invalid refresh token")
        return SimpleNamespace(session=self.auth_session, user=self.user)

class FleetManagerTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeSupabaseClient()
        self.manager = FleetManager(client=self.client)

    def test_add_vehicle_driver_and_assignment(self):
        vehicle = self.manager.add_vehicle("ABC-123", "Toyota", "Hiace", 2022, "White")
        driver = self.manager.add_driver("Jane Doe", "DL-1001", phone="555-0100")
        assignment = self.manager.assign_vehicle(
            driver["id"], vehicle["id"], "2026-10-03"
        )
        listed = self.manager.list_assignments()

        self.assertEqual(vehicle["plate_number"], "ABC-123")
        self.assertEqual(driver["name"], "Jane Doe")
        self.assertEqual(assignment["driver_id"], driver["id"])
        self.assertEqual(listed[0]["driver_name"], "Jane Doe")
        self.assertEqual(listed[0]["plate_number"], "ABC-123")
        self.assertEqual(self.manager.get_vehicle(vehicle["id"])["status"], "assigned")

    def test_trip_and_maintenance_and_fuel_tracking(self):
        vehicle = self.manager.add_vehicle("XYZ-988", "Mercedes", "Sprinter", 2021, "Blue")
        driver = self.manager.add_driver("John Smith", "DL-9988")

        trip = self.manager.add_trip(
            vehicle["id"], driver["id"], "Accra to Kumasi", 15000, 15375,
            "2026-10-02", "Routine delivery route",
        )
        maintenance = self.manager.add_maintenance(
            vehicle["id"], "service", "Oil change", 120.0
        )
        fuel = self.manager.add_fuel(vehicle["id"], "diesel", 80, 15.5)

        self.assertEqual(trip["route"], "Accra to Kumasi")
        self.assertEqual(maintenance["service_type"], "service")
        self.assertEqual(fuel["total_cost"], 1240.0)
        self.assertEqual(self.manager.dashboard()["recent_trips"], 1)
        self.assertEqual(self.manager.dashboard()["total_fuel_spend"], 1240.0)
        self.assertEqual(self.manager.get_vehicle(vehicle["id"])["odometer"], 15375)

    def test_imported_trip_without_vehicle_or_driver_ids_displays_source_fields(self):
        self.client.tables["trips"] = [{
            "id": 1,
            "vehicle_id": None,
            "driver_id": None,
            "record_date": "2026-09-28",
            "ism_no": "31946326",
            "shipment_date": "2026-09-27",
            "time_in": "10:27:00",
            "time_out": None,
            "origin": "GENSAN",
            "destination": "DAV2",
            "plate_no": "MUB289",
            "load_details": "1P",
            "driver_name": "SALCEDA",
            "trip_fuel": "1ST-105 INV12125 9.27",
            "route": "GENSAN to DAV2",
            "trip_date": "2026-09-27",
        }]

        trip = self.manager.list_trips()[0]
        self.assertEqual(trip["plate_number"], "MUB289")
        self.assertEqual(trip["driver_name"], "SALCEDA")

    def test_export_report(self):
        self.manager.add_vehicle("ZZZ-001", "Ford", "Transit", 2023)
        self.manager.add_driver("Esther Kofi", "DL-4411")
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "report.xlsx")
            result = self.manager.export_report(output_path)
            self.assertTrue(os.path.exists(result["output_path"]))
            self.assertGreater(result["records_written"], 0)
            workbook = load_workbook(output_path, data_only=True)
            self.assertEqual(workbook["Vehicles"]["B5"].value, "ZZZ-001")

    def test_web_export_returns_preformatted_system_wide_excel_workbook(self):
        vehicle = self.manager.add_vehicle("XLS-001", "Toyota", "Hiace", 2024)
        driver = self.manager.add_driver("Excel Driver", "XLS-DL-1")
        self.manager.assign_vehicle(driver["id"], vehicle["id"])
        self.manager.add_maintenance(
            vehicle["id"], "Service", '=HYPERLINK("https://example.com","Open")', 1250.5
        )
        self.manager.add_fuel(vehicle["id"], "Diesel", 50, 60.25)
        self.manager.add_trip(
            vehicle["id"], driver["id"], "Manila to Cavite", 100, 150,
            origin="Manila", destination="Cavite",
        )
        web_app.manager = self.manager
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()
        self.sign_in(client)

        response = client.get("/api/export")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.mimetype,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("fleet_system_report.xlsx", response.headers["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.data), data_only=True)
        self.assertEqual(
            workbook.sheetnames,
            ["Dashboard", "Vehicles", "Drivers", "Assignments", "Maintenance", "Fuel Logs", "Trips"],
        )
        vehicles = workbook["Vehicles"]
        self.assertEqual(vehicles["B4"].value, "Plate Number")
        self.assertEqual(vehicles["B5"].value, "XLS-001")
        self.assertEqual(vehicles.freeze_panes, "A5")
        self.assertEqual(vehicles.auto_filter.ref, "A4:K5")
        self.assertEqual(workbook["Fuel Logs"]["G5"].value, 3012.5)
        self.assertIn("₱", workbook["Fuel Logs"]["G5"].number_format)
        self.assertEqual(workbook["Maintenance"]["E5"].data_type, "s")
        self.assertEqual(workbook["Trips"]["G5"].value, "Manila")

    def test_cli_export_report_defaults_to_excel_file(self):
        from fleet_management import _build_cli

        args = _build_cli().parse_args(["export-report"])
        self.assertEqual(args.output, "fleet_system_report.xlsx")

    def test_missing_supabase_configuration_is_reported(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(FleetManagementError, "SUPABASE_URL"):
                FleetManager()

    def test_supabase_rest_endpoint_is_normalized_to_project_url(self):
        self.assertEqual(
            _supabase_project_url("https://project-ref.supabase.co/rest/v1/"),
            "https://project-ref.supabase.co",
        )

    def test_supabase_client_receives_normalized_url(self):
        with patch("fleet_management.create_client") as create_client:
            FleetManager(
                url="https://project-ref.supabase.co/rest/v1/",
                key="test-key",
            )
        create_client.assert_called_once_with(
            "https://project-ref.supabase.co", "test-key"
        )

    def test_dns_error_nested_in_transport_exception_gets_actionable_message(self):
        class BrokenQuery:
            def execute(self):
                try:
                    raise OSError(11001, "getaddrinfo failed")
                except OSError as cause:
                    raise RuntimeError("request transport failed") from cause

        with patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://project-ref.supabase.co"},
        ):
            with self.assertRaisesRegex(
                FleetManagementError, "Could not resolve the Supabase server"
            ):
                self.manager._execute(BrokenQuery())

    def test_missing_trip_migration_has_actionable_error(self):
        class UnmigratedTripsQuery:
            def execute(self):
                raise RuntimeError(
                    "{'message': 'column trips.shipment_date does not exist', "
                    "'code': '42703'}"
                )

        with self.assertRaisesRegex(
            FleetManagementError, "supabase_trips_migration.sql"
        ):
            self.manager._execute(UnmigratedTripsQuery())

    def test_web_dashboard_and_vehicle_form_use_supabase_manager(self):
        web_app.manager = self.manager
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()

        self.sign_in(client)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<!doctype html>", response.data.lower())
        self.assertIn(b"/static/app.js", response.data)
        response.close()

        response = client.post(
            "/api/vehicles",
            json={
                "plate_number": "WEB-123",
                "make": "Toyota",
                "model": "Hiace",
                "year": 2022,
            },
            headers={"X-CSRF-Token": self.csrf_token(client)},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["data"]["plate_number"], "WEB-123")

        driver = self.manager.add_driver("Web Driver", "WEB-DL-1")
        vehicle = self.manager.list_vehicles()[0]
        response = client.post(
            "/api/trips",
            json={
                "ism_no": "ISM-008",
                "shipment_date": "2026-10-03",
                "time_in": "08:15",
                "time_out": "09:40",
                "origin": "Manila",
                "destination": "Cavite",
                "vehicle_id": vehicle["id"],
                "driver_id": driver["id"],
                "load_details": "12 cartons",
                "trip_fuel": "Diesel",
            },
            headers={"X-CSRF-Token": self.csrf_token(client)},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["data"]["ism_no"], "ISM-008")
        self.assertEqual(response.json["data"]["origin"], "Manila")
        self.assertEqual(response.json["data"]["time_in"], "08:15")
        self.assertEqual(response.json["data"]["trip_fuel"], "Diesel")

        response = client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["vehicles"][0]["plate_number"], "WEB-123")
        trip = response.json["trips"][0]
        self.assertEqual(trip["shipment_date"], "2026-10-03")
        self.assertEqual(trip["plate_number"], "WEB-123")
        self.assertEqual(trip["driver_name"], "Web Driver")

    def test_web_reports_missing_supabase_configuration(self):
        web_app.manager = None
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()
        self.sign_in(client)
        with patch.dict(os.environ, {}, clear=True):
            response = client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"SUPABASE_URL", response.data)

    def csrf_token(self, client):
        response = client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        return response.json["csrf_token"]

    def sign_in(self, client, auth_client=None):
        patcher = patch.object(
            web_app,
            "get_auth_client",
            return_value=auth_client or FakeAuthClient(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        csrf = client.get("/api/auth/csrf").json["csrf_token"]
        response = client.post(
            "/api/auth/login",
            json={"email": "fleet@example.com", "password": "correct-password"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers.get("Set-Cookie", ""))
        return response

    def test_app_and_api_require_authentication_but_login_assets_are_public(self):
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()

        self.assertEqual(client.get("/").status_code, 302)
        self.assertEqual(client.get("/api/bootstrap").status_code, 401)
        self.assertEqual(client.get("/static/index.html").status_code, 302)
        login_page = client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        login_page.close()
        login_script = client.get("/static/login.js")
        self.assertEqual(login_script.status_code, 200)
        login_script.close()

    def test_login_rejects_bad_credentials_and_requires_csrf(self):
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()
        with patch.object(web_app, "get_auth_client", return_value=FakeAuthClient()):
            csrf = client.get("/api/auth/csrf").json["csrf_token"]
            no_csrf = client.post(
                "/api/auth/login",
                json={"email": "fleet@example.com", "password": "correct-password"},
            )
            bad_password = client.post(
                "/api/auth/login",
                json={"email": "fleet@example.com", "password": "wrong-password"},
                headers={"X-CSRF-Token": csrf},
            )
        self.assertEqual(no_csrf.status_code, 403)
        self.assertEqual(bad_password.status_code, 401)
        self.assertIn(b"Sign-in failed", bad_password.data)

    def test_login_reports_missing_supabase_anon_key(self):
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()
        with patch.object(web_app, "_supabase_setting", return_value=None):
            csrf = client.get("/api/auth/csrf").json["csrf_token"]
            response = client.post(
                "/api/auth/login",
                json={"email": "fleet@example.com", "password": "correct-password"},
                headers={"X-CSRF-Token": csrf},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"SUPABASE_ANON_KEY", response.data)

    def test_mutations_require_csrf_and_logout_clears_authenticated_session(self):
        web_app.manager = self.manager
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()
        auth_client = FakeAuthClient()
        self.sign_in(client, auth_client)
        csrf = self.csrf_token(client)
        payload = {
            "plate_number": "CSRF-1",
            "make": "Toyota",
            "model": "Hiace",
            "year": 2022,
        }
        blocked = client.post("/api/vehicles", json=payload)
        created = client.post(
            "/api/vehicles",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )
        logout = client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": csrf},
        )
        protected = client.get("/api/bootstrap")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(protected.status_code, 401)

    def test_logout_clears_local_session_without_csrf_token(self):
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()
        self.sign_in(client)

        response = client.post(
            "/api/auth/logout",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("/login", response.json["redirect"])
        self.assertTrue(any(
            "glfs_access_token=;" in cookie
            for cookie in response.headers.getlist("Set-Cookie")
        ))
        self.assertEqual(client.get("/api/bootstrap").status_code, 401)

    def test_expired_access_token_is_refreshed(self):
        web_app.app.config["TESTING"] = True
        client = web_app.app.test_client()
        auth_client = FakeAuthClient()
        self.sign_in(client, auth_client)
        auth_client.auth_session.access_token = "refreshed-access-token"
        # The old browser token expires; the refresh token supplies a new one.
        response = client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertIn("refreshed-access-token", response.headers.get("Set-Cookie", ""))


if __name__ == "__main__":
    unittest.main()
