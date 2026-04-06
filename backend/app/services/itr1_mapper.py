"""ITR-1 mapper for Form16/Form26AS extracted OCR payloads."""

from __future__ import annotations

from typing import Any


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _first(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in data:
            value = _to_int(data.get(key))
            if value is not None:
                return value
    return None


def _sum_int(values: list[int | None]) -> int:
    return sum(v for v in values if isinstance(v, int))


def _part_a_rows(form26as: dict[str, Any]) -> list[dict[str, Any]]:
    rows = form26as.get("tds_credits") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        section = str(row.get("section") or "")
        if section and not section.startswith("192"):
            continue
        amount_paid = _first(row, "amount_paid", "amount_paid_credited", "amount")
        tds_deducted = _first(row, "amount_deducted", "tax_deducted")
        tds_deposited = _first(row, "tax_deposited", "amount_deposited", "amount_deducted")
        out.append(
            {
                "pa_deductor_name": row.get("deductor_name") or row.get("deductor") or None,
                "pa_deductor_tan": row.get("tan") or None,
                "pa_amount_paid": amount_paid,
                "pa_tds_deducted": tds_deducted,
                "pa_tds_deposited": tds_deposited,
                "_source": {
                    "pa_deductor_name": "Form26AS Part A / Deductor Name",
                    "pa_deductor_tan": "Form26AS Part A / TAN",
                    "pa_amount_paid": "Form26AS Part A / Amount Paid/Credited",
                    "pa_tds_deducted": "Form26AS Part A / Tax Deducted",
                    "pa_tds_deposited": "Form26AS Part A / Tax Deposited",
                },
            }
        )
    return out


def _part_b_rows(form26as: dict[str, Any], ais: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rows = form26as.get("tds_credits") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        section = str(row.get("section") or "")
        if section.startswith("192"):
            continue
        out.append(
            {
                "pb_deductor_name": row.get("deductor_name") or row.get("deductor") or None,
                "pb_nature": row.get("nature") or row.get("section") or None,
                "pb_amount_paid": _first(row, "amount_paid", "amount_paid_credited", "amount"),
                "pb_tds_deposited": _first(row, "tax_deposited", "amount_deposited", "amount_deducted"),
                "_source": {
                    "pb_deductor_name": "Form26AS Part B / Deductor Name",
                    "pb_nature": "Form26AS Part B / Nature of Payment",
                    "pb_amount_paid": "Form26AS Part B / Amount Paid",
                    "pb_tds_deposited": "Form26AS Part B / Tax Deposited",
                },
            }
        )

    if out:
        return out

    for row in (ais.get("tds_credits") or []):
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "pb_deductor_name": row.get("deductor_name") or row.get("deductor") or None,
                "pb_nature": row.get("section") or None,
                "pb_amount_paid": _first(row, "amount_paid", "amount"),
                "pb_tds_deposited": _first(row, "amount_deducted", "tax_deposited"),
                "_source": {
                    "pb_deductor_name": "AIS TDS Credits / Deductor Name",
                    "pb_nature": "AIS TDS Credits / Section",
                    "pb_amount_paid": "AIS TDS Credits / Amount",
                    "pb_tds_deposited": "AIS TDS Credits / Amount Deducted",
                },
            }
        )
    return out


def _challans(ais: dict[str, Any], form26as: dict[str, Any]) -> list[dict[str, Any]]:
    taxes = ais.get("taxes_paid") or form26as.get("taxes_paid") or []
    out: list[dict[str, Any]] = []
    for row in taxes:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "bsr_code": row.get("bsr_code") or row.get("bsr") or None,
                "challan_no": row.get("challan_no") or row.get("serial_no") or None,
                "date": row.get("date") or row.get("deposit_date") or None,
                "amount": _first(row, "amount", "tax_amount"),
                "type": row.get("type") or None,
                "_source": {
                    "bsr_code": "Form26AS Part C / BSR Code",
                    "challan_no": "Form26AS Part C / Challan No",
                    "date": "Form26AS Part C / Date",
                    "amount": "Form26AS Part C / Amount",
                    "type": "Form26AS Part C / Tax Type",
                },
            }
        )
    return out


def build_itr1_payload(extracted_docs: dict[str, Any]) -> dict[str, Any]:
    form16 = extracted_docs.get("form16") or extracted_docs.get("payslip") or {}
    form26as = extracted_docs.get("form26as") or {}
    ais = extracted_docs.get("ais") or {}

    part_a_rows = _part_a_rows(form26as)
    part_b_rows = _part_b_rows(form26as, ais)
    challans = _challans(ais, form26as)

    gross_salary = _first(form16, "gross_salary", "gross_total_income")
    hra_received = _first(form16, "hra", "hra_exemption_u_s_10_13a")
    hra_exempt = _first(form16, "hra_exemption_u_s_10_13a")
    lta_exempt = _first(form16, "lta_exemption_u_s_10_5", "lta")
    other_sec10 = _first(form16, "other_exempt_allowances", "other_section10_exemptions")
    standard_deduction = _first(form16, "standard_deduction")
    professional_tax = _first(form16, "professional_tax", "pt")
    net_salary = _first(form16, "net_taxable_salary", "taxable_income", "net_salary")
    deduction_80c = _first(form16, "deduction_80c", "amount_80c", "total_80c")
    deduction_80d = _first(form16, "deduction_80d", "amount_80d", "health_insurance", "medical_premium")
    deduction_80ccd1b = _first(form16, "deduction_80ccd_1b", "amount_80ccd_1b", "nps")
    deduction_other_via = _first(form16, "other_deductions")
    total_chapter_via = _first(form16, "total_deductions")
    total_taxable_income = _first(form16, "taxable_income", "net_taxable_salary")
    tax_on_income = _first(form16, "tax_on_income", "total_tax")
    surcharge = _first(form16, "surcharge")
    health_edu_cess = _first(form16, "health_education_cess", "cess")
    total_tax_payable = _first(form16, "total_tax_payable", "total_tax")
    relief_u89 = _first(form16, "relief_u89")
    net_tax_payable = _first(form16, "net_tax_payable")
    tds_deducted_by_employer = _first(form16, "tds_deducted", "total_tds_deposited", "tds", "income_tax_tds")

    if total_chapter_via is None:
        total_chapter_via = _sum_int([deduction_80c, deduction_80d, deduction_80ccd1b, deduction_other_via]) or None

    if net_tax_payable is None and total_tax_payable is not None:
        net_tax_payable = total_tax_payable - (relief_u89 or 0)

    tis_salary = _sum_int([_to_int(x.get("amount")) for x in (ais.get("salary_entries") or [])]) or None
    tis_interest = _sum_int([_to_int(x.get("amount")) for x in (ais.get("interest_entries") or [])]) or None
    tis_dividend = _sum_int([_to_int(x.get("amount")) for x in (ais.get("dividend_entries") or [])]) or None

    advance_tax_total = _sum_int([x.get("amount") for x in challans if (x.get("type") or "") == "advance"]) or None
    self_assessment_tax_total = _sum_int([x.get("amount") for x in challans if (x.get("type") or "") == "self_assessment"]) or None

    extraction = {
        "form16": {
            "employer_name": form16.get("employer_name"),
            "employer_tan": form16.get("employer_tan"),
            "employee_pan": form16.get("employee_pan") or form16.get("pan"),
            "employee_name": form16.get("employee_name"),
            "assessment_year": form16.get("assessment_year"),
            "tds_q1": _first(form16, "tds_q1"),
            "tds_q2": _first(form16, "tds_q2"),
            "tds_q3": _first(form16, "tds_q3"),
            "tds_q4": _first(form16, "tds_q4"),
            "total_tds_deposited": _first(form16, "total_tds_deposited", "tds_deducted", "tds"),
            "gross_salary": gross_salary,
            "hra_received": hra_received,
            "hra_exempt": hra_exempt,
            "lta_exempt": lta_exempt,
            "other_sec10_exemptions": other_sec10,
            "standard_deduction": standard_deduction,
            "professional_tax": professional_tax,
            "net_salary": net_salary,
            "deduction_80c": deduction_80c,
            "deduction_80d": deduction_80d,
            "deduction_80ccd1b": deduction_80ccd1b,
            "deduction_other_via": deduction_other_via,
            "total_chapter_via": total_chapter_via,
            "total_taxable_income": total_taxable_income,
            "tax_on_income": tax_on_income,
            "surcharge": surcharge,
            "health_edu_cess": health_edu_cess,
            "total_tax_payable": total_tax_payable,
            "relief_u89": relief_u89,
            "net_tax_payable": net_tax_payable,
            "tds_deducted_by_employer": tds_deducted_by_employer,
            "_source": {
                "total_tds_deposited": "Form16 Part A / Total TDS Deposited",
                "gross_salary": "Form16 Part B / Gross Salary",
                "hra_received": "Form16 Part B / HRA received",
                "hra_exempt": "Form16 Part B / HRA exemption u/s 10(13A)",
                "lta_exempt": "Form16 Part B / LTA exemption u/s 10(5)",
                "standard_deduction": "Form16 Part B / Standard deduction u/s 16(ia)",
                "professional_tax": "Form16 Part B / Professional tax u/s 16(iii)",
                "total_taxable_income": "Form16 Part B / Taxable income",
                "total_tax_payable": "Form16 Part B / Total tax payable",
                "tds_deducted_by_employer": "Form16 Part B / TDS deducted",
            },
        },
        "form26as": {
            "part_a": part_a_rows,
            "pa1_amount": _first(form26as, "pa1_amount"),
            "part_b": part_b_rows,
            "advance_tax_total": advance_tax_total,
            "self_assessment_tax_total": self_assessment_tax_total,
            "challan_details": challans,
            "rent_received": _first(form26as, "rent_received"),
            "tds_on_rent": _first(form26as, "tds_on_rent"),
            "tis_salary": tis_salary,
            "tis_interest": tis_interest,
            "tis_dividend": tis_dividend,
            "_source": {
                "part_a": "Form26AS Part A",
                "part_b": "Form26AS Part B",
                "advance_tax_total": "Form26AS Part C / Advance Tax",
                "self_assessment_tax_total": "Form26AS Part C / Self Assessment Tax",
                "challan_details": "Form26AS Part C / Challans",
                "rent_received": "Form26AS Part F",
                "tds_on_rent": "Form26AS Part F",
                "tis_salary": "Form26AS Part G / TIS Summary",
                "tis_interest": "Form26AS Part G / TIS Summary",
                "tis_dividend": "Form26AS Part G / TIS Summary",
            },
        },
    }

    checks_passed: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    if extraction["form16"]["standard_deduction"] is not None and extraction["form16"]["standard_deduction"] > 50000:
        extraction["form16"]["standard_deduction"] = 50000
        warnings.append("standard_deduction exceeded 50000 and was capped")

    if extraction["form16"]["deduction_80c"] is not None and extraction["form16"]["deduction_80c"] > 150000:
        extraction["form16"]["deduction_80c"] = 150000
        errors.append("80C exceeds limit")

    if extraction["form16"]["deduction_80ccd1b"] is not None and extraction["form16"]["deduction_80ccd1b"] > 50000:
        extraction["form16"]["deduction_80ccd1b"] = 50000
        errors.append("80CCD(1B) exceeds limit")

    salary_tds_sum = _sum_int([row.get("pa_tds_deposited") for row in extraction["form26as"]["part_a"]])
    f16_tds = extraction["form16"].get("tds_deducted_by_employer")
    if f16_tds is not None and salary_tds_sum > 0:
        if abs(f16_tds - salary_tds_sum) <= 1:
            checks_passed.append("TDS consistency")
        else:
            errors.append("TDS mismatch between Form 16 and Form 26AS Part A")

    if extraction["form16"].get("gross_salary") is not None and extraction["form26as"].get("tis_salary") is not None:
        if extraction["form16"]["gross_salary"] == extraction["form26as"]["tis_salary"]:
            checks_passed.append("Salary consistency")
        else:
            warnings.append("Gross salary differs between Form 16 and 26AS TIS")

    toi = extraction["form16"].get("tax_on_income") or 0
    sur = extraction["form16"].get("surcharge") or 0
    cess = extraction["form16"].get("health_edu_cess") or 0
    total = extraction["form16"].get("total_tax_payable")
    if total is not None:
        if toi + sur + cess == total:
            checks_passed.append("Tax arithmetic")
        else:
            errors.append("Tax computation does not add up")

    cess_expected = int(round((toi + sur) * 0.04)) if (toi + sur) > 0 else 0
    if extraction["form16"].get("health_edu_cess") is not None:
        if abs((extraction["form16"].get("health_edu_cess") or 0) - cess_expected) <= 2:
            checks_passed.append("Cess arithmetic")
        else:
            warnings.append("Cess amount may be incorrect")

    rel = extraction["form16"].get("relief_u89") or 0
    net = extraction["form16"].get("net_tax_payable")
    if total is not None and net is not None:
        if total - rel == net:
            checks_passed.append("Net tax cross-check")
        else:
            errors.append("Net tax payable mismatch")

    schedule_s = {
        "Salaries": extraction["form16"].get("gross_salary"),
        "ExemptAllowances": [],
        "DeductionUS16ia": extraction["form16"].get("standard_deduction"),
        "DeductionUS16iii": extraction["form16"].get("professional_tax"),
        "IncomeFromSalaries": extraction["form16"].get("net_salary"),
    }
    if extraction["form16"].get("hra_exempt") is not None:
        schedule_s["ExemptAllowances"].append(
            {"NatureDesc": "HRA", "SectionCode": "10(13A)", "Amount": extraction["form16"].get("hra_exempt")}
        )
    if extraction["form16"].get("lta_exempt") is not None:
        schedule_s["ExemptAllowances"].append(
            {"NatureDesc": "LTA", "SectionCode": "10(5)", "Amount": extraction["form16"].get("lta_exempt")}
        )

    tds_credit_total = salary_tds_sum
    adv_paid = extraction["form26as"].get("advance_tax_total") or 0
    sa_paid = extraction["form26as"].get("self_assessment_tax_total") or 0
    tax_due_value = ((total or 0) - tds_credit_total - adv_paid - sa_paid) if total is not None else None

    itr_mapped = {
        "PersonalInfo": {
            "PAN": extraction["form16"].get("employee_pan"),
            "AssesseeName": extraction["form16"].get("employee_name"),
            "AssessmentYear": extraction["form16"].get("assessment_year"),
        },
        "ScheduleS": schedule_s,
        "ScheduleVIA": {
            "DeductUndChapVIA": {
                "Section80C": extraction["form16"].get("deduction_80c"),
                "Section80D": extraction["form16"].get("deduction_80d"),
                "Section80CCD1B": extraction["form16"].get("deduction_80ccd1b"),
                "TotalChapVIADeductions": extraction["form16"].get("total_chapter_via"),
            }
        },
        "ScheduleTDS1": [
            {
                "EmployerOrDeductorOrCollectName": row.get("pa_deductor_name"),
                "TANOfEmployer": row.get("pa_deductor_tan"),
                "IncChrgSal": row.get("pa_amount_paid"),
                "TaxDeducted": row.get("pa_tds_deposited"),
            }
            for row in extraction["form26as"]["part_a"]
        ],
        "ScheduleTDS2": [
            {
                "DeductorName": row.get("pb_deductor_name"),
                "AmountPaid": row.get("pb_amount_paid"),
                "TaxDeducted": row.get("pb_tds_deposited"),
            }
            for row in extraction["form26as"]["part_b"]
        ],
        "ScheduleIT": [
            {
                "BSRCode": row.get("bsr_code"),
                "SrlNoOfChallan": row.get("challan_no"),
                "DateDep": row.get("date"),
                "Amt": row.get("amount"),
                "Tax": row.get("type"),
            }
            for row in extraction["form26as"]["challan_details"]
        ],
        "PartBTTI": {
            "TotalIncome": extraction["form16"].get("total_taxable_income"),
            "TaxPayable": extraction["form16"].get("tax_on_income"),
            "Surcharge": extraction["form16"].get("surcharge"),
            "EducationCess": extraction["form16"].get("health_edu_cess"),
            "TaxPayableOnTI": extraction["form16"].get("total_tax_payable"),
            "ReliefUS89": extraction["form16"].get("relief_u89"),
            "NetTaxPayable": extraction["form16"].get("net_tax_payable"),
            "TaxDue": (tax_due_value if tax_due_value > 0 else 0) if tax_due_value is not None else None,
            "Refund": {"RefundDue": (abs(tax_due_value) if tax_due_value < 0 else 0) if tax_due_value is not None else None},
        },
    }

    refund_or_demand = {
        "type": "REFUND" if (tax_due_value is not None and tax_due_value < 0) else "TAX_DUE",
        "amount": abs(tax_due_value) if tax_due_value is not None else 0,
    }

    return {
        "extraction": extraction,
        "itr_mapped": itr_mapped,
        "validation": {
            "checks_passed": checks_passed,
            "errors": errors,
            "warnings": warnings,
            "refund_or_demand": refund_or_demand,
        },
    }
