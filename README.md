# Good Luck Forwarding Systems Inc. Fleet Management System

A fleet management system with a semantic HTML5 interface, responsive CSS3
styling, and a vanilla JavaScript single-page frontend. Flask provides a JSON
API and securely connects to Supabase; the Supabase service key never goes into
browser code.

It tracks vehicles, drivers, assignments, maintenance, fuel purchases, and trips.
The web interface supports light and dark themes, follows the device preference
by default, and remembers the selected theme in the browser.

## Supabase setup

1. Create a Supabase project.
2. In the Supabase SQL Editor, run [`supabase_schema.sql`](./supabase_schema.sql).
3. Copy `.env.example` to `.env`.
4. Fill in `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and
   `SUPABASE_SERVICE_ROLE_KEY` from the project's API settings. The anon or
   publishable key is used for password authentication; the service-role/secret
   key is used only by the server for fleet data access. Never put the
   service-role key in browser code or commit either secret to source control.
5. Replace `SECRET_KEY` with a long random value (for example, generate one with
   `python -c "import secrets; print(secrets.token_hex(32))"`).
6. In Supabase **Authentication → Users**, invite or create each authorized
   user's email/password account. Public sign-up is not enabled by this app.

## Dispatcher roles and data isolation

Run [`supabase_dispatcher_ownership_migration.sql`](./supabase_dispatcher_ownership_migration.sql)
in the Supabase SQL Editor before using dispatcher accounts. It adds immutable
`created_by` ownership fields to trips, fuel logs, and maintenance records.
It also adds private image storage for trip load manifests and fuel invoices.
If you ran an earlier version of this migration, run the updated file again;
the changes are safe to reapply. The migration also advances the trip, fuel,
and maintenance ID counters past existing records, which prevents duplicate
IDs after CSV imports. Existing records remain unowned and are visible only to
administrators.

Set a dispatcher's role to `dispatcher` in that user's Supabase **User Metadata**
to enable the compatibility role restriction. Prefer setting `role` in
**App Metadata** when provisioning accounts server-side; App Metadata is
administrator-controlled. The application never accepts `administrator` from
User Metadata as an authorization grant. Users without an explicit dispatcher
role retain the existing administrator access model.

Dispatchers can access their own trips, fuel logs, and maintenance records and
the shared vehicle/driver choices needed to submit them. Payroll, system
exports, fleet-wide pages, and delete requests are denied by the server as well
as hidden in the dispatcher interface.

Trip entry accepts an optional load-manifest image, and fuel-log entry accepts
an optional invoice image. JPG, PNG, and WEBP files are decoded and validated
on the server and limited to 10 MB by default. Set
`DOCUMENT_IMAGE_MAX_BYTES` to change the server-side per-image limit (up to the
bucket's 50 MB limit). Images are stored in a private Supabase Storage bucket
and delivered through record-ownership-checked app endpoints; they are not
public URLs. Selecting a trip row in the dashboard or Trips page opens a
details popup with its route, vehicle, driver, shipment information, and
uploaded load manifest when available. The popup also lets authorized users
upload a missing manifest later or replace the current image.

Open a trip to edit its shipment details and review its edit history. Each
change records the authenticated editor, timestamp, and before/after values.
The edit history is stored by a database trigger; run the current
`supabase_dispatcher_ownership_migration.sql` in Supabase before deploying this
feature. Dispatchers can edit only their own trips.

The web app requires Supabase email/password authentication. Its access and
refresh tokens are stored in HttpOnly, SameSite browser-session cookies;
protected pages, data APIs, and report exports reject unauthenticated requests.
Sessions expire after three minutes of inactivity, and the open page returns to
sign-in when idle. State-changing API requests also require a CSRF token. For an
HTTPS deployment, set `COOKIE_SECURE=true`; leave it `false` for local HTTP
development.

## Deploy on Vercel

Vercel does not use your local `.env` file. In the Vercel project, open
**Settings → Environment Variables** and add these server-side variables for
every environment you deploy (Production, and Preview if applicable):

- `SUPABASE_URL`: the project URL from Supabase **Settings → API**.
- `SUPABASE_ANON_KEY`: the project's anon/publishable key, used for sign-in.
- `SUPABASE_SERVICE_ROLE_KEY`: the service-role/secret key, used by the server
  to read and update fleet records. Never add this key to frontend code.
- `SECRET_KEY`: a long, random value used to sign session cookies. Generate a
  value locally with `python -c "import secrets; print(secrets.token_hex(32))"`
  and enter it directly in Vercel; do not commit it.
- `COOKIE_SECURE`: `true` for the HTTPS Vercel deployment.

After saving or changing environment variables, redeploy the project so the
serverless functions receive them. A `503` from `/api/auth/login` means the
server could not initialize Supabase Auth; check the response's JSON `error`
and confirm the Vercel `SUPABASE_URL` and `SUPABASE_ANON_KEY` values. If sign-in
then returns `401`, the Supabase connection is working, but the account
credentials were rejected.

The **Export Excel report** action downloads a pre-formatted `.xlsx` workbook
with a dashboard summary and separate worksheets for vehicles, drivers,
assignments, maintenance, fuel logs, and trips.

## Payroll setup and workflow

After creating the fleet/trips tables, run
[`supabase_payroll_migration.sql`](./supabase_payroll_migration.sql) in the
Supabase SQL Editor. This adds payroll periods, immutable reviewed trip/rate
snapshots, driver summaries, cash advances, overdraft transactions, and audit
history. Payroll uses the existing trip and driver IDs and does not copy or
modify trip records. The migration's database function finalizes payroll
atomically and prevents a trip from being finalized in more than one period.

Payroll is available to signed-in users, matching the existing app-wide access
model (the current app does not define separate user roles). Payroll eligibility
uses the route fields and does not require `time_in` or `time_out`. Shipment date
is taken from `shipment_date`, then the legacy `trip_date` or `record_date`.
When `driver_id` is missing, a unique, case-insensitive full-name or last-name
match is used if available; ambiguous matches remain under the imported name.
Matched trips are grouped under the registered driver's full name.
Trips with missing origin/destination, unknown routes, or already finalized
elsewhere are flagged and excluded. A registered driver and ISM number are
required to review and save payroll.

Rates are ₱200 for DAV2–PLAS, DAV1–DAV2, and DAV1–PLAS, and ₱900 for
GENSAN–DAV2, GENSAN–PLAS, and GENSAN–DAV1, in either direction. Payroll review
snapshots each eligible trip and its rate. Finalized payroll retains those
values if trips or route rules later change. Cash advances must be recorded before
review; overdrafts are recorded as explicit opening/new ledger entries and are
never inferred from negative pay. Overdraft settlement is separately confirmed
at finalization. Claims are shown as Coming Soon and do not affect pay.
Payroll reports can be printed or exported as CSV.

## Run the app

```powershell
python -m pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000> and sign in with an account created in Supabase
Authentication. Flask serves the static frontend from
[`static/index.html`](./static/index.html), [`static/style.css`](./static/style.css),
and [`static/app.js`](./static/app.js), plus the sign-in screen in
[`static/login.html`](./static/login.html). The JavaScript client uses the
same-origin `/api/` endpoints for data.

The same Supabase project is used by the command-line interface:

```powershell
python fleet_management.py dashboard
python fleet_management.py add-vehicle --plate-number ABC-123 --make Toyota --model Hiace --year 2022
python fleet_management.py export-report
```

The CLI export writes the same pre-formatted Excel workbook as the web export
to `fleet_system_report.xlsx` by default. Use `--output` to choose another file
path (the file contents remain an Excel workbook).

## Data tables

The schema creates `vehicles`, `drivers`, `assignments`, `maintenance`,
`fuel_logs`, and `trips`. The foreign keys cascade deletion of a vehicle or
driver to its related history.

For an existing Supabase project, run
[`supabase_trips_csv_schema.sql`](./supabase_trips_csv_schema.sql) in the SQL
Editor to adapt `public.trips` to the manifest CSV columns. It preserves
existing trip rows, makes database vehicle/driver IDs optional for imported
records, and backfills fields where possible. For a new project, run
`supabase_schema.sql` first, then this file.

The Trips page columns are ISM NO, SHIPMENT DATE, TIME IN, TIME OUT, ORIGIN,
DESTINATION, PLATE NO, LOAD, DRIVER, and TRIP/FUEL.

To import the supplied sample manifest into an existing project:

1. Run `supabase_trips_csv_schema.sql` first.
2. In Supabase Table Editor, open `public.trips` and choose **Import data from CSV**.
3. Upload [`supabase_trips_import.csv`](./supabase_trips_import.csv).

Dates in the supplied file were converted using 2026. The source's first date
is retained as `record_date`; the second date is `shipment_date`. The CSV also
populates the legacy `route` and `trip_date` columns. Since the source contains
plate numbers and driver names rather than database IDs, it leaves
`vehicle_id` and `driver_id` empty while preserving the source values in
`plate_no` and `driver_name`.

## Test

```powershell
python -m unittest discover -s tests -v
```
