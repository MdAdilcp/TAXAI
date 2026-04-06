# OCR Field Normalization Mapping

Documents (payslips, investment proofs, medical bills, rent receipts) are OCR'd and normalized to the following fields.

## Payslip

| Normalized field     | Alternative labels (OCR / forms)        | Type   | Example   |
|----------------------|-----------------------------------------|--------|-----------|
| employee_name        | Employee Name, Name                      | string | John Doe  |
| employer_name        | Employer, Company                        | string | Acme Ltd  |
| month                | Month, Pay Period                        | string | 03        |
| year                 | Year                                     | int    | 2024      |
| basic_salary         | Basic, Basic Salary                      | number | 50000     |
| hra                  | HRA, House Rent Allowance                | number | 20000     |
| special_allowance    | Special Allowance, SA                    | number | 15000     |
| other_allowances     | Other Allowances, Conveyance             | number | 3000      |
| gross_salary         | Gross, Gross Salary, Total Earnings      | number | 88000     |
| professional_tax     | Professional Tax, PT                     | number | 200       |
| income_tax_tds       | TDS, Income Tax                          | number | 5000      |
| other_deductions     | Other Deductions                         | number | 0         |
| net_salary           | Net, Net Salary, Take Home               | number | 82800     |
| ctc_annual           | CTC, Annual CTC                          | number | 1056000   |

## Investment proof

| Normalized field   | Alternative labels           | Type   | Example   |
|--------------------|------------------------------|--------|-----------|
| provider_name      | Insurer, Fund House          | string | LIC       |
| policy_or_fund_name| Policy No, Fund Name         | string | Policy #  |
| section            | Section, 80C / 80D           | string | 80C       |
| amount             | Amount, Premium, Invested    | number | 150000    |
| financial_year     | FY, Year                     | string | 2023-24   |
| receipt_date       | Date                         | string | 2024-01-15|

## Medical bill

| Normalized field   | Alternative labels   | Type   |
|--------------------|----------------------|--------|
| hospital_or_provider| Hospital, Clinic    | string |
| patient_name       | Patient               | string |
| amount             | Total, Amount         | number |
| date               | Date                  | string |
| description        | Description           | string |

## Rent receipt

| Normalized field | Alternative labels   | Type   |
|------------------|----------------------|--------|
| landlord_name    | Landlord             | string |
| tenant_name      | Tenant               | string |
| address          | Property Address     | string |
| month            | Month                | string |
| year             | Year                 | int    |
| rent_amount      | Rent, Amount         | number |
| pan_landlord     | Landlord PAN         | string |
