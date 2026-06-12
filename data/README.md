# Synthetic Demo Data

**All data in this directory is synthetic.** It is fabricated for demos and tests of
the Healthcare Contract Auditor. No file here is a real contract, and no figure
represents an actual CMS payment determination.

## Files

| File | What it is |
| --- | --- |
| `mpfs_2025.csv` | Sample CMS Medicare Physician Fee Schedule (MPFS) rows. Loaded into `facets_sim.mpfs_fee` by `db/seed_mpfs.py`. |
| `generate_synthetic_contracts.py` | Standalone reportlab script that writes the sample contract PDFs into `contracts/`. |
| `contracts/contract_provider_a.pdf` | Provider A agreement — **compliant** sample. |
| `contracts/contract_provider_b.pdf` | Provider B agreement — **non-compliant** sample. |
| `contracts/amendment_provider_a.pdf` | Amendment to Provider A (later timely-filing window, for timeline reconciliation demos). |

## Demo entities

### Provider A — COMPLIANT (`contract_provider_a.pdf`)
- NPI `1234567890`, Contract `C-TX-001`, State `TX`, LOB `Medicare`, Effective `Jan 1, 2023`.
- Timely filing: **90 days** (matches the benchmark).
- Lesser-of clause present.
- Reimbursement at **100% of Medicare**, including physical therapy CPT 97110 / 97530.

### Provider B — NON-COMPLIANT (`contract_provider_b.pdf`)
- NPI `1987654321`, Contract `C-NY-001`, State `NY`, LOB `Medicaid`, Effective `Mar 1, 2022`.
- Timely filing: **180 days** — exceeds the 90-day benchmark (expected to fail, e.g. `TF001`).
- **No lesser-of clause** — expected to fail `LL001`.
- Speech therapy CPT 92507 reimbursed at **130% of Medicare** vs. an expected 100% (expected to fail `FS002`).

### Amendment to Provider A (`amendment_provider_a.pdf`)
- Amends `C-TX-001` (NPI `1234567890`) effective `Jan 1, 2024`, changing the timely-filing
  window to **120 days**. Used to demonstrate amendment/timeline reconciliation.

## `mpfs_2025.csv`

Sample CMS MPFS data used as the fee-schedule ground truth in `facets_sim.mpfs_fee`.

- Columns: `cpt_code,locality,description,conversion_factor,rvu,amount`.
- Every row uses locality `0000000` (the app's default locality) and a conversion
  factor of `32.74`. `amount ≈ rvu × conversion_factor`, rounded to 2 decimals.
- Includes the CPT codes referenced by the synthetic contracts (97110, 97530, 92507,
  99213, 99214) plus additional realistic CPT/HCPCS codes.

## Regenerating the PDFs

From the repo root (`C:\RAG`), with the project venv (reportlab installed):

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\Scripts\uv.exe" run --directory "C:\RAG" python data\generate_synthetic_contracts.py
```
