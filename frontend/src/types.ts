export interface User {
  id: string
  name: string
  email: string
  pan?: string
  language: string
}

export interface PrefilledTaxData {
  basic?: number
  hra_received?: number
  special_allowance?: number
  perquisites?: number
  profits_in_lieu?: number
  other_income?: number
  ltaExempt?: number
  otherSection10Exemptions?: number
  section80C?: number
  section80ccd1?: number
  medicalSelf?: number
  medicalFamily?: number
  nps?: number
  rentPaid?: number
  homeLoanInterest?: number
  savingsInterest?: number
  professionalTax?: number
  dividendIncome?: number
  capitalGainsStcgPre23Jul2024?: number
  capitalGainsStcgPost23Jul2024?: number
  electricVehicleLoanInterest80eeb?: number
}
