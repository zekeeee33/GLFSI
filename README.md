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

The web app requires Supabase email/password authentication. Its access and
refresh tokens are stored in HttpOnly, SameSite cookies; protected pages, data
APIs, and report exports reject unauthenticated requests. State-changing API
requests also require a CSRF token. For an HTTPS deployment, set
`COOKIE_SECURE=true`; leave it `false` for local HTTP development.

The **Export Excel report** action downloads a pre-formatted `.xlsx` workbook
with a dashboard summary and separate worksheets for vehicles, drivers,
assignments, maintenance, fuel logs, and trips.

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
