"use strict";

const TITLES = {
  dashboard: "Fleet overview",
  vehicles: "Vehicles",
  drivers: "Drivers",
  assignments: "Assignments",
  maintenance: "Maintenance",
  fuel: "Fuel logs",
  trips: "Trips",
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

const state = { data: null, page: "dashboard", search: "", csrfToken: "" };
const view = document.querySelector("#app-view");

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
  view.innerHTML = state.page === "dashboard" ? renderDashboard() : renderResource(state.page);
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

view.addEventListener("submit", (event) => {
  const form = event.target.closest(".record-form");
  if (!form) return;
  event.preventDefault();
  if (form.reportValidity()) submitForm(form);
});

view.addEventListener("input", (event) => {
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

document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", () => {
    state.search = "";
    document.querySelector("#sidebar").classList.remove("sidebar-open");
    document.querySelector("#menu-toggle").setAttribute("aria-expanded", "false");
  });
});

document.querySelector("#menu-toggle").addEventListener("click", (event) => {
  const sidebar = document.querySelector("#sidebar");
  const open = sidebar.classList.toggle("sidebar-open");
  event.currentTarget.setAttribute("aria-expanded", String(open));
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
    window.location.replace("/login");
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
