#!/usr/bin/env python3
"""Good Luck Forwarding Systems Inc. Fleet Management System backed by Supabase."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _supabase_project_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FleetManagementError(
            "SUPABASE_URL must be the project URL, such as "
            "https://your-project-ref.supabase.co."
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/rest/v1"):
        path = path[:-len("/rest/v1")]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class FleetManagementError(RuntimeError):
    """Raised when a fleet action or Supabase request fails."""


class FleetManager:
    """Fleet data access through the Supabase PostgREST API."""

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        client: Optional[Client] = None,
    ):
        self.client = client
        if self.client is None:
            project_url = url or os.environ.get("SUPABASE_URL")
            api_key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            if not project_url or not api_key:
                raise FleetManagementError(
                    "Supabase is not configured. Set SUPABASE_URL and "
                    "SUPABASE_SERVICE_ROLE_KEY in your environment or .env file."
                )
            try:
                self.client = create_client(_supabase_project_url(project_url), api_key)
            except Exception as exc:
                raise FleetManagementError(f"Could not initialize Supabase: {exc}") from exc

    def _execute(self, query: Any) -> Any:
        try:
            return query.execute()
        except Exception as exc:
            error_details = []
            pending = [exc]
            seen = set()
            while pending:
                current = pending.pop()
                if id(current) in seen:
                    continue
                seen.add(id(current))
                error_details.append(str(current).lower())
                error_details.extend(str(arg).lower() for arg in current.args)
                for related in (current.__cause__, current.__context__):
                    if related is not None:
                        pending.append(related)
            combined_error = " ".join(error_details)
            if "getaddrinfo failed" in combined_error or "11001" in combined_error:
                project_url = os.environ.get("SUPABASE_URL", "")
                hostname = urlsplit(project_url).hostname
                host_detail = f" ({hostname})" if hostname else ""
                raise FleetManagementError(
                    "Could not resolve the Supabase server"
                    f"{host_detail}. Verify SUPABASE_URL in .env matches the "
                    "Project URL in Supabase Settings > API, check your internet "
                    "or VPN/DNS settings, and restart the app."
                ) from exc
            if "column trips.shipment_date does not exist" in combined_error:
                raise FleetManagementError(
                    "The Supabase trips table needs its shipment fields. Run "
                    "supabase_trips_migration.sql in the Supabase SQL Editor, "
                    "then refresh the app."
                ) from exc
            if "function hashtextext(text) does not exist" in combined_error:
                raise FleetManagementError(
                    "The Supabase payroll finalization function is outdated. Run "
                    "the updated supabase_payroll_migration.sql in the Supabase "
                    "SQL Editor, then retry payroll finalization."
                ) from exc
            missing_edit_history = (
                "column trips.last_edited_by does not exist" in combined_error
                or "column trips.last_edited_by_email does not exist" in combined_error
                or (
                    "trip_edit_history" in combined_error
                    and (
                        "does not exist" in combined_error
                        or "schema cache" in combined_error
                    )
                )
            )
            if missing_edit_history:
                raise FleetManagementError(
                    "Trip edit history is not installed. Run "
                    "supabase_dispatcher_ownership_migration.sql in the Supabase "
                    "SQL Editor, then refresh the app."
                ) from exc
            if "payroll_periods" in combined_error and (
                "does not exist" in combined_error or "schema cache" in combined_error
            ):
                raise FleetManagementError(
                    "Payroll tables are not installed. Run "
                    "supabase_payroll_migration.sql in the Supabase SQL Editor, "
                    "then refresh the app."
                ) from exc
            if "notifications" in combined_error and (
                "does not exist" in combined_error or "schema cache" in combined_error
            ):
                raise FleetManagementError(
                    "Admin notifications are not installed. Run "
                    "supabase_notifications_migration.sql in the Supabase SQL "
                    "Editor, then refresh the app."
                ) from exc
            raise FleetManagementError(f"Supabase request failed: {exc}") from exc

    def _insert(self, table: str, values: Dict[str, Any]) -> Dict[str, Any]:
        response = self._execute(
            self.client.table(table).insert(values).select("*")
        )
        rows = response.data or []
        if not rows:
            raise FleetManagementError(f"Supabase did not return the inserted {table} record")
        return dict(rows[0])

    def _select_all(
        self,
        table: str,
        select: str,
        order: Optional[tuple[str, str]] = None,
        filters: Optional[List[tuple[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        page_size = 1000
        offset = 0
        result: List[Dict[str, Any]] = []
        while True:
            query = self.client.table(table).select(select)
            for column, value in filters or []:
                query = query.eq(column, value)
            if order:
                column, direction = order
                query = query.order(column, desc=direction == "desc")
            response = self._execute(query.range(offset, offset + page_size - 1))
            page = response.data or []
            result.extend(dict(row) for row in page)
            if len(page) < page_size:
                return result
            offset += page_size

    def _list(
        self,
        table: str,
        select: str = "*",
        order: Optional[tuple[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        return self._select_all(table, select, order)

    def _get(self, table: str, record_id: int) -> Dict[str, Any]:
        response = self._execute(
            self.client.table(table).select("*").eq("id", record_id).limit(1)
        )
        rows = response.data or []
        if not rows:
            raise FleetManagementError(f"{table.rstrip('s').capitalize()} {record_id} not found")
        return dict(rows[0])

    def _delete(self, table: str, record_id: int) -> None:
        self._execute(self.client.table(table).delete().eq("id", record_id))

    def _related_list(
        self,
        table: str,
        select: str,
        order: tuple[str, str],
        owner_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = []
        filters = [("created_by", owner_id)] if owner_id is not None else None
        for row in self._select_all(table, select, order, filters):
            driver = row.pop("driver", None)
            vehicle = row.pop("vehicle", None)
            if isinstance(driver, dict):
                row["driver_name"] = driver.get("name")
            if isinstance(vehicle, dict):
                row.update(
                    {
                        key: value
                        for key, value in vehicle.items()
                        if key in ("plate_number", "make", "model")
                    }
                )
            elif table == "trips" and row.get("plate_no"):
                row["plate_number"] = row["plate_no"]
            rows.append(row)
        return rows

    def _exists(self, table: str, record_id: int) -> bool:
        response = self._execute(
            self.client.table(table).select("id").eq("id", record_id).limit(1)
        )
        return bool(response.data)

    @staticmethod
    def _normalize_owner(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _matches_owner(cls, row: Dict[str, Any], user_id: Optional[str]) -> bool:
        if user_id is None:
            return True
        owner_value = cls._normalize_owner(
            row.get("created_by")
            or row.get("dispatcher_id")
            or row.get("user_id")
        )
        return owner_value == cls._normalize_owner(user_id)

    @classmethod
    def _filter_owned_rows(cls, rows: List[Dict[str, Any]], user_id: Optional[str]) -> List[Dict[str, Any]]:
        if user_id is None:
            return rows
        return [row for row in rows if cls._matches_owner(row, user_id)]

    def add_vehicle(
        self,
        plate_number: str,
        make: str,
        model: str,
        year: int,
        color: Optional[str] = None,
        status: str = "available",
        odometer: int = 0,
        registration_expiry: Optional[str] = None,
        insurance_expiry: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not plate_number or not make or not model:
            raise FleetManagementError("plate_number, make, and model are required")
        if year < 1900 or year > datetime.now().year + 2:
            raise FleetManagementError("vehicle year is out of range")
        if odometer < 0:
            raise FleetManagementError("odometer cannot be negative")
        return self._insert(
            "vehicles",
            {
                "plate_number": plate_number.strip(),
                "make": make.strip(),
                "model": model.strip(),
                "year": year,
                "color": color.strip() if color else None,
                "status": status.strip(),
                "odometer": odometer,
                "registration_expiry": registration_expiry,
                "insurance_expiry": insurance_expiry,
            },
        )

    def get_vehicle(self, vehicle_id: int) -> Dict[str, Any]:
        return self._get("vehicles", vehicle_id)

    def add_driver(
        self,
        name: str,
        license_number: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        if not name or not license_number:
            raise FleetManagementError("name and license_number are required")
        return self._insert(
            "drivers",
            {
                "name": name.strip(),
                "license_number": license_number.strip(),
                "phone": phone,
                "email": email,
                "status": status.strip(),
            },
        )

    def get_driver(self, driver_id: int) -> Dict[str, Any]:
        return self._get("drivers", driver_id)

    def list_vehicles(self) -> List[Dict[str, Any]]:
        return self._list("vehicles", order=("plate_number", "asc"))

    def list_drivers(self) -> List[Dict[str, Any]]:
        return self._list("drivers", order=("name", "asc"))

    def delete_vehicle(self, vehicle_id: int) -> None:
        self._delete("vehicles", vehicle_id)

    def delete_driver(self, driver_id: int) -> None:
        self._delete("drivers", driver_id)

    def assign_vehicle(
        self,
        driver_id: int,
        vehicle_id: int,
        assigned_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._exists("drivers", driver_id):
            raise FleetManagementError(f"Driver {driver_id} not found")
        if not self._exists("vehicles", vehicle_id):
            raise FleetManagementError(f"Vehicle {vehicle_id} not found")
        self._execute(
            self.client.table("vehicles").update({"status": "assigned"}).eq("id", vehicle_id)
        )
        return self._insert(
            "assignments",
            {
                "driver_id": driver_id,
                "vehicle_id": vehicle_id,
                "assigned_date": assigned_date or datetime.now().date().isoformat(),
                "notes": notes,
            },
        )

    def get_assignment(self, assignment_id: int) -> Dict[str, Any]:
        response = self._execute(
            self.client.table("assignments")
            .select("*,driver:drivers(name),vehicle:vehicles(plate_number,make,model)")
            .eq("id", assignment_id)
            .limit(1)
        )
        if not response.data:
            raise FleetManagementError(f"Assignment {assignment_id} not found")
        return self._flatten_assignment(dict(response.data[0]))

    @staticmethod
    def _flatten_assignment(row: Dict[str, Any]) -> Dict[str, Any]:
        driver = row.pop("driver", None)
        vehicle = row.pop("vehicle", None)
        if isinstance(driver, dict):
            row["driver_name"] = driver.get("name")
        if isinstance(vehicle, dict):
            row.update({key: vehicle.get(key) for key in ("plate_number", "make", "model")})
        elif row.get("plate_no"):
            row["plate_number"] = row["plate_no"]
        return row

    def list_assignments(self) -> List[Dict[str, Any]]:
        rows = self._related_list(
            "assignments",
            "*,driver:drivers(name),vehicle:vehicles(plate_number,make,model)",
            ("assigned_date", "desc"),
        )
        return [self._flatten_assignment(row) for row in rows]

    def delete_assignment(self, assignment_id: int) -> None:
        self._delete("assignments", assignment_id)

    def add_maintenance(
        self,
        vehicle_id: int,
        service_type: str,
        description: Optional[str],
        cost: float,
        performed_on: Optional[str] = None,
        created_by: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not self._exists("vehicles", vehicle_id):
            raise FleetManagementError(f"Vehicle {vehicle_id} not found")
        if not service_type:
            raise FleetManagementError("service_type is required")
        owner = self._normalize_owner(created_by)
        payload = {
            "vehicle_id": vehicle_id,
            "service_type": service_type.strip(),
            "description": description,
            "cost": float(cost),
            "performed_on": performed_on or datetime.now().date().isoformat(),
        }
        if owner is not None:
            payload["created_by"] = owner
        return self._insert("maintenance", payload)

    def get_maintenance(self, maintenance_id: int, user_id: Optional[str] = None) -> Dict[str, Any]:
        row = self._get("maintenance", maintenance_id)
        if user_id is not None and not self._matches_owner(row, user_id):
            raise FleetManagementError(f"You do not have access to maintenance record {maintenance_id}")
        return row

    def list_maintenance(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self._related_list(
            "maintenance",
            "*,vehicle:vehicles(plate_number)",
            ("performed_on", "desc"),
            owner_id=user_id,
        )
        return rows if user_id is None else self._filter_owned_rows(rows, user_id)

    def add_fuel(
        self,
        vehicle_id: int,
        fuel_type: str,
        quantity: float,
        price_per_liter: float,
        total_cost: Optional[float] = None,
        logged_on: Optional[str] = None,
        created_by: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not self._exists("vehicles", vehicle_id):
            raise FleetManagementError(f"Vehicle {vehicle_id} not found")
        if not fuel_type or quantity <= 0 or price_per_liter <= 0:
            raise FleetManagementError("fuel_type is required; quantity and price_per_liter must be positive")
        owner = self._normalize_owner(created_by)
        payload = {
            "vehicle_id": vehicle_id,
            "fuel_type": fuel_type.strip(),
            "quantity": float(quantity),
            "price_per_liter": float(price_per_liter),
            "total_cost": float(total_cost) if total_cost is not None else quantity * price_per_liter,
            "logged_on": logged_on or datetime.now().date().isoformat(),
        }
        if owner is not None:
            payload["created_by"] = owner
        return self._insert("fuel_logs", payload)

    def get_fuel(self, fuel_id: int, user_id: Optional[str] = None) -> Dict[str, Any]:
        row = self._get("fuel_logs", fuel_id)
        if user_id is not None and not self._matches_owner(row, user_id):
            raise FleetManagementError(f"You do not have access to fuel log {fuel_id}")
        return row

    def set_fuel_invoice_path(
        self, fuel_id: int, object_path: str, user_id: Optional[str] = None
    ) -> None:
        self.get_fuel(fuel_id, user_id)
        query = (
            self.client.table("fuel_logs")
            .update({"invoice_object_path": object_path})
            .eq("id", fuel_id)
        )
        if user_id is not None:
            query = query.eq("created_by", user_id)
        response = self._execute(query.select("id"))
        if not response.data:
            raise FleetManagementError(f"Fuel log {fuel_id} was not found or is not accessible")

    def list_fuel_logs(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self._related_list(
            "fuel_logs",
            "*,vehicle:vehicles(plate_number)",
            ("logged_on", "desc"),
            owner_id=user_id,
        )
        return rows if user_id is None else self._filter_owned_rows(rows, user_id)

    def add_trip(
        self,
        vehicle_id: int,
        driver_id: int,
        route: str,
        start_odometer: int,
        end_odometer: int,
        trip_date: Optional[str] = None,
        notes: Optional[str] = None,
        ism_no: Optional[str] = None,
        shipment_date: Optional[str] = None,
        time_in: Optional[str] = None,
        time_out: Optional[str] = None,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        load_details: Optional[str] = None,
        trip_fuel: Optional[str] = None,
        created_by: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not self._exists("vehicles", vehicle_id):
            raise FleetManagementError(f"Vehicle {vehicle_id} not found")
        if not self._exists("drivers", driver_id):
            raise FleetManagementError(f"Driver {driver_id} not found")
        if not route:
            raise FleetManagementError("route is required")
        if start_odometer < 0 or end_odometer < start_odometer:
            raise FleetManagementError("odometer readings must be non-negative and end cannot be lower than start")
        owner = self._normalize_owner(created_by)
        trip = self._insert(
            "trips",
            {
                "vehicle_id": vehicle_id,
                "driver_id": driver_id,
                "route": route.strip(),
                "start_odometer": int(start_odometer),
                "end_odometer": int(end_odometer),
                "trip_date": trip_date or datetime.now().date().isoformat(),
                "notes": notes,
                "ism_no": ism_no.strip() if ism_no else None,
                "shipment_date": shipment_date or trip_date or datetime.now().date().isoformat(),
                "time_in": time_in or None,
                "time_out": time_out or None,
                "origin": origin.strip() if origin else None,
                "destination": destination.strip() if destination else None,
                "load_details": load_details.strip() if load_details else None,
                "trip_fuel": trip_fuel.strip() if trip_fuel else None,
                **({"created_by": owner} if owner is not None else {}),
            },
        )
        if end_odometer > 0:
            self._execute(
                self.client.table("vehicles")
                .update({"odometer": end_odometer})
                .eq("id", vehicle_id)
            )
        return trip

    def get_trip(self, trip_id: int, user_id: Optional[str] = None) -> Dict[str, Any]:
        response = self._execute(
            self.client.table("trips")
            .select("*,driver:drivers(name),vehicle:vehicles(plate_number,make,model)")
            .eq("id", trip_id)
            .limit(1)
        )
        if not response.data:
            raise FleetManagementError(f"Trip {trip_id} not found")
        row = dict(response.data[0])
        if user_id is not None and not self._matches_owner(row, user_id):
            raise FleetManagementError(f"You do not have access to trip {trip_id}")
        driver = row.pop("driver", None)
        vehicle = row.pop("vehicle", None)
        if isinstance(driver, dict):
            row["driver_name"] = driver.get("name")
        if isinstance(vehicle, dict):
            row.update({key: vehicle.get(key) for key in ("plate_number", "make", "model")})
        return row

    def update_trip(
        self,
        trip_id: int,
        values: Dict[str, Any],
        edited_by: str,
        editor_email: Optional[str],
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        editable_fields = {
            "ism_no",
            "shipment_date",
            "time_in",
            "time_out",
            "origin",
            "destination",
            "vehicle_id",
            "driver_id",
            "load_details",
            "trip_fuel",
            "notes",
            "route",
        }
        required_fields = {
            "shipment_date",
            "origin",
            "destination",
            "vehicle_id",
            "driver_id",
            "route",
        }
        if (
            not required_fields.issubset(values)
            or set(values) - editable_fields
        ):
            raise FleetManagementError("The trip contains unsupported fields.")
        self.get_trip(trip_id, user_id)
        if values["vehicle_id"] is not None and not self._exists("vehicles", values["vehicle_id"]):
            raise FleetManagementError(f"Vehicle {values['vehicle_id']} not found")
        if values["driver_id"] is not None and not self._exists("drivers", values["driver_id"]):
            raise FleetManagementError(f"Driver {values['driver_id']} not found")

        update_values = {
            **values,
            "trip_date": values["shipment_date"],
            "last_edited_by": edited_by,
            "last_edited_by_email": editor_email,
        }
        query = (
            self.client.table("trips")
            .update(update_values)
            .eq("id", trip_id)
        )
        if user_id is not None:
            query = query.eq("created_by", user_id)
        response = self._execute(query.select("*"))
        if not response.data:
            raise FleetManagementError(f"Trip {trip_id} was not found or is not accessible")
        return dict(response.data[0])

    def list_trip_edit_history(
        self, trip_id: int, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        self.get_trip(trip_id, user_id)
        response = self._execute(
            self.client.table("trip_edit_history")
            .select("id,trip_id,edited_by,edited_by_email,edited_at,old_values,new_values")
            .eq("trip_id", trip_id)
            .order("edited_at", desc=True)
        )
        return [dict(row) for row in (response.data or [])]

    def set_trip_manifest_path(
        self,
        trip_id: int,
        object_path: str,
        user_id: Optional[str] = None,
        edited_by: Optional[str] = None,
        editor_email: Optional[str] = None,
    ) -> None:
        self.get_trip(trip_id, user_id)
        update_values = {"manifest_object_path": object_path}
        if edited_by is not None:
            update_values["last_edited_by"] = edited_by
            update_values["last_edited_by_email"] = editor_email
        query = (
            self.client.table("trips")
            .update(update_values)
            .eq("id", trip_id)
        )
        if user_id is not None:
            query = query.eq("created_by", user_id)
        response = self._execute(query.select("id"))
        if not response.data:
            raise FleetManagementError(f"Trip {trip_id} was not found or is not accessible")

    def list_trips(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self._related_list(
            "trips",
            "*,driver:drivers(name),vehicle:vehicles(plate_number,make,model)",
            ("shipment_date", "desc"),
            owner_id=user_id,
        )
        return rows if user_id is None else self._filter_owned_rows(rows, user_id)

    def payroll_report(self, start_date: str, end_date: str) -> Dict[str, Any]:
        from payroll import PayrollService

        return PayrollService(self).report(start_date, end_date)

    def review_payroll(
        self, start_date: str, end_date: str, actor_id: str
    ) -> Dict[str, Any]:
        from payroll import PayrollService

        return PayrollService(self).review(start_date, end_date, actor_id)

    def add_cash_advance(
        self,
        start_date: str,
        end_date: str,
        driver_id: int,
        advance_date: str,
        amount: Any,
        remarks: Optional[str],
        reference: Optional[str],
        actor_id: str,
    ) -> Dict[str, Any]:
        from payroll import PayrollService

        return PayrollService(self).add_cash_advance(
            start_date, end_date, driver_id, advance_date, amount, remarks,
            reference, actor_id,
        )

    def add_overdraft(
        self,
        driver_id: int,
        transaction_type: str,
        amount: Any,
        effective_date: str,
        remarks: Optional[str],
        actor_id: str,
    ) -> Dict[str, Any]:
        from payroll import PayrollService

        return PayrollService(self).add_overdraft(
            driver_id, transaction_type, amount, effective_date, remarks, actor_id
        )

    def finalize_payroll(
        self,
        start_date: str,
        end_date: str,
        settle_overdraft: bool,
        actor_id: str,
    ) -> Dict[str, Any]:
        from payroll import PayrollService

        return PayrollService(self).finalize(
            start_date, end_date, settle_overdraft, actor_id
        )

    def delete_trip(self, trip_id: int, user_id: Optional[str] = None) -> None:
        if user_id is not None:
            row = self.get_trip(trip_id)
            if not self._matches_owner(row, user_id):
                raise FleetManagementError(f"You do not have access to trip {trip_id}")
        self._delete("trips", trip_id)

    def delete_maintenance(self, maintenance_id: int, user_id: Optional[str] = None) -> None:
        if user_id is not None:
            row = self.get_maintenance(maintenance_id)
            if not self._matches_owner(row, user_id):
                raise FleetManagementError(f"You do not have access to maintenance record {maintenance_id}")
        self._delete("maintenance", maintenance_id)

    def delete_fuel_log(self, fuel_id: int, user_id: Optional[str] = None) -> None:
        if user_id is not None:
            row = self.get_fuel(fuel_id)
            if not self._matches_owner(row, user_id):
                raise FleetManagementError(f"You do not have access to fuel log {fuel_id}")
        self._delete("fuel_logs", fuel_id)

    def dashboard(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        vehicles = self._list("vehicles", select="status")
        drivers = self._list("drivers", select="status")
        fuel_logs = self._filter_owned_rows(self._list("fuel_logs", select="total_cost"), user_id)
        maintenance = self._filter_owned_rows(self._list("maintenance", select="cost"), user_id)
        trips = self._filter_owned_rows(self._list("trips", select="id"), user_id)
        return {
            "total_vehicles": len(vehicles),
            "active_drivers": sum(driver["status"] == "active" for driver in drivers),
            "assigned_vehicles": sum(vehicle["status"] == "assigned" for vehicle in vehicles),
            "total_fuel_spend": sum(float(item["total_cost"]) for item in fuel_logs),
            "total_maintenance": sum(float(item["cost"]) for item in maintenance),
            "recent_trips": len(trips),
        }

    def export_report(self, output_path: str) -> Dict[str, Any]:
        from excel_report import build_excel_report

        data = {
            "vehicles": self.list_vehicles(),
            "drivers": self.list_drivers(),
            "assignments": self.list_assignments(),
            "trips": self.list_trips(),
            "maintenance": self.list_maintenance(),
            "fuel_logs": self.list_fuel_logs(),
            "dashboard": self.dashboard(),
        }
        with open(output_path, "wb") as handle:
            handle.write(build_excel_report(data).getvalue())
        return {
            "output_path": output_path,
            "records_written": sum(
                len(value) for value in data.values() if isinstance(value, list)
            ),
        }


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Good Luck Forwarding Systems Inc. Fleet Management System"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_vehicle = subparsers.add_parser("add-vehicle", help="Add a new vehicle")
    add_vehicle.add_argument("--plate-number", required=True)
    add_vehicle.add_argument("--make", required=True)
    add_vehicle.add_argument("--model", required=True)
    add_vehicle.add_argument("--year", type=int, required=True)
    add_vehicle.add_argument("--color")
    add_vehicle.add_argument("--status", default="available")
    add_vehicle.add_argument("--odometer", type=int, default=0)
    add_vehicle.add_argument("--registration-expiry")
    add_vehicle.add_argument("--insurance-expiry")

    add_driver = subparsers.add_parser("add-driver", help="Add a new driver")
    add_driver.add_argument("--name", required=True)
    add_driver.add_argument("--license-number", required=True)
    add_driver.add_argument("--phone")
    add_driver.add_argument("--email")
    add_driver.add_argument("--status", default="active")

    assignment = subparsers.add_parser("assign-vehicle", help="Assign a vehicle to a driver")
    assignment.add_argument("--driver-id", type=int, required=True)
    assignment.add_argument("--vehicle-id", type=int, required=True)
    assignment.add_argument("--assigned-date")
    assignment.add_argument("--notes")

    maintenance = subparsers.add_parser("add-maintenance", help="Record maintenance")
    maintenance.add_argument("--vehicle-id", type=int, required=True)
    maintenance.add_argument("--service-type", required=True)
    maintenance.add_argument("--description")
    maintenance.add_argument("--cost", type=float, default=0.0)
    maintenance.add_argument("--performed-on")

    fuel = subparsers.add_parser("add-fuel", help="Record fuel purchase")
    fuel.add_argument("--vehicle-id", type=int, required=True)
    fuel.add_argument("--fuel-type", required=True)
    fuel.add_argument("--quantity", type=float, required=True)
    fuel.add_argument("--price-per-liter", type=float, required=True)
    fuel.add_argument("--total-cost", type=float)
    fuel.add_argument("--logged-on")

    trip = subparsers.add_parser("add-trip", help="Record a trip")
    trip.add_argument("--vehicle-id", type=int, required=True)
    trip.add_argument("--driver-id", type=int, required=True)
    trip.add_argument("--route", required=True)
    trip.add_argument("--start-odometer", type=int, required=True)
    trip.add_argument("--end-odometer", type=int, required=True)
    trip.add_argument("--trip-date")
    trip.add_argument("--notes")

    subparsers.add_parser("list-vehicles", help="List all vehicles")
    subparsers.add_parser("list-drivers", help="List all drivers")
    subparsers.add_parser("list-assignments", help="List vehicle assignments")
    subparsers.add_parser("list-trips", help="List recorded trips")
    subparsers.add_parser("dashboard", help="Display fleet summary")

    export = subparsers.add_parser("export-report", help="Export fleet data to formatted Excel")
    export.add_argument("--output", default="fleet_system_report.xlsx")
    return parser


def main() -> None:
    parser = _build_cli()
    args = parser.parse_args()
    try:
        manager = FleetManager()
        if args.command == "add-vehicle":
            result = manager.add_vehicle(
                args.plate_number, args.make, args.model, args.year, args.color,
                args.status, args.odometer, args.registration_expiry, args.insurance_expiry,
            )
        elif args.command == "add-driver":
            result = manager.add_driver(
                args.name, args.license_number, args.phone, args.email, args.status
            )
        elif args.command == "assign-vehicle":
            result = manager.assign_vehicle(
                args.driver_id, args.vehicle_id, args.assigned_date, args.notes
            )
        elif args.command == "add-maintenance":
            result = manager.add_maintenance(
                args.vehicle_id, args.service_type, args.description, args.cost, args.performed_on
            )
        elif args.command == "add-fuel":
            result = manager.add_fuel(
                args.vehicle_id, args.fuel_type, args.quantity,
                args.price_per_liter, args.total_cost, args.logged_on,
            )
        elif args.command == "add-trip":
            result = manager.add_trip(
                args.vehicle_id, args.driver_id, args.route, args.start_odometer,
                args.end_odometer, args.trip_date, args.notes,
            )
        elif args.command == "list-vehicles":
            result = manager.list_vehicles()
        elif args.command == "list-drivers":
            result = manager.list_drivers()
        elif args.command == "list-assignments":
            result = manager.list_assignments()
        elif args.command == "list-trips":
            result = manager.list_trips()
        elif args.command == "dashboard":
            result = manager.dashboard()
        elif args.command == "export-report":
            result = manager.export_report(args.output)
        else:
            parser.error(f"Unsupported command: {args.command}")
            return
        _print_json(result)
    except FleetManagementError as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
