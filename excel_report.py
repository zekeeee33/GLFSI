from __future__ import annotations

import json
from datetime import date, datetime, time
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

EXCEL_REPORT_SHEETS = (
    ("vehicles", "Vehicles", (
        "id", "plate_number", "make", "model", "year", "color", "status",
        "odometer", "registration_expiry", "insurance_expiry", "created_at",
    )),
    ("drivers", "Drivers", (
        "id", "name", "license_number", "phone", "email", "status", "created_at",
    )),
    ("assignments", "Assignments", (
        "id", "driver_id", "driver_name", "vehicle_id", "plate_number", "make",
        "model", "assigned_date", "returned_date", "notes",
    )),
    ("maintenance", "Maintenance", (
        "id", "vehicle_id", "plate_number", "service_type", "description",
        "cost", "performed_on",
    )),
    ("fuel_logs", "Fuel Logs", (
        "id", "vehicle_id", "plate_number", "fuel_type", "quantity",
        "price_per_liter", "total_cost", "logged_on",
    )),
    ("trips", "Trips", (
        "id", "record_date", "ism_no", "shipment_date", "time_in", "time_out",
        "origin", "destination", "vehicle_id", "plate_no", "plate_number",
        "make", "model", "driver_id", "driver_name", "load_details", "trip_fuel",
        "route", "start_odometer", "end_odometer", "trip_date", "notes",
    )),
)

EXCEL_CURRENCY_FIELDS = {"cost", "price_per_liter", "total_cost"}
EXCEL_DATE_FIELDS = {
    "assigned_date", "created_at", "insurance_expiry", "logged_on",
    "performed_on", "record_date", "registration_expiry", "returned_date",
    "shipment_date", "trip_date",
}


def _excel_cell_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if field in EXCEL_DATE_FIELDS and isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    if field in {"time_in", "time_out"} and isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except ValueError:
            return value
    return value


def build_excel_report(report: dict[str, Any]) -> BytesIO:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Dashboard"
    workbook.properties.title = "Fleet Management System Report"
    workbook.properties.subject = "System-wide fleet operations report"
    title_fill = PatternFill("solid", fgColor="17365D")
    header_fill = PatternFill("solid", fgColor="1F4E78")
    alternate_fill = PatternFill("solid", fgColor="EAF1F8")

    def format_sheet(
        worksheet: Any,
        title: str,
        headers: list[str],
        rows: list[list[Any]],
    ) -> None:
        worksheet.sheet_view.showGridLines = False
        worksheet.merge_cells(
            start_row=1, start_column=1, end_row=1, end_column=max(1, len(headers))
        )
        title_cell = worksheet.cell(row=1, column=1, value=title)
        title_cell.font = Font(name="Aptos Display", size=16, bold=True, color="FFFFFF")
        title_cell.fill = title_fill
        title_cell.alignment = Alignment(vertical="center")
        worksheet.row_dimensions[1].height = 30
        worksheet.cell(
            row=2,
            column=1,
            value=f"Generated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        )
        worksheet.cell(row=2, column=1).font = Font(italic=True, color="64748B")

        header_row = 4
        for column_index, header in enumerate(headers, start=1):
            cell = worksheet.cell(
                row=header_row,
                column=column_index,
                value=header.replace("_", " ").title(),
            )
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        worksheet.row_dimensions[header_row].height = 30

        for row_index, values in enumerate(rows, start=header_row + 1):
            for column_index, value in enumerate(values, start=1):
                cell = worksheet.cell(row=row_index, column=column_index, value=value)
                if isinstance(value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if row_index % 2:
                    cell.fill = alternate_fill
                field = headers[column_index - 1]
                if field in EXCEL_CURRENCY_FIELDS:
                    cell.number_format = '"₱"#,##0.00;[Red]-"₱"#,##0.00'
                elif field == "quantity":
                    cell.number_format = "#,##0.00"
                elif field in EXCEL_DATE_FIELDS and isinstance(value, date):
                    cell.number_format = "yyyy-mm-dd"
                elif field in {"time_in", "time_out"} and isinstance(value, time):
                    cell.number_format = "hh:mm"

        if headers:
            last_column = len(headers)
            last_row = max(header_row, header_row + len(rows))
            last_column_letter = get_column_letter(last_column)
            worksheet.auto_filter.ref = f"A{header_row}:{last_column_letter}{last_row}"
            worksheet.freeze_panes = "A5"
            worksheet.print_title_rows = "1:4"
            worksheet.page_setup.orientation = "landscape"
            worksheet.page_setup.fitToWidth = 1
            worksheet.page_setup.fitToHeight = 0
            worksheet.sheet_properties.pageSetUpPr.fitToPage = True
            for column_index, header in enumerate(headers, start=1):
                values_for_width = [header.replace("_", " ").title()]
                values_for_width.extend(
                    str(row[column_index - 1]) if row[column_index - 1] is not None else ""
                    for row in rows
                )
                width = min(max(max(map(len, values_for_width), default=0) + 2, 12), 42)
                worksheet.column_dimensions[get_column_letter(column_index)].width = width

    summary_rows = [
        [key.replace("_", " ").title(), value]
        for key, value in report["dashboard"].items()
    ]
    format_sheet(summary, "Fleet Management System - Dashboard", ["metric", "value"], summary_rows)
    for row in range(5, summary.max_row + 1):
        metric = summary.cell(row=row, column=1).value
        if metric in {"Total Fuel Spend", "Total Maintenance"}:
            summary.cell(row=row, column=2).number_format = '"₱"#,##0.00;[Red]-"₱"#,##0.00'

    for data_key, sheet_title, base_fields in EXCEL_REPORT_SHEETS:
        records = report[data_key]
        headers = list(base_fields)
        for record in records:
            headers.extend(
                field for field in record
                if field not in headers and field not in {"driver", "vehicle"}
            )
        rows = [
            [_excel_cell_value(field, record.get(field)) for field in headers]
            for record in records
        ]
        format_sheet(workbook.create_sheet(sheet_title), sheet_title, headers, rows)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output
