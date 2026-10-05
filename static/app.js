"use strict";

const TITLES = {
  dashboard: "Fleet overview",
  vehicles: "Vehicles",
  drivers: "Drivers",
  assignments: "Assignments",
  maintenance: "Maintenance",
  fuel: "Fuel logs",
  trips: "Trips",
  payroll: "Payroll",
};

const RESOURCE_CONFIG = {
  vehicles: {
    api: "vehicles",
    title: "Vehicle registry",
    singular: "vehicle",
    fields: [
      { name: "plate_number", label: "Registration number", required: true },
      { name: "make", label: "Make", required: true },
      { name: "model", label: "Model", required: true },
      { name: "year", label: "Year", type: "number", required: true, min: 1900 },
      { name: "color", label: "Color" },
      {
        name: "status",
        label: "Status",
        type: "select",
        options: [["available", "Available"], ["assigned", "Assigned"], ["maintenance", "In maintenance"]],
      },
      { name: "odometer", label: "Odometer (km)", type: "number", min: 0, value: 0 },
      { name: "registration_expiry", label: "Registration expiry", type: "date" },
      { name: "insurance_expiry", label: "Insurance expiry", type: "date" },
    ],
    columns: [
      ["plate_number", "Registration"],
      ["make", "Make"],
      ["model", "Model"],
      ["year", "Year"],
      ["odometer", "Odometer", (value) => `${formatNumber(value)} km`],
      ["status", "Status", statusBadge],
    ],
  },
  drivers: {
    api: "drivers",
    title: "Driver directory",
    singular: "driver",
    fields: [
      { name: "name", label: "Full name", required: true },
      { name: "license_number", label: "License number", required: true },
      { name: "phone", label: "Phone", type: "tel" },
      { name: "email", label: "Email", type: "email" },
      {
        name: "status",
        label: "Status",
        type: "select",
        options: [["active", "Active"], ["inactive", "Inactive"]],
      },
    ],
    columns: [
      ["name", "Driver"],
      ["license_number", "License"],
      ["phone", "Phone"],
      ["email", "Email"],
      ["status", "Status", statusBadge],
    ],
  },
  assignments: {
    api: "assignments",
    title: "Vehicle assignments",
    singular: "assignment",
    fields: [
      { name: "driver_id", label: "Driver", type: "driver", required: true },
      { name: "vehicle_id", label: "Vehicle", type: "vehicle", required: true },
      { name: "assigned_date", label: "Assigned date", type: "date" },
      { name: "notes", label: "Notes", type: "textarea" },
    ],
    columns: [
      ["driver_name", "Driver"],
      ["plate_number", "Vehicle"],
      ["make", "Make"],
      ["assigned_date", "Assigned"],
      ["returned_date", "Returned"],
    ],
  },
  maintenance: {
    api: "maintenance",
    title: "Maintenance records",
    singular: "maintenance record",
    fields: [
      { name: "vehicle_id", label: "Vehicle", type: "vehicle", required: true },
      { name: "service_type", label: "Service type", required: true },
      { name: "description", label: "Description", type: "textarea" },
      { name: "cost", label: "Cost", type: "number", min: 0, step: "0.01", value: 0 },
      { name: "performed_on", label: "Service date", type: "date" },
    ],
    columns: [
      ["plate_number", "Vehicle"],
      ["service_type", "Service"],
      ["description", "Description"],
      ["performed_on", "Date"],
      ["cost", "Cost", formatCurrency],
    ],
  },
  fuel: {
    api: "fuel",
    title: "Fuel logs",
    singular: "fuel log",
    fields: [
      { name: "vehicle_id", label: "Vehicle", type: "vehicle", required: true },
      { name: "fuel_type", label: "Fuel type", required: true },
      { name: "quantity", label: "Quantity (L)", type: "number", min: 0.01, step: "0.01", required: true },
      { name: "price_per_liter", label: "Price per liter", type: "number", min: 0.01, step: "0.01", required: true },
      { name: "total_cost", label: "Total cost (optional)", type: "number", min: 0, step: "0.01" },
      { name: "logged_on", label: "Date", type: "date" },
    ],
    columns: [
      ["plate_number", "Vehicle"],
      ["fuel_type", "Fuel"],
      ["quantity", "Quantity", (value) => `${formatNumber(value)} L`],
      ["logged_on", "Date"],
      ["total_cost", "Total cost", formatCurrency],
    ],
  },
  trips: {
    api: "trips",
    title: "Trip history",
    singular: "trip",
    fields: [
      { name: "ism_no", label: "ISM No" },
      { name: "shipment_date", label: "Shipment date", type: "date", required: true },
      { name: "time_in", label: "Time in", type: "time" },
      { name: "time_out", label: "Time out", type: "time" },
      { name: "origin", label: "Origin", required: true },
      { name: "destination", label: "Destination", required: true },
      { name: "vehicle_id", label: "Vehicle", type: "vehicle", required: true },
      { name: "driver_id", label: "Driver", type: "driver", required: true },
      { name: "load_details", label: "Load" },
      { name: "trip_fuel", label: "Trip/Fuel" },
    ],
    columns: [
      ["ism_no", "ISM NO"],
      ["shipment_date", "SHIPMENT DATE"],
      ["time_in", "TIME IN"],
      ["time_out", "TIME OUT"],
      ["origin", "ORIGIN"],
      ["destination", "DESTINATION"],
      ["plate_number", "PLATE NO"],
      ["load_details", "LOAD"],
      ["driver_name", "DRIVER"],
      ["trip_fuel", "TRIP/FUEL"],
    ],
  },
};

function isoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const today = new Date();
const SESSION_IDLE_TIMEOUT_MS = 3 * 60 * 1000;
const SESSION_ACTIVITY_PING_INTERVAL_MS = 30 * 1000;
const state = {
  data: null,
  page: "dashboard",
  search: "",
  csrfToken: "",
  payroll: null,
  payrollKey: "",
  payrollRequestedKey: "",
  payrollPeriod: {
    start_date: isoDate(new Date(today.getFullYear(), today.getMonth(), 1)),
    end_date: isoDate(new Date(today.getFullYear(), today.getMonth() + 1, 0)),
  },
  payrollFilters: { driver_id: "", ism_no: "", origin: "", destination: "" },
};
const view = document.querySelector("#app-view");
let idleLogoutTimer;
let lastActivityPing = 0;

function returnToSignIn() {
  window.location.replace("/login?expired=1");
}

function registerSessionActivity() {
  window.clearTimeout(idleLogoutTimer);
  idleLogoutTimer = window.setTimeout(returnToSignIn, SESSION_IDLE_TIMEOUT_MS);

  const now = Date.now();
  if (now - lastActivityPing < SESSION_ACTIVITY_PING_INTERVAL_MS) return;
  lastActivityPing = now;
  fetch("/api/auth/me", { cache: "no-store" })
    .then((response) => {
      if (response.status === 401) returnToSignIn();
    })
    .catch(() => showToast("Could not verify the session. Check your connection.", "error"));
}

for (const eventName of ["pointerdown", "keydown", "scroll", "touchstart"]) {
  window.addEventListener(eventName, registerSessionActivity, { passive: true });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat().format(number) : "—";
}

function formatCurrency(value) {
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("en-PH", {
      style: "currency",
      currency: "PHP",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(number)
    : "—";
}

function statusBadge(value) {
  const status = String(value || "unknown").toLowerCase();
  return `<span class="badge badge-${escapeHtml(status)}">${escapeHtml(status.replaceAll("_", " "))}</span>`;
}

function showToast(message, kind = "success") {
  const region = document.querySelector("#toast-region");
  region.innerHTML = `<div class="toast toast-${kind}" role="status">${escapeHtml(message)}</div>`;
  window.setTimeout(() => {
    region.replaceChildren();
  }, 4500);
}

async function api(path, options = {}) {
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...options.headers,
  };
  if (["POST", "PUT", "PATCH", "DELETE"].includes(options.method?.toUpperCase())) {
    headers["X-CSRF-Token"] = state.csrfToken;
  }
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.location.replace("/login");
    }
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

async function loadData() {
  view.setAttribute("aria-busy", "true");
  try {
    state.data = await api("/api/bootstrap");
    state.csrfToken = state.data.csrf_token || "";
    document.querySelector("#signed-in-user").textContent = state.data.user?.email || "";
    registerSessionActivity();
    render();
  } catch (error) {
    view.innerHTML = `
      <section class="error-card">
        <p class="eyebrow">Connection problem</p>
        <h1>Could not load fleet data</h1>
        <p>${escapeHtml(error.message)}</p>
        <button class="button button-primary" data-action="retry" type="button">Try again</button>
      </section>`;
  } finally {
    view.setAttribute("aria-busy", "false");
  }
}

function header(eyebrow, title, description = "", action = "") {
  return `
    <div class="page-heading">
      <div>
        <p class="eyebrow">${escapeHtml(eyebrow)}</p>
        <h1>${escapeHtml(title)}</h1>
        ${description ? `<p class="page-description">${escapeHtml(description)}</p>` : ""}
      </div>
      <div class="page-heading-actions">
        ${action}
        <button class="button button-secondary" data-action="refresh" type="button">↻ Refresh</button>
      </div>
    </div>`;
}

function statCard(label, value, tone, icon) {
  return `
    <article class="stat-card">
      <div class="stat-icon ${tone}" aria-hidden="true">${icon}</div>
      <div class="stat-copy">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    </article>`;
}

function tableMarkup(rows, columns, resource, options = {}) {
  if (!rows.length) {
    return `<div class="empty-state"><span aria-hidden="true">⌁</span><strong>${escapeHtml(options.empty || "Nothing here yet")}</strong><small>Records you add will appear here.</small></div>`;
  }
  const headings = columns.map(([, label]) => `<th scope="col">${escapeHtml(label)}</th>`).join("");
  const actionHeader = resource ? '<th class="action-column" scope="col">Action</th>' : "";
  const body = rows.map((row) => {
    const cells = columns.map(([key, , formatter]) => {
      const value = formatter ? formatter(row[key]) : escapeHtml(row[key] ?? "—");
      return `<td>${value}</td>`;
    }).join("");
    const action = resource
      ? `<td class="action-column"><button class="icon-button delete-button" type="button" data-action="delete" data-resource="${escapeHtml(resource)}" data-id="${escapeHtml(row.id)}" aria-label="Delete record">×</button></td>`
      : "";
    return `<tr>${cells}${action}</tr>`;
  }).join("");
  return `<div class="table-wrap"><table><thead><tr>${headings}${actionHeader}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function panel(title, content, link = "") {
  return `
    <section class="panel">
      <div class="panel-heading">
        <h2>${escapeHtml(title)}</h2>
        ${link ? `<a class="text-link" href="#${escapeHtml(link)}">View all <span aria-hidden="true">→</span></a>` : ""}
      </div>
      ${content}
    </section>`;
}

function renderDashboard() {
  const data = state.data;
  const summary = data.dashboard;
  return `
    ${header("OPERATIONS", "Fleet overview", "Monitor vehicles, drivers, and daily fleet activity.")}
    <div class="stats-grid">
      ${statCard("Total vehicles", formatNumber(summary.total_vehicles), "blue", "▰")}
      ${statCard("Active drivers", formatNumber(summary.active_drivers), "green", "♙")}
      ${statCard("Assigned vehicles", formatNumber(summary.assigned_vehicles), "purple", "⇄")}
      ${statCard("Fuel spend", formatCurrency(summary.total_fuel_spend), "orange", "◉")}
      ${statCard("Maintenance spend", formatCurrency(summary.total_maintenance), "red", "⚙")}
      ${statCard("Trips recorded", formatNumber(summary.recent_trips), "teal", "⌁")}
    </div>
    <div class="dashboard-grid">
      ${panel("Vehicles", tableMarkup(data.vehicles.slice(0, 5), RESOURCE_CONFIG.vehicles.columns, null, { empty: "No vehicles registered" }), "vehicles")}
      ${panel("Recent trips", tableMarkup(data.trips.slice(0, 5), [
        ["origin", "Origin"],
        ["destination", "Destination"],
        ["plate_number", "Plate no"],
        ["driver_name", "Driver"],
        ["shipment_date", "Shipment date"],
      ], null, { empty: "No trips recorded" }), "trips")}
      ${panel("Vehicle assignments", tableMarkup(data.assignments.slice(0, 5), RESOURCE_CONFIG.assignments.columns, null, { empty: "No assignments yet" }), "assignments")}
      ${panel("Maintenance", tableMarkup(data.maintenance.slice(0, 5), RESOURCE_CONFIG.maintenance.columns, null, { empty: "No maintenance records" }), "maintenance")}
    </div>`;
}

function optionMarkup(type) {
  const records = type === "vehicle" ? state.data.vehicles : state.data.drivers;
  const label = type === "vehicle"
    ? (record) => `${record.plate_number} · ${record.make} ${record.model}`
    : (record) => record.name;
  const options = records.map((record) => `<option value="${escapeHtml(record.id)}">${escapeHtml(label(record))}</option>`).join("");
  return `<option value="">Select ${type === "vehicle" ? "a vehicle" : "a driver"}</option>${options}`;
}

function fieldMarkup(field) {
  const required = field.required ? "required" : "";
  const min = field.min !== undefined ? `min="${escapeHtml(field.min)}"` : "";
  const step = field.step ? `step="${escapeHtml(field.step)}"` : "";
  const value = field.value !== undefined ? `value="${escapeHtml(field.value)}"` : "";
  let control;
  if (field.type === "select") {
    control = `<select id="field-${field.name}" name="${field.name}" ${required}>${field.options.map(([key, label]) => `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`).join("")}</select>`;
  } else if (field.type === "vehicle" || field.type === "driver") {
    const records = field.type === "vehicle" ? state.data.vehicles : state.data.drivers;
    control = `<select id="field-${field.name}" name="${field.name}" ${required} ${records.length ? "" : "disabled"}>${optionMarkup(field.type)}</select>${records.length ? "" : `<small class="field-hint">Add a ${field.type} first.</small>`}`;
  } else if (field.type === "textarea") {
    control = `<textarea id="field-${field.name}" name="${field.name}" rows="3" ${required}></textarea>`;
  } else {
    control = `<input id="field-${field.name}" name="${field.name}" type="${escapeHtml(field.type || "text")}" ${min} ${step} ${value} ${required} />`;
  }
  return `<label class="form-field" for="field-${field.name}"><span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>${control}</label>`;
}

function filterRows(rows, columns) {
  const term = state.search.trim().toLocaleLowerCase();
  if (!term) return rows;
  return rows.filter((row) => columns.some(([key]) => String(row[key] ?? "").toLocaleLowerCase().includes(term)));
}

function renderResource(page) {
  const config = RESOURCE_CONFIG[page];
  const listKey = page === "fuel" ? "fuel_logs" : page;
  const rows = filterRows(state.data[listKey], config.columns);
  const hasOptions = config.fields.some((field) => field.type === "vehicle" || field.type === "driver");
  if (page === "trips") {
    const needsReferences = config.fields.some(
      (field) =>
        (field.type === "vehicle" && !state.data.vehicles.length) ||
        (field.type === "driver" && !state.data.drivers.length),
    );
    return `
      ${header(
        "FLEET DATA",
        config.title,
        "Review the complete shipment report. Use the table’s horizontal scrollbar on narrow screens.",
        '<button class="button button-primary" data-action="new-record" type="button"><span aria-hidden="true">＋</span> New record</button>',
      )}
      <section class="panel records-panel trips-report">
        <div class="panel-heading records-heading">
          <div><p class="eyebrow">SHIPMENT MANIFEST</p><h2>${escapeHtml(config.title)}</h2></div>
          <label class="search-box"><span class="sr-only">Search trips</span><span aria-hidden="true">⌕</span><input type="search" id="record-search" placeholder="Search trips" value="${escapeHtml(state.search)}" /></label>
        </div>
        <p class="record-count">${formatNumber(rows.length)} ${rows.length === 1 ? "record" : "records"}</p>
        ${tableMarkup(rows, config.columns, null, { empty: "No trip records" })}
      </section>
      <dialog class="record-dialog" aria-labelledby="trip-dialog-title">
        <div class="dialog-header">
          <div><p class="eyebrow">SHIPMENT MANIFEST</p><h2 id="trip-dialog-title">New trip record</h2></div>
          <button class="icon-button dialog-close" data-action="close-record" type="button" aria-label="Close dialog">×</button>
        </div>
        <form class="record-form dialog-form" data-form="trips">
          <div class="dialog-fields">${config.fields.map(fieldMarkup).join("")}</div>
          <p class="dialog-error" role="alert" hidden></p>
          <div class="dialog-actions">
            <button class="button button-secondary" data-action="close-record" type="button">Cancel</button>
            <button class="button button-primary" type="submit" ${needsReferences ? "disabled" : ""}>Save trip</button>
          </div>
        </form>
      </dialog>`;
  }
  return `
    ${header("FLEET DATA", config.title, `Create and review ${config.singular} records.`)}
    <div class="resource-layout">
      <section class="panel form-panel">
        <div class="panel-heading"><div><p class="eyebrow">NEW RECORD</p><h2>Add ${escapeHtml(config.singular)}</h2></div></div>
        <form class="record-form" data-form="${page}">
          <div class="form-fields">${config.fields.map(fieldMarkup).join("")}</div>
          <button class="button button-primary" type="submit" ${hasOptions && config.fields.some((field) => (field.type === "vehicle" && !state.data.vehicles.length) || (field.type === "driver" && !state.data.drivers.length)) ? "disabled" : ""}>
            <span aria-hidden="true">＋</span> Save ${escapeHtml(config.singular)}
          </button>
        </form>
      </section>
      <section class="panel records-panel">
        <div class="panel-heading records-heading">
          <div><p class="eyebrow">RECORDS</p><h2>${escapeHtml(config.title)}</h2></div>
          <label class="search-box"><span class="sr-only">Search ${escapeHtml(config.title.toLowerCase())}</span><span aria-hidden="true">⌕</span><input type="search" id="record-search" placeholder="Search records" value="${escapeHtml(state.search)}" /></label>
        </div>
        <p class="record-count">${formatNumber(rows.length)} ${rows.length === 1 ? "record" : "records"}</p>
        ${tableMarkup(rows, config.columns, page === "trips" ? null : config.api, { empty: `No ${config.singular} records` })}
      </section>
    </div>`;
}

function payrollOptionMarkup(records, selected, key, entityLabel, displayField) {
  return `<option value="">All ${entityLabel}s</option>${records.map((record) =>
    `<option value="${escapeHtml(record[key])}" ${String(record[key]) === String(selected) ? "selected" : ""}>${escapeHtml(record[displayField])}</option>`,
  ).join("")}`;
}

function payrollCsvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function payrollRows() {
  const report = state.payroll || { trips: [], drivers: [] };
  const filters = state.payrollFilters;
  const search = filters.ism_no.trim().toLocaleLowerCase();
  return report.trips.filter((trip) =>
    (!filters.driver_id || String(trip.driver_id) === filters.driver_id)
    && (!search || String(trip.ism_no || "").toLocaleLowerCase().includes(search))
    && (!filters.origin || trip.origin === filters.origin)
    && (!filters.destination || trip.destination === filters.destination),
  );
}

function sumCurrency(rows, field) {
  const cents = rows.reduce((total, row) => total + Math.round(Number(row[field] || 0) * 100), 0);
  return cents / 100;
}

function renderPayroll() {
  const report = state.payroll;
  const [startDate, endDate] = [state.payrollPeriod.start_date, state.payrollPeriod.end_date];
  const key = `${startDate}:${endDate}`;
  if (state.payrollKey !== key && state.payrollRequestedKey !== key) {
    state.payrollRequestedKey = key;
    api(`/api/payroll?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`)
      .then((result) => {
        state.payroll = result;
        state.payrollKey = key;
        if (state.page === "payroll") render();
      })
      .catch((error) => {
        state.payrollRequestedKey = "";
        if (state.page === "payroll") {
          view.innerHTML = `${header("PAYROLL", "Payroll", "Driver earnings and payroll review.")}<div class="error-card"><p>${escapeHtml(error.message)}</p><button class="button button-primary" data-action="payroll-reload" type="button">Retry</button></div>`;
        }
      });
  }

  const drivers = report?.drivers || [];
  const allTrips = report?.trips || [];
  const visibleTrips = payrollRows();
  const selectedDriver = state.payrollFilters.driver_id;
  const driverSummaries = drivers.filter((driver) =>
    !selectedDriver || String(driver.driver_id) === selectedDriver,
  );
  const totals = {
    gross: sumCurrency(driverSummaries, "gross_pay"),
    advances: sumCurrency(driverSummaries, "cash_advances"),
    overdraft: sumCurrency(driverSummaries.map((driver) => ({
      outstanding: driver.remaining_overdraft ?? driver.overdraft_balance,
    })), "outstanding"),
    net: sumCurrency(driverSummaries.map((driver) => ({
      payable: driver.final_net_pay ?? Math.max(Number(driver.net_before_overdraft || 0), 0),
    })), "payable"),
  };
  const eligibleIds = new Set(visibleTrips.filter((trip) => trip.eligible).map((trip) => String(trip.id)));
  const visibleSummary = driverSummaries.map((driver) => ({
    ...driver,
    total_trips: (report?.trips || []).filter((trip) =>
      (trip.driver_key || `id:${trip.driver_id}`) === (driver.driver_key || `id:${driver.driver_id}`)
      && trip.eligible && eligibleIds.has(String(trip.id)),
    ).length,
  }));
  const status = report?.status || "draft";
  const isDraft = status === "draft";
  const tripColumns = [
    ["payroll_date", "Date"],
    ["driver_name", "Driver Name"],
    ["ism_no", "ISM Number"],
    ["origin", "Origin"],
    ["destination", "Destination"],
    ["rate", "Trip Rate", (value) => value == null ? "Unconfigured Route" : formatCurrency(value)],
    ["issue", "Review"],
  ];
  const origins = [...new Set(allTrips.map((trip) => trip.origin).filter(Boolean))].sort();
  const destinations = [...new Set(allTrips.map((trip) => trip.destination).filter(Boolean))].sort();
  const driverCards = visibleSummary.map((driver) => {
    const driverKey = driver.driver_key || `id:${driver.driver_id}`;
    const driverTrips = visibleTrips.filter((trip) =>
      (trip.driver_key || `id:${trip.driver_id}`) === driverKey,
    );
    const cashAdvances = report?.cash_advances?.filter((advance) =>
      String(advance.driver_id) === String(driver.driver_id),
    ) || [];
    return `
      <details class="payroll-driver-details">
        <summary>
          <span><strong>${escapeHtml(driver.driver_name)}</strong><small>${formatNumber(driver.total_trips)} eligible trips</small></span>
          <span class="payroll-summary-amount">${formatCurrency(driver.gross_pay)}</span>
          <span class="badge badge-${escapeHtml(status)}">${escapeHtml(status)}</span>
          <span class="button button-secondary button-small">View Details</span>
        </summary>
        <div class="payroll-driver-body">
          ${tableMarkup(driverTrips, tripColumns, null, { empty: "No trips for this driver in the selected filters" })}
          <div class="payroll-financial-grid">
            <span>Gross pay <strong>${formatCurrency(driver.gross_pay)}</strong></span>
            <span>Cash advances <strong>${formatCurrency(driver.cash_advances)}</strong></span>
            <span>Claims <strong>Coming Soon</strong></span>
            <span>Opening overdraft <strong>${formatCurrency(driver.opening_overdraft)}</strong></span>
            <span>New overdraft <strong>${formatCurrency(driver.new_overdraft)}</strong></span>
            <span>Overdraft deduction <strong>${formatCurrency(driver.overdraft_deduction)}</strong></span>
            <span>Net before overdraft <strong>${formatCurrency(driver.net_before_overdraft)}</strong></span>
            <span>Final net pay <strong>${formatCurrency(driver.final_net_pay ?? Math.max(Number(driver.net_before_overdraft || 0), 0))}</strong></span>
            <span>Remaining amount due <strong>${formatCurrency(driver.remaining_amount_due)}</strong></span>
            <span>Outstanding overdraft <strong>${formatCurrency(driver.remaining_overdraft ?? driver.overdraft_balance)}</strong></span>
          </div>
          ${driver.overdraft_transactions?.length ? `<div><p class="eyebrow">OVERDRAFT TRANSACTION HISTORY</p>${tableMarkup(driver.overdraft_transactions, [
            ["effective_date", "Date"],
            ["transaction_type", "Transaction"],
            ["amount", "Amount", formatCurrency],
            ["remarks", "Remarks"],
          ], null, { empty: "No overdraft transactions" })}</div>` : ""}
          ${cashAdvances.length ? `<p class="record-count">Cash advances: ${cashAdvances.map((advance) => `${escapeHtml(advance.advance_date)} · ${formatCurrency(advance.amount)}${advance.remarks ? ` · ${escapeHtml(advance.remarks)}` : ""}`).join(" | ")}</p>` : ""}
        </div>
      </details>`;
  }).join("");
  return `
    ${header("FINANCE", "Payroll", "Review route-based earnings, advances, overdrafts, and driver payroll.", '<button class="button button-secondary" data-action="payroll-print" type="button">Print Payroll</button><button class="button button-secondary" data-action="payroll-export" type="button">Export CSV</button>')}
    <div class="payroll-period-bar">
      <form id="payroll-period-form" class="payroll-toolbar">
        <label class="form-field"><span>Period start</span><input name="start_date" type="date" value="${escapeHtml(startDate)}" required /></label>
        <label class="form-field"><span>Period end</span><input name="end_date" type="date" value="${escapeHtml(endDate)}" required /></label>
        <button class="button button-primary" type="submit">Generate Report</button>
        <span class="badge badge-${escapeHtml(status)}">${escapeHtml(status)}</span>
      </form>
      <div class="payroll-filter-grid">
        <label class="form-field"><span>Driver</span><select id="payroll-driver-filter">${payrollOptionMarkup(state.data.drivers, selectedDriver, "id", "driver", "name")}</select></label>
        <label class="form-field"><span>Search ISM number</span><input id="payroll-ism-filter" type="search" placeholder="Search ISM" value="${escapeHtml(state.payrollFilters.ism_no)}" /></label>
        <label class="form-field"><span>Origin</span><select id="payroll-origin-filter"><option value="">All origins</option>${origins.map((origin) => `<option ${origin === state.payrollFilters.origin ? "selected" : ""} value="${escapeHtml(origin)}">${escapeHtml(origin)}</option>`).join("")}</select></label>
        <label class="form-field"><span>Destination</span><select id="payroll-destination-filter"><option value="">All destinations</option>${destinations.map((destination) => `<option ${destination === state.payrollFilters.destination ? "selected" : ""} value="${escapeHtml(destination)}">${escapeHtml(destination)}</option>`).join("")}</select></label>
      </div>
    </div>
    <div class="stats-grid payroll-stats">
      ${statCard("Total Drivers", formatNumber(driverSummaries.length), "blue", "♙")}
      ${statCard("Total Trips", formatNumber(visibleTrips.filter((trip) => trip.eligible).length), "teal", "⌁")}
      ${statCard("Total Gross Payroll", formatCurrency(totals.gross), "green", "₱")}
      ${statCard("Total Cash Advances", formatCurrency(totals.advances), "orange", "↓")}
      ${statCard("Total Overdraft Balance", formatCurrency(totals.overdraft), "red", "↗")}
      ${statCard("Total Net Payable", formatCurrency(totals.net), "purple", "✓")}
    </div>
    <section class="panel payroll-workflow">
      <div><p class="eyebrow">PAYROLL WORKFLOW</p><h2>${escapeHtml(status === "finalized" ? "Payroll finalized" : status === "reviewed" ? "Ready for finalization" : "Draft payroll")}</h2><p class="page-description">Draft earnings use origin and destination only. A registered driver and ISM number are required when reviewing payroll. Claims are not deducted.</p></div>
      <div class="page-heading-actions">
        ${isDraft ? '<button class="button button-secondary" data-action="payroll-review" type="button">Review Payroll</button>' : ""}
        ${status === "reviewed" ? '<label class="settlement-toggle"><input id="settle-overdraft" type="checkbox" /> Settle overdraft from payable amount</label><button class="button button-primary" data-action="payroll-finalize" type="button">Finalize Payroll</button>' : ""}
      </div>
    </section>
    ${report?.issues?.length ? `<section class="panel payroll-issues"><div class="panel-heading"><div><p class="eyebrow">REQUIRES REVIEW</p><h2>${formatNumber(report.issues.length)} trips need attention</h2></div></div><p class="page-description">These trips are excluded from earnings. Resolve the origin, destination, route, or duplicate-payroll issue shown for each trip in the Trips data.</p>${tableMarkup(report.issues, tripColumns, null, { empty: "No review issues" })}</section>` : ""}
    <section class="panel payroll-advances">
      <div class="panel-heading"><div><p class="eyebrow">CASH ADVANCES</p><h2>Record an advance</h2></div></div>
      ${isDraft ? `<form id="cash-advance-form" class="payroll-entry-form">
        <label class="form-field"><span>Driver</span><select name="driver_id" required><option value="">Select driver</option>${state.data.drivers.map((driver) => `<option value="${escapeHtml(driver.id)}">${escapeHtml(driver.name)}</option>`).join("")}</select></label>
        <label class="form-field"><span>Date</span><input name="advance_date" type="date" min="${escapeHtml(startDate)}" max="${escapeHtml(endDate)}" required /></label>
        <label class="form-field"><span>Amount (₱)</span><input name="amount" type="number" min="0.01" step="0.01" required /></label>
        <label class="form-field"><span>Reference (optional)</span><input name="reference" type="text" maxlength="100" /></label>
        <label class="form-field"><span>Remarks (optional)</span><input name="remarks" type="text" maxlength="500" /></label>
        <button class="button button-primary" type="submit">Add Advance</button>
      </form>` : '<p class="page-description">Cash advances are locked after payroll review.</p>'}
    </section>
    <section class="panel payroll-advances">
      <div class="panel-heading"><div><p class="eyebrow">OVERDRAFT LEDGER</p><h2>Record an approved overdraft transaction</h2></div></div>
      <form id="overdraft-form" class="payroll-entry-form">
        <label class="form-field"><span>Driver</span><select name="driver_id" required><option value="">Select driver</option>${state.data.drivers.map((driver) => `<option value="${escapeHtml(driver.id)}">${escapeHtml(driver.name)}</option>`).join("")}</select></label>
        <label class="form-field"><span>Transaction</span><select name="transaction_type"><option value="opening">Opening balance</option><option value="new">New overdraft</option></select></label>
        <label class="form-field"><span>Effective date</span><input name="effective_date" type="date" value="${escapeHtml(endDate)}" required /></label>
        <label class="form-field"><span>Amount (₱)</span><input name="amount" type="number" min="0.01" step="0.01" required /></label>
        <label class="form-field"><span>Remarks</span><input name="remarks" type="text" maxlength="500" required /></label>
        <button class="button button-secondary" type="submit">Record Overdraft</button>
      </form>
      <p class="page-description">Overdraft entries require an explicit administrator action; negative payroll is never converted automatically.</p>
    </section>
    <section class="panel payroll-drivers">
      <div class="panel-heading"><div><p class="eyebrow">DRIVER STATEMENTS</p><h2>Payroll by driver</h2></div><span class="record-count">${formatNumber(visibleSummary.length)} drivers</span></div>
      ${driverCards || '<div class="empty-state"><span>₱</span><strong>No payroll results</strong><small>Select a period and generate the report.</small></div>'}
    </section>
    ${report?.audit_history?.length ? `<section class="panel payroll-issues"><div class="panel-heading"><div><p class="eyebrow">AUDIT HISTORY</p><h2>Payroll period activity</h2></div></div>${tableMarkup(report.audit_history.map((entry) => ({
      created_at: entry.created_at,
      action: entry.action,
      actor_id: entry.actor_id,
      details: JSON.stringify(entry.details || {}),
    })), [
      ["created_at", "Date"],
      ["action", "Action"],
      ["actor_id", "User"],
      ["details", "Details"],
    ], null, { empty: "No payroll changes recorded" })}</section>` : ""}
    <section class="panel records-panel trips-report payroll-trip-report">
      <div class="panel-heading"><div><p class="eyebrow">TRIP LINE ITEMS</p><h2>Payroll report detail</h2></div><span class="record-count">${formatNumber(visibleTrips.length)} trips</span></div>
      ${tableMarkup(visibleTrips, tripColumns, null, { empty: "No trips in this payroll period" })}
    </section>`;
}

function render() {
  if (!state.data) return;
  state.page = location.hash.slice(1) in TITLES ? location.hash.slice(1) : "dashboard";
  document.title = `${TITLES[state.page]} · Good Luck Forwarding Systems Inc.`;
  document.querySelectorAll(".nav-link").forEach((link) => {
    const active = link.dataset.page === state.page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  view.innerHTML = state.page === "dashboard"
    ? renderDashboard()
    : state.page === "payroll" ? renderPayroll() : renderResource(state.page);
}

async function submitForm(form) {
  const page = form.dataset.form;
  const config = RESOURCE_CONFIG[page];
  const payload = Object.fromEntries(new FormData(form).entries());
  for (const field of config.fields) {
    if (field.type === "number" && payload[field.name] !== "") {
      payload[field.name] = Number(payload[field.name]);
    } else if (field.type === "vehicle" || field.type === "driver") {
      payload[field.name] = Number(payload[field.name]);
    } else if (payload[field.name] === "") {
      payload[field.name] = null;
    }
  }
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    await api(`/api/${config.api}`, { method: "POST", body: JSON.stringify(payload) });
    showToast(`${capitalize(config.singular)} saved successfully.`);
    state.search = "";
    const dialog = form.closest("dialog");
    if (dialog?.open) dialog.close();
    await loadData();
  } catch (error) {
    const errorMessage = form.querySelector(".dialog-error");
    if (errorMessage) {
      errorMessage.textContent = error.message;
      errorMessage.hidden = false;
    } else {
      showToast(error.message, "error");
    }
  } finally {
    if (submit.isConnected) submit.disabled = false;
  }
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

async function deleteRecord(button) {
  const config = Object.values(RESOURCE_CONFIG).find((item) => item.api === button.dataset.resource);
  if (!config || !window.confirm(`Delete this ${config.singular}? Related history may also be removed.`)) return;
  button.disabled = true;
  try {
    await api(`/api/${config.api}/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
    showToast(`${capitalize(config.singular)} deleted.`);
    await loadData();
  } catch (error) {
    showToast(error.message, "error");
    button.disabled = false;
  }
}

async function submitPayrollForm(form) {
  const values = Object.fromEntries(new FormData(form).entries());
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    if (form.id === "payroll-period-form") {
      if (values.start_date > values.end_date) {
        throw new Error("Period start must be on or before period end.");
      }
      state.payrollPeriod = { start_date: values.start_date, end_date: values.end_date };
      state.payroll = null;
      state.payrollKey = "";
      state.payrollRequestedKey = "";
      render();
      return;
    }
    if (form.id === "cash-advance-form") {
      values.driver_id = Number(values.driver_id);
      values.amount = Number(values.amount);
      values.start_date = state.payrollPeriod.start_date;
      values.end_date = state.payrollPeriod.end_date;
      await api("/api/payroll/cash-advances", { method: "POST", body: JSON.stringify(values) });
      showToast("Cash advance recorded.");
    } else if (form.id === "overdraft-form") {
      values.driver_id = Number(values.driver_id);
      values.amount = Number(values.amount);
      await api("/api/payroll/overdrafts", { method: "POST", body: JSON.stringify(values) });
      showToast("Overdraft transaction recorded.");
    }
    await reloadPayroll();
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    if (submit.isConnected) submit.disabled = false;
  }
}

async function reloadPayroll() {
  const { start_date: startDate, end_date: endDate } = state.payrollPeriod;
  state.payroll = await api(
    `/api/payroll?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`,
  );
  state.payrollKey = `${startDate}:${endDate}`;
  state.payrollRequestedKey = state.payrollKey;
  if (state.page === "payroll") render();
}

async function payrollWorkflowAction(action) {
  const { start_date: startDate, end_date: endDate } = state.payrollPeriod;
  const button = view.querySelector(`[data-action="${action}"]`);
  if (button) button.disabled = true;
  try {
    if (action === "payroll-review") {
      state.payroll = await api("/api/payroll/review", {
        method: "POST",
        body: JSON.stringify({ start_date: startDate, end_date: endDate }),
      });
      showToast("Payroll reviewed. Verify the details before finalizing.");
    } else if (action === "payroll-finalize") {
      const settleOverdraft = Boolean(view.querySelector("#settle-overdraft")?.checked);
      if (!window.confirm("Finalize and lock this payroll period?")) {
        if (button?.isConnected) button.disabled = false;
        return;
      }
      state.payroll = await api("/api/payroll/finalize", {
        method: "POST",
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          settle_overdraft: settleOverdraft,
        }),
      });
      showToast("Payroll finalized and locked.");
    }
    state.payrollKey = `${startDate}:${endDate}`;
    state.payrollRequestedKey = state.payrollKey;
    render();
  } catch (error) {
    showToast(error.message, "error");
    if (button?.isConnected) button.disabled = false;
  }
}

function exportPayrollCsv() {
  const rows = payrollRows();
  const headers = ["Date", "Driver Name", "ISM Number", "Origin", "Destination", "Trip Rate", "Review"];
  const fields = ["payroll_date", "driver_name", "ism_no", "origin", "destination", "rate", "issue"];
  const lines = [
    headers.map(payrollCsvCell).join(","),
    ...rows.map((trip) => fields.map((field) =>
      payrollCsvCell(field === "rate" && trip.rate != null ? Number(trip.rate).toFixed(2) : trip[field]),
    ).join(",")),
    "",
    ["Driver", "Trips", "Gross Pay", "Cash Advances", "Net Before Overdraft", "Overdraft Deduction", "Final Net Pay", "Remaining Due"].map(payrollCsvCell).join(","),
    ...(state.payroll?.drivers || []).map((driver) => [
      driver.driver_name,
      driver.total_trips,
      driver.gross_pay,
      driver.cash_advances,
      driver.net_before_overdraft,
      driver.overdraft_deduction,
      driver.final_net_pay ?? Math.max(Number(driver.net_before_overdraft || 0), 0),
      driver.remaining_amount_due,
    ].map(payrollCsvCell).join(",")),
  ];
  const blob = new Blob(["\uFEFF", lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `payroll-${state.payrollPeriod.start_date}-to-${state.payrollPeriod.end_date}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

view.addEventListener("submit", (event) => {
  const payrollForm = event.target.closest("#payroll-period-form, #cash-advance-form, #overdraft-form");
  if (payrollForm) {
    event.preventDefault();
    if (payrollForm.reportValidity()) submitPayrollForm(payrollForm);
    return;
  }
  const form = event.target.closest(".record-form");
  if (!form) return;
  event.preventDefault();
  if (form.reportValidity()) submitForm(form);
});

view.addEventListener("input", (event) => {
  if (event.target.id === "payroll-ism-filter") {
    const position = event.target.selectionStart;
    state.payrollFilters.ism_no = event.target.value;
    render();
    const nextInput = document.querySelector("#payroll-ism-filter");
    nextInput?.focus();
    nextInput?.setSelectionRange(position, position);
    return;
  }
  if (event.target.id !== "record-search") return;
  const position = event.target.selectionStart;
  state.search = event.target.value;
  render();
  const nextInput = document.querySelector("#record-search");
  nextInput?.focus();
  nextInput?.setSelectionRange(position, position);
});

view.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  if (button.dataset.action === "retry" || button.dataset.action === "refresh") loadData();
  if (button.dataset.action === "payroll-reload") {
    state.payrollRequestedKey = "";
    render();
  }
  if (button.dataset.action === "payroll-review" || button.dataset.action === "payroll-finalize") {
    payrollWorkflowAction(button.dataset.action);
  }
  if (button.dataset.action === "payroll-print") window.print();
  if (button.dataset.action === "payroll-export") exportPayrollCsv();
  if (button.dataset.action === "new-record") {
    const dialog = view.querySelector(".record-dialog");
    if (dialog && !dialog.open) {
      dialog.showModal();
      dialog.querySelector("input, select, textarea")?.focus();
    }
  }
  if (button.dataset.action === "close-record") {
    button.closest("dialog")?.close();
  }
  if (button.dataset.action === "delete") deleteRecord(button);
});

view.addEventListener("change", (event) => {
  const filterMap = {
    "payroll-driver-filter": "driver_id",
    "payroll-origin-filter": "origin",
    "payroll-destination-filter": "destination",
  };
  const key = filterMap[event.target.id];
  if (!key) return;
  state.payrollFilters[key] = event.target.value;
  render();
});

const appShell = document.querySelector(".app-shell");
const sidebar = document.querySelector("#sidebar");
const menuToggle = document.querySelector("#menu-toggle");
const sidebarBackdrop = document.querySelector("#sidebar-backdrop");
const mobileNavigation = window.matchMedia("(max-width: 760px)");

function setSidebarOpen(open) {
  if (mobileNavigation.matches) {
    sidebar.classList.toggle("sidebar-open", open);
    sidebarBackdrop.classList.toggle("sidebar-backdrop-open", open);
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    if (open) sidebar.querySelector(".nav-link")?.focus();
    return;
  }

  appShell.classList.toggle("sidebar-collapsed", !open);
  menuToggle.setAttribute("aria-expanded", String(open));
  menuToggle.setAttribute("aria-label", open ? "Collapse navigation" : "Expand navigation");
}

setSidebarOpen(!mobileNavigation.matches && !appShell.classList.contains("sidebar-collapsed"));

document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", () => {
    state.search = "";
    if (mobileNavigation.matches) setSidebarOpen(false);
  });
});

menuToggle.addEventListener("click", () => {
  if (mobileNavigation.matches) {
    setSidebarOpen(!sidebar.classList.contains("sidebar-open"));
  } else {
    setSidebarOpen(appShell.classList.contains("sidebar-collapsed"));
  }
});

sidebarBackdrop.addEventListener("click", () => setSidebarOpen(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && sidebar.classList.contains("sidebar-open")) {
    setSidebarOpen(false);
    menuToggle.focus();
  }
});
mobileNavigation.addEventListener("change", () => {
  sidebar.classList.remove("sidebar-open");
  sidebarBackdrop.classList.remove("sidebar-backdrop-open");
  menuToggle.setAttribute("aria-expanded", String(!appShell.classList.contains("sidebar-collapsed")));
  menuToggle.setAttribute(
    "aria-label",
    appShell.classList.contains("sidebar-collapsed") ? "Expand navigation" : "Collapse navigation",
  );
});

document.querySelector("#sign-out").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const response = await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": state.csrfToken },
      cache: "no-store",
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `Sign out failed (${response.status}).`);
    }
    returnToSignIn();
  } catch (error) {
    showToast(error.message, "error");
    button.disabled = false;
  }
});

window.addEventListener("hashchange", () => {
  state.search = "";
  render();
});

if (!location.hash) location.hash = "dashboard";
loadData();
