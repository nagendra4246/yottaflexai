# Deterministic synthetic data generation

The generator creates synthetic employee, leave, expense, approval, and
reimbursement records. It uses no real personal information. Master records are
created first; dependent rows reference their generated IDs. Derived totals,
business days, balance components, and approval/reimbursement records are
calculated from their source data.

Run from the repository root:

```powershell
python -m generator.generator
```

By default, the generator uses seed `20261022` and writes to
`data/generated/`. An alternate seed and output path may be provided:

```powershell
python -m generator.generator --seed 20261022 --output .\data\generated
```

The same generator supports smaller reproducibility/evaluation fixtures by
changing the employee, leave-request, expense-claim, and per-claim line counts:

```powershell
python -m generator.generator --seed 20261022 --output .\data\starter `
  --employees 20 --leave-requests 40 --expense-claims 30 `
  --min-expense-lines 1 --max-expense-lines 3
```

The generator keeps six leave policies and the required labelled scenarios at
every supported scale. Minimum supported counts are 3 employees, 4 leave
requests, and 7 expense claims; expense lines must be between 1 and 10. The
full-scale defaults remain 400 employees, 800 leave requests, 1,000 claims,
and 1–10 lines per claim.

Load the application entity CSVs into an empty, migrated database:

```powershell
python -m generator.load_data
```

Set `DATABASE_URL` first when running locally. The loader imports only the
12 entity CSVs in dependency order, converts dates, timestamps, booleans, and
decimals to schema types, and relies on database foreign keys/constraints for
referential integrity. The entire load is transactional. If any application
table already contains rows, it reports a skip and preserves all existing
data; it never merges or truncates records. Docker runs the same loader after
migrations by default; set `SEED_DATA=false` to disable it.

The export contains one CSV per database entity, `anomaly_cases.csv`,
`ground_truth.csv` and `ground_truth.json` (separate label-only files),
`seed_data.json` and `seed_data.sql` (application entities only),
`source_manifest.json`, `validation_summary.json`, and
`generation_metadata.json`. The validation module checks key uniqueness,
references, hierarchy cycles, policy applicability, leave day and balance
arithmetic, expense totals and limits, workflow status/steps, reimbursement
eligibility, and required anomaly labels before any files are written.

`ground_truth.csv` contains labels only; scenario payloads for deliberately
invalid submissions (for example, an unknown cost center or duplicate
reimbursement attempt) are kept separately in `anomaly_cases.csv`. Neither
file is loaded into application tables. The backend image contains only the 12
entity CSVs. Structural violations of database
constraints are represented as rejected test-case inputs rather than invalid
foreign-key rows. The explicitly required negative balance, approved-leave
overlap, out-of-employment expense, and self-approval anomalies appear in their
corresponding dataset rows and have separate ground-truth labels.

The SQL script inserts only the 12 application tables and assumes migrations
have already been applied. Neither ground truth nor anomaly payloads are added
to application seed data. `generation_metadata.json` records the seed,
generation configuration, synthetic-only source manifest, validation summary,
row counts, and SHA-256 checksums for each generated export (excluding the
metadata file itself). Repeated generation with the same seed and configuration
produces identical IDs and file content.

To run generator checks:

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python -m pytest .\generator\tests -q
```
