-- seed_data.sql
-- Seeds benchmark/reference data + sample CMS MPFS into facets_sim.
-- Run AFTER schema_facets_sim.sql, e.g. from Azure Cloud Shell:
--   sqlcmd -S <server>.database.windows.net -d hca -U <admin> -P "$PWD" -i db/seed_data.sql
-- Idempotent (deletes then inserts), so it is safe to re-run. No Python/pyodbc needed.
-- (The prompt registry is optional — agents/agent_rag.py has built-in fallback prompts.)

DELETE FROM facets_sim.provider_agreement;
INSERT INTO facets_sim.provider_agreement
    (provider_npi, contract_id, state, lob, effective_date, terminate_date) VALUES
    ('1234567890', 'C-TX-001', 'TX', 'Medicare', '2023-01-01', NULL),
    ('1987654321', 'C-NY-001', 'NY', 'Medicaid', '2022-03-01', NULL);
GO

DELETE FROM facets_sim.filing_rule;
INSERT INTO facets_sim.filing_rule (state, lob, days_to_file) VALUES
    ('TX', 'Medicare', 120),
    ('FL', 'Medicare', 90),
    ('CA', 'Medicare', 95),
    ('NY', 'Medicaid', 90),
    ('TX', 'Medicaid', 95);
GO

DELETE FROM facets_sim.reimbursement_policy;
INSERT INTO facets_sim.reimbursement_policy
    (state, lob, lesser_of_required, expected_pct_of_medicare) VALUES
    ('TX', 'Medicare', 1, 100.00),
    ('FL', 'Medicare', 1, 100.00),
    ('CA', 'Medicare', 1, 100.00),
    ('NY', 'Medicaid', 1, 100.00),
    ('TX', 'Medicaid', 1, 100.00);
GO

DELETE FROM facets_sim.mpfs_fee;
INSERT INTO facets_sim.mpfs_fee
    (cpt_code, locality, description, conversion_factor, rvu, amount) VALUES
    ('97110', '0000000', 'Therapeutic exercises', 32.74, 0.85, 27.83),
    ('97140', '0000000', 'Manual therapy techniques', 32.74, 0.81, 26.52),
    ('97530', '0000000', 'Therapeutic activities', 32.74, 0.92, 30.12),
    ('97112', '0000000', 'Neuromuscular reeducation', 32.74, 0.88, 28.81),
    ('97116', '0000000', 'Gait training therapy', 32.74, 0.78, 25.54),
    ('92507', '0000000', 'Speech/hearing therapy individual', 32.74, 1.30, 42.56),
    ('92526', '0000000', 'Oral function therapy', 32.74, 1.18, 38.63),
    ('99213', '0000000', 'Office/outpatient visit est', 32.74, 1.30, 42.56),
    ('99214', '0000000', 'Office/outpatient visit est', 32.74, 1.92, 62.86),
    ('99203', '0000000', 'Office/outpatient visit new', 32.74, 1.60, 52.38),
    ('99204', '0000000', 'Office/outpatient visit new', 32.74, 2.60, 85.12),
    ('20610', '0000000', 'Drain/inject joint/bursa', 32.74, 1.97, 64.50),
    ('73610', '0000000', 'X-ray exam of ankle', 32.74, 0.59, 19.32),
    ('20550', '0000000', 'Inj tendon sheath/ligament', 32.74, 0.86, 28.16),
    ('G0283', '0000000', 'Electrical stimulation therapy', 32.74, 0.55, 18.01);
GO
