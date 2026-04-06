import { useState, useEffect, useCallback } from 'react'
import { DocumentUpload } from './DocumentUpload'
import type { PrefilledTaxData } from '../types'

const API_BASE = import.meta.env.VITE_API_URL || ''

type AnimState = 'idle' | 'greeting' | 'computing' | 'celebrating'

interface Props {
  prefill?: PrefilledTaxData | null
  onAnimationStateChange?: (state: AnimState) => void
  lang?: string
}


interface TaxResult {
  regime: string
  net_salary: number
  gross_total_income: number
  gross_income: number
  total_deductions: number
  taxable_income: number
  tax_before_rebate: number
  surcharge: number
  surcharge_rate_pct: number
  marginal_relief: number
  rebate_87a: number
  tax_after_rebate: number
  cess: number
  total_tax: number
  effective_rate_pct: number
  marginal_rate_pct: number
  surcharge_applies: boolean
  rebate_applies: boolean
  deduction_breakup: Array<{ section: string; amount: number; explanation: string; legal_reference: string; section_label?: string }>
  slab_breakup: Array<{ lower: number; upper: number; rate: number; taxable_at_rate: number; tax_amount: number }>
}

interface OptimizeResult {
  recommended_regime: string
  tax_old: number
  tax_new: number
  savings_if_switch: number
  result_old: TaxResult
  result_new: TaxResult
  suggested_investments: Array<{
    section: string
    current_claim: number
    max_deduction: number
    suggested_additional: number
    message: string
  }>
}

function normalizeTaxResult(data: TaxResult): TaxResult {
  return {
    ...data,
    deduction_breakup: Array.isArray(data?.deduction_breakup) ? data.deduction_breakup : [],
    slab_breakup: Array.isArray(data?.slab_breakup) ? data.slab_breakup : [],
  }
}

// ─── Insights engine ────────────────────────────────────────────────────────

type InsightPriority = 'high' | 'medium' | 'low' | 'info'
type InsightType = 'saving' | 'filing' | 'risk' | 'tip'

interface InsightItem {
  type: InsightType
  priority: InsightPriority
  icon: string
  title: string
  description: string
  impact?: string
  section?: string
}

interface FilingChecklist {
  form: string
  reason: string
  dueDate: string
  docs: string[]
}

function getTaxHealthScore(result: TaxResult, optResult: OptimizeResult): number {
  // Max possible deductions: 80C(1.5L) + NPS(50K) + 80D_self(25K) + 80D_parents(50K) + 24b(2L) + 80TTA(10K)
  const MAX_POSSIBLE = 150000 + 50000 + 25000 + 50000 + 200000 + 10000
  const deductionRatio = Math.min(1, result.total_deductions / MAX_POSSIBLE)
  const rateScore = Math.max(0, 1 - result.effective_rate_pct / 35)
  const regimePenalty = optResult.savings_if_switch > 5000 ? 0.85 : 1
  return Math.round((deductionRatio * 0.55 + rateScore * 0.45) * 100 * regimePenalty)
}

function generateInsights(
  result: TaxResult,
  optResult: OptimizeResult,
  deductions: { section80C: number; medicalSelf: number; medicalFamily: number; nps: number; ltaExempt: number; rentPaid: number; homeLoanInterest: number; savingsInterest: number; professionalTax: number },
  salary: { basic: number; hra_received: number; special_allowance: number; other_income: number },
  _metro: boolean,
): InsightItem[] {
  const insights: InsightItem[] = []

  // 1. Regime switch
  if (optResult.savings_if_switch > 2000) {
    const recName = optResult.recommended_regime === 'new' ? 'New Regime' : 'Old Regime'
    insights.push({
      type: 'saving', priority: 'high', icon: '💰', section: 'Regime',
      title: `Switch to ${recName} — Save ${fmt(optResult.savings_if_switch)}`,
      description: `The ${recName} is ₹${Math.round(optResult.savings_if_switch / 12).toLocaleString('en-IN')}/month cheaper for you. ${optResult.recommended_regime === 'new' ? 'New regime has lower slab rates.' : 'Old regime deductions outweigh the lower new-regime slabs for your profile.'}`,
      impact: `Save ${fmt(optResult.savings_if_switch)}/yr`,
    })
  }

  // 2. Investment gaps from the optimizer
  for (const s of optResult.suggested_investments) {
    const bracket = result.effective_rate_pct
    const estSaving = Math.round(s.suggested_additional * (bracket / 100))
    insights.push({
      type: 'saving',
      priority: s.suggested_additional >= 50000 ? 'high' : s.suggested_additional >= 20000 ? 'medium' : 'low',
      icon: '📈',
      section: s.section,
      title: `Maximize ${s.section} — Save ~${fmt(estSaving)}`,
      description: s.message,
      impact: `~${fmt(estSaving)} tax saved`,
    })
  }

  // 3. HRA received but no rent entered
  if (salary.hra_received > 0 && deductions.rentPaid === 0) {
    insights.push({
      type: 'risk', priority: 'high', icon: '⚠️', section: 'HRA',
      title: 'HRA Benefit Unclaimed — Enter Rent Paid',
      description: 'You receive HRA but haven\'t entered annual rent paid. If you pay rent, add it to unlock the HRA exemption — often ₹60,000–₹1,20,000 reduction in taxable income.',
    })
  }

  // 4. NPS underutilised
  const npsGap = 50000 - deductions.nps
  if (npsGap > 5000 && result.gross_income > 500000) {
    const saving = Math.round(npsGap * 0.20)
    insights.push({
      type: 'saving', priority: 'medium', icon: '🏦', section: '80CCD(1B)',
      title: `Top up NPS by ${fmt(npsGap)} — Extra ₹50K deduction`,
      description: `Section 80CCD(1B) allows ₹50,000 over and above 80C. You\'ve used only ${fmt(deductions.nps)}. Investing ${fmt(npsGap)} more can save you ~${fmt(saving)} in tax.`,
      impact: `~${fmt(saving)} tax saved`,
    })
  }

  // 5. Missing parent health insurance
  if (deductions.medicalFamily === 0) {
    insights.push({
      type: 'tip', priority: 'medium', icon: '❤️‍🩹', section: '80D',
      title: 'Insure Parents — Claim ₹25K–₹50K Under 80D',
      description: 'Parent health insurance premiums qualify for an additional deduction — ₹25,000 (parents < 60 yrs) or ₹50,000 (senior citizen parents) under Section 80D, separate from your own limit.',
    })
  }

  // 6. 87A check
  if (result.taxable_income > 0 && result.taxable_income <= 500000 && result.rebate_87a === 0 && result.regime === 'old') {
    insights.push({
      type: 'risk', priority: 'high', icon: '⚠️', section: '87A',
      title: 'Section 87A Rebate May Apply',
      description: 'Your taxable income is at or below ₹5L in the old regime, which qualifies for a full rebate of up to ₹12,500 under Section 87A. Verify that the backend has applied it.',
    })
  }

  // 7. Savings interest deduction
  if (deductions.savingsInterest === 0 && result.gross_income > 300000) {
    insights.push({
      type: 'tip', priority: 'low', icon: '🏧', section: '80TTA',
      title: 'Claim Savings Interest Deduction (80TTA)',
      description: 'Interest earned on savings bank accounts is deductible up to ₹10,000 under Section 80TTA. Check your bank statements and enter the amount to reduce your taxable income.',
    })
  }

  // 8. High effective rate tip
  if (result.effective_rate_pct > 18) {
    insights.push({
      type: 'tip', priority: 'low', icon: '📊', section: 'General',
      title: 'Effective Rate Above 18% — Room to Optimise',
      description: 'Your effective tax rate is relatively high. Consider ELSS funds, PPF top-up, NPS, and home loan restructuring to reduce your taxable income further.',
    })
  }

  return insights.sort((a, b) => {
    const order: Record<InsightPriority, number> = { high: 0, medium: 1, info: 2, low: 3 }
    return order[a.priority] - order[b.priority]
  })
}

function getFilingChecklist(
  salary: { basic: number; hra_received: number; other_income: number },
  result: TaxResult,
): FilingChecklist {
  const isSimple = salary.other_income < 5000 && result.gross_income <= 5000000
  return {
    form: isSimple ? 'ITR-1 (Sahaj)' : 'ITR-2',
    reason: isSimple
      ? 'Your income is from salary and interest only (≤ ₹50L)'
      : 'You have capital gains or income from multiple sources',
    dueDate: 'July 31, 2025 (AY 2025-26)',
    docs: [
      'Form 16 from employer',
      'Form 26AS & AIS (download from incometax.gov.in)',
      'Bank statements (savings interest)',
      ...(salary.hra_received > 0 ? ['Rent receipts & landlord PAN'] : []),
      ...(result.deduction_breakup.some(d => d.section.includes('24')) ? ['Home loan interest certificate'] : []),
      '80C investment proofs (ELSS, PPF passbook, LIC premium receipts)',
      ...(result.deduction_breakup.some(d => d.section.includes('80D')) ? ['Health insurance premium receipts'] : []),
      'NPS account statement (if applicable)',
    ],
  }
}

// ─── Translation map ────────────────────────────────────────────────────────
type TcT = {
  uploadTab: string; manualTab: string
  incomeTitle: string; incomeSub: string
  basicSalary: string; basicHint: string
  hra: string; hraHint: string
  specialAllowance: string
  otherIncome: string; otherHint: string
  deductionsTitle: string; deductionsSub: string
  sec80C: string; sec80CHint: string
  med80DSelf: string; med80DSelfHint: string
  med80DParents: string; med80DParentsHint: string
  nps: string; npsHint: string
  rentPaid: string; rentHint: string
  homeLoan: string; homeLoanHint: string
  savings: string; savingsHint: string
  profTax: string; profTaxHint: string
  optionsTitle: string
  metro: string; metroOn: string; metroOff: string
  regime: string; regimeAuto: string; regimeOld: string; regimeNew: string
  computeBtn: string; computing: string
  emptyState: string; computingState: string
  recommended: string; save: string; saveBySwitching: string
  tabSummary: string; tabBreakdown: string; tabOptimize: string
  grossIncome: string; totalDeductions: string; taxableIncome: string
  totalTax: string; effectiveRate: string; rebate87A: string; ifApplicable: string
  taxSteps: string; lessDeductions: string; taxSlabs: string
  lessRebate: string; lessCess: string; netTax: string
  oldRegime: string; newRegime: string
  deductionBreakup: string; noDeductions: string
  investSuggestions: string; maxDeductions: string; best: string
}

const TC_TEXT: Record<string, TcT> = {
  en: {
    uploadTab: 'Upload Documents', manualTab: 'Manual Entry',
    incomeTitle: 'Income from Salary (ITR)', incomeSub: 'Enter annual values as per Form 16 / ITR schedule',
    basicSalary: 'Basic salary (annual, for HRA formula)', basicHint: 'Enter annual basic salary only, not total salary u/s 17(1)',
    hra: 'HRA received', hraHint: 'Used to compute exemption u/s 10(13A)',
    specialAllowance: 'Taxable allowances (incl. special allowance)',
    otherIncome: 'Income from other sources', otherHint: 'Savings interest/other income taxable under OS',
    deductionsTitle: 'Deductions (Chapter VI-A / Salary)', deductionsSub: 'Enter claimable amounts using ITR terminology',
    sec80C: 'Section 80C', sec80CHint: 'LIC, PPF, EPF, ELSS etc. (max ₹1.5L)',
    med80DSelf: 'Section 80D (Self/Family)', med80DSelfHint: 'Medical insurance premium',
    med80DParents: 'Section 80D (Parents)', med80DParentsHint: "Parents' medical insurance premium",
    nps: 'Section 80CCD(1B) - NPS', npsHint: 'Additional NPS deduction (max ₹50K)',
    rentPaid: 'Annual rent paid', rentHint: 'For HRA exemption calculation',
    homeLoan: 'Interest on housing loan u/s 24(b)', homeLoanHint: 'Self-occupied house property interest (max ₹2L)',
    savings: 'Savings interest (for 80TTA)', savingsHint: 'Eligible deduction up to ₹10K',
    profTax: 'Professional tax u/s 16(iii)', profTaxHint: 'Tax paid to state government',
    optionsTitle: 'Options',
    metro: 'Metro city', metroOn: 'Mumbai / Delhi / Kolkata / Chennai', metroOff: 'Non-metro',
    regime: 'Regime', regimeAuto: 'Auto (Best)', regimeOld: 'Old', regimeNew: 'New',
    computeBtn: 'Compute Tax', computing: 'Computing…',
    emptyState: 'Fill in your income details and click Compute Tax to see results.',
    computingState: 'Computing your tax…',
    recommended: 'Recommended', save: 'Save', saveBySwitching: 'by switching to',
    tabSummary: '📊 Summary', tabBreakdown: '📋 Deductions', tabOptimize: '💡 Optimizer',
    grossIncome: 'Gross Income', totalDeductions: 'Total Deductions', taxableIncome: 'Taxable Income',
    totalTax: 'Total Tax', effectiveRate: 'Effective Rate', rebate87A: '87A Rebate', ifApplicable: 'if applicable',
    taxSteps: 'Tax Computation Steps', lessDeductions: 'Less: Deductions', taxSlabs: 'Tax (as per slabs)',
    lessRebate: 'Less: 87A Rebate', lessCess: 'Less: Cess (4%)', netTax: 'Net Tax Payable',
    oldRegime: 'Old Regime', newRegime: 'New Regime',
    deductionBreakup: 'Deduction Breakup', noDeductions: 'No deductions applied.',
    investSuggestions: 'Investment Suggestions', maxDeductions: '🎉 You are already maximising your deductions!', best: '✓ Best',
  },
  hi: {
    uploadTab: 'दस्तावेज़ अपलोड करें', manualTab: 'मैन्युअल प्रविष्टि',
    incomeTitle: 'आय विवरण', incomeSub: 'वार्षिक आंकड़े (INR में)',
    basicSalary: 'मूल वेतन', basicHint: 'वार्षिक मूल वेतन',
    hra: 'HRA प्राप्त', hraHint: 'मकान किराया भत्ता',
    specialAllowance: 'विशेष भत्ता',
    otherIncome: 'अन्य आय', otherHint: 'ब्याज, पूंजीगत लाभ आदि',
    deductionsTitle: 'कटौतियाँ', deductionsSub: 'धारावार वार्षिक निवेश व खर्च',
    sec80C: 'धारा 80C', sec80CHint: 'PF, LIC, ELSS, PPF (अधिकतम ₹1.5L)',
    med80DSelf: '80D — स्वयं व परिवार', med80DSelfHint: 'स्वास्थ्य बीमा प्रीमियम',
    med80DParents: '80D — माता-पिता', med80DParentsHint: 'माता-पिता का चिकित्सा बीमा',
    nps: 'NPS (80CCD)', npsHint: 'राष्ट्रीय पेंशन योजना (अतिरिक्त ₹50K)',
    rentPaid: 'चुकाया किराया', rentHint: 'HRA गणना हेतु वार्षिक किराया',
    homeLoan: 'गृह ऋण ब्याज', homeLoanHint: 'धारा 24(b) — अधिकतम ₹2L',
    savings: 'बचत ब्याज', savingsHint: '80TTA — अधिकतम ₹10K',
    profTax: 'व्यावसायिक कर', profTaxHint: 'राज्य सरकार को भुगतान',
    optionsTitle: 'विकल्प',
    metro: 'मेट्रो शहर', metroOn: 'मुंबई / दिल्ली / कोलकाता / चेन्नई', metroOff: 'गैर-मेट्रो',
    regime: 'कर व्यवस्था', regimeAuto: 'स्वचालित (सर्वोत्तम)', regimeOld: 'पुरानी', regimeNew: 'नई',
    computeBtn: 'कर की गणना करें', computing: 'गणना हो रही है…',
    emptyState: 'आय विवरण भरें और परिणाम देखने के लिए "कर की गणना करें" दबाएं।',
    computingState: 'आपका कर गणना हो रहा है…',
    recommended: 'अनुशंसित', save: 'बचाएं', saveBySwitching: 'में स्विच करने पर',
    tabSummary: '📊 सारांश', tabBreakdown: '📋 कटौतियाँ', tabOptimize: '💡 अनुकूलक',
    grossIncome: 'सकल आय', totalDeductions: 'कुल कटौती', taxableIncome: 'कर योग्य आय',
    totalTax: 'कुल कर', effectiveRate: 'प्रभावी दर', rebate87A: '87A छूट', ifApplicable: 'यदि लागू हो',
    taxSteps: 'कर गणना चरण', lessDeductions: 'घटाएं: कटौतियाँ', taxSlabs: 'कर (स्लैब अनुसार)',
    lessRebate: 'घटाएं: 87A छूट', lessCess: 'घटाएं: उपकर (4%)', netTax: 'देय शुद्ध कर',
    oldRegime: 'पुरानी कर व्यवस्था', newRegime: 'नई कर व्यवस्था',
    deductionBreakup: 'कटौती विवरण', noDeductions: 'कोई कटौती लागू नहीं।',
    investSuggestions: 'निवेश सुझाव', maxDeductions: '🎉 आप पहले से ही अधिकतम कटौती का लाभ उठा रहे हैं!', best: '✓ सर्वोत्तम',
  },
  ta: {
    uploadTab: 'ஆவணங்கள் பதிவேற்றவும்', manualTab: 'கை உள்ளீடு',
    incomeTitle: 'வருமான விவரங்கள்', incomeSub: 'ஆண்டு தொகை (INR)',
    basicSalary: 'அடிப்படை சம்பளம்', basicHint: 'ஆண்டு அடிப்படை ஊதியம்',
    hra: 'HRA பெற்றது', hraHint: 'வீட்டு வாடகை கொடுப்பனவு',
    specialAllowance: 'சிறப்பு கொடுப்பனவு',
    otherIncome: 'பிற வருமானம்', otherHint: 'வட்டி, மூலதன ஆதாயம் போன்றவை',
    deductionsTitle: 'விலக்குகள்', deductionsSub: 'பிரிவுவாரி ஆண்டு முதலீடுகள் & செலவுகள்',
    sec80C: 'பிரிவு 80C', sec80CHint: 'PF, LIC, ELSS, PPF (அதிகபட்சம் ₹1.5L)',
    med80DSelf: '80D — சொந்தம் & குடும்பம்', med80DSelfHint: 'உடல்நல காப்பீட்டு பிரீமியம்',
    med80DParents: '80D — பெற்றோர்', med80DParentsHint: 'பெற்றோர் மருத்துவ காப்பீடு',
    nps: 'NPS (80CCD)', npsHint: 'தேசிய ஓய்வூதிய திட்டம் (கூடுதல் ₹50K)',
    rentPaid: 'செலுத்திய வாடகை', rentHint: 'HRA கணக்கீட்டிற்கு ஆண்டு வாடகை',
    homeLoan: 'வீட்டுக்கடன் வட்டி', homeLoanHint: 'பிரிவு 24(b) — அதிகபட்சம் ₹2L',
    savings: 'சேமிப்பு வட்டி', savingsHint: '80TTA — அதிகபட்சம் ₹10K',
    profTax: 'தொழில் வரி', profTaxHint: 'மாநில அரசுக்கு செலுத்தியது',
    optionsTitle: 'விருப்பங்கள்',
    metro: 'மெட்ரோ நகரம்', metroOn: 'மும்பை / டெல்லி / கொல்கத்தா / சென்னை', metroOff: 'மெட்ரோ அல்லாத',
    regime: 'வரி முறை', regimeAuto: 'தானியங்கி (சிறந்தது)', regimeOld: 'பழைய', regimeNew: 'புதிய',
    computeBtn: 'வரி கணக்கிடு', computing: 'கணக்கிடுகிறேன்…',
    emptyState: 'வருமான விவரங்களை நிரப்பி "வரி கணக்கிடு" என்பதை கிளிக் செய்யுங்கள்.',
    computingState: 'உங்கள் வரி கணக்கிடப்படுகிறது…',
    recommended: 'பரிந்துரைக்கப்பட்டது', save: 'மிச்சப்படுத்துங்கள்', saveBySwitching: 'மாற்றுவதன் மூலம்',
    tabSummary: '📊 சுருக்கம்', tabBreakdown: '📋 விலக்குகள்', tabOptimize: '💡 மேம்படுத்தி',
    grossIncome: 'மொத்த வருமானம்', totalDeductions: 'மொத்த விலக்கு', taxableIncome: 'வரிக்குரிய வருமானம்',
    totalTax: 'மொத்த வரி', effectiveRate: 'செயல்திறன் விகிதம்', rebate87A: '87A தள்ளுபடி', ifApplicable: 'பொருந்தினால்',
    taxSteps: 'வரி கணக்கீட்டு படிகள்', lessDeductions: 'கழிக்கவும்: விலக்குகள்', taxSlabs: 'வரி (ஸ்லாப் படி)',
    lessRebate: 'கழிக்கவும்: 87A தள்ளுபடி', lessCess: 'கழிக்கவும்: செஸ் (4%)', netTax: 'செலுத்த வேண்டிய நிகர வரி',
    oldRegime: 'பழைய வரி முறை', newRegime: 'புதிய வரி முறை',
    deductionBreakup: 'விலக்கு விவரம்', noDeductions: 'விலக்குகள் எதுவும் பயன்படுத்தப்படவில்லை.',
    investSuggestions: 'முதலீட்டு பரிந்துரைகள்', maxDeductions: '🎉 நீங்கள் ஏற்கனவே அதிகபட்ச விலக்குகளை பெறுகிறீர்கள்!', best: '✓ சிறந்தது',
  },
  te: {
    uploadTab: 'పత్రాలు అప్‌లోడ్ చేయండి', manualTab: 'మాన్యువల్ ఎంట్రీ',
    incomeTitle: 'ఆదాయ వివరాలు', incomeSub: 'వార్షిక మొత్తాలు (INR)',
    basicSalary: 'మూల జీతం', basicHint: 'వార్షిక మూల వేతనం',
    hra: 'HRA వచ్చింది', hraHint: 'ఇంటి అద్దె భత్యం',
    specialAllowance: 'ప్రత్యేక భత్యం',
    otherIncome: 'ఇతర ఆదాయం', otherHint: 'వడ్డీ, మూలధన లాభాలు మొదలైనవి',
    deductionsTitle: 'మినహాయింపులు', deductionsSub: 'విభాగాల వారీ వార్షిక పెట్టుబడులు & ఖర్చులు',
    sec80C: 'సెక్షన్ 80C', sec80CHint: 'PF, LIC, ELSS, PPF (గరిష్టం ₹1.5L)',
    med80DSelf: '80D — స్వంతం & కుటుంబం', med80DSelfHint: 'ఆరోగ్య బీమా ప్రీమియం',
    med80DParents: '80D — తల్లిదండ్రులు', med80DParentsHint: 'తల్లిదండ్రుల వైద్య బీమా',
    nps: 'NPS (80CCD)', npsHint: 'జాతీయ పెన్షన్ పథకం (అదనంగా ₹50K)',
    rentPaid: 'చెల్లించిన అద్దె', rentHint: 'HRA లెక్కింపుకు వార్షిక అద్దె',
    homeLoan: 'గృహ రుణ వడ్డీ', homeLoanHint: 'సెక్షన్ 24(b) — గరిష్టం ₹2L',
    savings: 'సేవింగ్స్ వడ్డీ', savingsHint: '80TTA — గరిష్టం ₹10K',
    profTax: 'వృత్తి పన్ను', profTaxHint: 'రాష్ట్ర ప్రభుత్వానికి చెల్లింపు',
    optionsTitle: 'ఎంపికలు',
    metro: 'మెట్రో నగరం', metroOn: 'ముంబై / ఢిల్లీ / కోల్‌కతా / చెన్నై', metroOff: 'మెట్రో కాని',
    regime: 'పన్ను విధానం', regimeAuto: 'ఆటో (బెస్ట్)', regimeOld: 'పాత', regimeNew: 'కొత్త',
    computeBtn: 'పన్ను లెక్కించు', computing: 'లెక్కిస్తున్నాను…',
    emptyState: 'ఆదాయ వివరాలు నమోదు చేసి పన్ను లెక్కించు నొక్కండి.',
    computingState: 'మీ పన్ను లెక్కిస్తున్నాము…',
    recommended: 'సిఫార్సు చేయబడింది', save: 'ఆదా చేయండి', saveBySwitching: 'మారడం ద్వారా',
    tabSummary: '📊 సారాంశం', tabBreakdown: '📋 మినహాయింపులు', tabOptimize: '💡 అప్టిమైజర్',
    grossIncome: 'మొత్తం ఆదాయం', totalDeductions: 'మొత్తం మినహాయింపు', taxableIncome: 'పన్ను విధించదగిన ఆదాయం',
    totalTax: 'మొత్తం పన్ను', effectiveRate: 'ప్రభావవంతమైన రేటు', rebate87A: '87A రాయితీ', ifApplicable: 'వర్తిస్తే',
    taxSteps: 'పన్ను గణన దశలు', lessDeductions: 'తీసివేయి: మినహాయింపులు', taxSlabs: 'పన్ను (స్లాబ్‌ల ప్రకారం)',
    lessRebate: 'తీసివేయి: 87A రాయితీ', lessCess: 'తీసివేయి: సెస్ (4%)', netTax: 'చెల్లించవలసిన నికర పన్ను',
    oldRegime: 'పాత పన్ను విధానం', newRegime: 'కొత్త పన్ను విధానం',
    deductionBreakup: 'మినహాయింపు వివరాలు', noDeductions: 'ఎటువంటి మినహాయింపులు వర్తించలేదు.',
    investSuggestions: 'పెట్టుబడి సూచనలు', maxDeductions: '🎉 మీరు ఇప్పటికే గరిష్ట మినహాయింపులు పొందుతున్నారు!', best: '✓ బెస్ట్',
  },
  kn: {
    uploadTab: 'ದಾಖಲೆಗಳನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ', manualTab: 'ಕೈಯಿಂದ ನಮೂದಿಸಿ',
    incomeTitle: 'ಆದಾಯ ವಿವರಗಳು', incomeSub: 'ವಾರ್ಷಿಕ ಮೊತ್ತ (INR)',
    basicSalary: 'ಮೂಲ ವೇತನ', basicHint: 'ವಾರ್ಷಿಕ ಮೂಲ ವೇತನ',
    hra: 'HRA ಪಡೆದಿದೆ', hraHint: 'ಮನೆ ಬಾಡಿಗೆ ಭತ್ಯೆ',
    specialAllowance: 'ವಿಶೇಷ ಭತ್ಯೆ',
    otherIncome: 'ಇತರ ಆದಾಯ', otherHint: 'ಬಡ್ಡಿ, ಬಂಡವಾಳ ಲಾಭ ಇತ್ಯಾದಿ',
    deductionsTitle: 'ಕಡಿತಗಳು', deductionsSub: 'ವಿಭಾಗವಾರು ವಾರ್ಷಿಕ ಹೂಡಿಕೆ ಮತ್ತು ಖರ್ಚು',
    sec80C: 'ವಿಭಾಗ 80C', sec80CHint: 'PF, LIC, ELSS, PPF (ಗರಿಷ್ಠ ₹1.5L)',
    med80DSelf: '80D — ಸ್ವಂತ ಮತ್ತು ಕುಟುಂಬ', med80DSelfHint: 'ಆರೋಗ್ಯ ವಿಮಾ ಪ್ರೀಮಿಯಂ',
    med80DParents: '80D — ಪೋಷಕರು', med80DParentsHint: 'ಪೋಷಕರ ವೈದ್ಯಕೀಯ ವಿಮೆ',
    nps: 'NPS (80CCD)', npsHint: 'ರಾಷ್ಟ್ರೀಯ ಪಿಂಚಣಿ ಯೋಜನೆ (ಹೆಚ್ಚುವರಿ ₹50K)',
    rentPaid: 'ಪಾವತಿಸಿದ ಬಾಡಿಗೆ', rentHint: 'HRA ಲೆಕ್ಕಕ್ಕೆ ವಾರ್ಷಿಕ ಬಾಡಿಗೆ',
    homeLoan: 'ಗೃಹ ಸಾಲ ಬಡ್ಡಿ', homeLoanHint: 'ವಿಭಾಗ 24(b) — ಗರಿಷ್ಠ ₹2L',
    savings: 'ಉಳಿತಾಯ ಬಡ್ಡಿ', savingsHint: '80TTA — ಗರಿಷ್ಠ ₹10K',
    profTax: 'ವೃತ್ತಿ ತೆರಿಗೆ', profTaxHint: 'ರಾಜ್ಯ ಸರ್ಕಾರಕ್ಕೆ ಪಾವತಿ',
    optionsTitle: 'ಆಯ್ಕೆಗಳು',
    metro: 'ಮೆಟ್ರೋ ನಗರ', metroOn: 'ಮುಂಬೈ / ದೆಹಲಿ / ಕೋಲ್ಕತಾ / ಚೆನ್ನೈ', metroOff: 'ಮೆಟ್ರೋ ಅಲ್ಲದ',
    regime: 'ತೆರಿಗೆ ವ್ಯವಸ್ಥೆ', regimeAuto: 'ಸ್ವಯಂ (ಉತ್ತಮ)', regimeOld: 'ಹಳೆಯ', regimeNew: 'ಹೊಸ',
    computeBtn: 'ತೆರಿಗೆ ಲೆಕ್ಕಿಸಿ', computing: 'ಲೆಕ್ಕಿಸುತ್ತಿದ್ದೇನೆ…',
    emptyState: 'ಆದಾಯ ವಿವರ ತುಂಬಿ ತೆರಿಗೆ ಲೆಕ್ಕಿಸಿ ಕ್ಲಿಕ್ ಮಾಡಿ.',
    computingState: 'ನಿಮ್ಮ ತೆರಿಗೆ ಲೆಕ್ಕಿಸಲಾಗುತ್ತಿದೆ…',
    recommended: 'ಶಿಫಾರಸು ಮಾಡಲಾಗಿದೆ', save: 'ಉಳಿಸಬಹುದು', saveBySwitching: 'ಬದಲಾಯಿಸುವ ಮೂಲಕ',
    tabSummary: '📊 ಸಾರಾಂಶ', tabBreakdown: '📋 ಕಡಿತಗಳು', tabOptimize: '💡 ಆಪ್ಟಿಮೈಜರ್',
    grossIncome: 'ಒಟ್ಟು ಆದಾಯ', totalDeductions: 'ಒಟ್ಟು ಕಡಿತ', taxableIncome: 'ತೆರಿಗೆ ವಿಧಿಸಬಹುದಾದ ಆದಾಯ',
    totalTax: 'ಒಟ್ಟು ತೆರಿಗೆ', effectiveRate: 'ಪರಿಣಾಮಕಾರಿ ದರ', rebate87A: '87A ರಿಯಾಯಿತಿ', ifApplicable: 'ಅನ್ವಯಿಸಿದರೆ',
    taxSteps: 'ತೆರಿಗೆ ಗಣನಾ ಹಂತಗಳು', lessDeductions: 'ಕಳೆಯಿರಿ: ಕಡಿತಗಳು', taxSlabs: 'ತೆರಿಗೆ (ಸ್ಲ್ಯಾಬ್ ಪ್ರಕಾರ)',
    lessRebate: 'ಕಳೆಯಿರಿ: 87A ರಿಯಾಯಿತಿ', lessCess: 'ಕಳೆಯಿರಿ: ಸೆಸ್ (4%)', netTax: 'ಪಾವತಿಸಬೇಕಾದ ನಿವ್ವಳ ತೆರಿಗೆ',
    oldRegime: 'ಹಳೆಯ ತೆರಿಗೆ ವ್ಯವಸ್ಥೆ', newRegime: 'ಹೊಸ ತೆರಿಗೆ ವ್ಯವಸ್ಥೆ',
    deductionBreakup: 'ಕಡಿತ ವಿವರ', noDeductions: 'ಯಾವುದೇ ಕಡಿತ ಅನ್ವಯಿಸಿಲ್ಲ.',
    investSuggestions: 'ಹೂಡಿಕೆ ಸಲಹೆಗಳು', maxDeductions: '🎉 ನೀವು ಈಗಾಗಲೇ ಗರಿಷ್ಠ ಕಡಿತ ಪಡೆಯುತ್ತಿದ್ದೀರಿ!', best: '✓ ಉತ್ತಮ',
  },
  ml: {
    uploadTab: 'ഡോക്യുമെന്റ് അപ്‌ലോഡ് ചെയ്യൂ', manualTab: 'മാനുവൽ എൻട്രി',
    incomeTitle: 'വരുമാന വിവരങ്ങൾ', incomeSub: 'വാർഷിക തുക (INR)',
    basicSalary: 'അടിസ്ഥാന ശമ്പളം', basicHint: 'വാർഷിക അടിസ്ഥാന ശമ്പളം',
    hra: 'HRA ലഭിച്ചത്', hraHint: 'വീട് വാടക ഭത്യം',
    specialAllowance: 'പ്രത്യേക ഭത്യം',
    otherIncome: 'മറ്റ് വരുമാനം', otherHint: 'പലിശ, മൂലധന നേട്ടം തുടങ്ങിയവ',
    deductionsTitle: 'കിഴിവുകൾ', deductionsSub: 'വകുപ്പ് തിരിച്ചുള്ള വാർഷിക നിക്ഷേപങ്ങൾ & ചെലവ്',
    sec80C: 'സെക്ഷൻ 80C', sec80CHint: 'PF, LIC, ELSS, PPF (പരമാവധി ₹1.5L)',
    med80DSelf: '80D — സ്വന്തം & കുടുംബം', med80DSelfHint: 'ആരോഗ്യ ഇൻഷുറൻസ് പ്രീമിയം',
    med80DParents: '80D — മാതാപിതാക്കൾ', med80DParentsHint: 'മാതാപിതാക്കളുടെ വൈദ്യ ഇൻഷുറൻസ്',
    nps: 'NPS (80CCD)', npsHint: 'ദേശീയ പെൻഷൻ പദ്ധതി (അധിക ₹50K)',
    rentPaid: 'അടച്ച വാടക', rentHint: 'HRA കണക്കിന് വാർഷിക വാടക',
    homeLoan: 'ഭവന വായ്പ പലിശ', homeLoanHint: 'സെക്ഷൻ 24(b) — പരമാവധി ₹2L',
    savings: 'സേവിംഗ്സ് പലിശ', savingsHint: '80TTA — പരമാവധി ₹10K',
    profTax: 'പ്രൊഫഷണൽ ടാക്സ്', profTaxHint: 'സംസ്ഥാന സർക്കാരിന് അടച്ചത്',
    optionsTitle: 'ഓപ്ഷനുകൾ',
    metro: 'മെട്രോ നഗരം', metroOn: 'മുംബൈ / ഡൽഹി / കൊൽക്കത്ത / ചെന്നൈ', metroOff: 'മെട്രോ അല്ലാത്ത',
    regime: 'നികുതി സമ്പ്രദായം', regimeAuto: 'ഓട്ടോ (മികച്ചത്)', regimeOld: 'പഴയ', regimeNew: 'പുതിയ',
    computeBtn: 'നികുതി കണക്കാക്കൂ', computing: 'കണക്കാക്കുന്നു…',
    emptyState: 'വരുമാന വിവരങ്ങൾ നൽകി നികുതി കണക്കാക്കൂ ക്ലിക്ക് ചെയ്യൂ.',
    computingState: 'നിങ്ങളുടെ നികുതി കണക്കാക്കുന്നു…',
    recommended: 'ശുപാർശ ചെയ്തത്', save: 'ലാഭിക്കാം', saveBySwitching: 'മാറ്റുന്നതിലൂടെ',
    tabSummary: '📊 സംഗ്രഹം', tabBreakdown: '📋 കിഴിവുകൾ', tabOptimize: '💡 ഒപ്റ്റിമൈസർ',
    grossIncome: 'മൊത്ത വരുമാനം', totalDeductions: 'മൊത്തം കിഴിവ്', taxableIncome: 'നികുതി വിധേയ വരുമാനം',
    totalTax: 'ആകെ നികുതി', effectiveRate: 'ഫലപ്രദ നിരക്ക്', rebate87A: '87A റിബേറ്റ്', ifApplicable: 'ബാധകമെങ്കിൽ',
    taxSteps: 'നികുതി കണക്കുകൂട്ടൽ ഘട്ടങ്ങൾ', lessDeductions: 'കുറയ്ക്കുക: കിഴിവുകൾ', taxSlabs: 'നികുതി (സ്ലാബ് അനുസരിച്ച്)',
    lessRebate: 'കുറയ്ക്കുക: 87A റിബേറ്റ്', lessCess: 'കുറയ്ക്കുക: സെസ് (4%)', netTax: 'അടക്കേണ്ട അറ്റ നികുതി',
    oldRegime: 'പഴയ നികുതി സമ്പ്രദായം', newRegime: 'പുതിയ നികുതി സമ്പ്രദായം',
    deductionBreakup: 'കിഴിവ് വിവരം', noDeductions: 'കിഴിവുകൾ ഒന്നും ബാധകമല്ല.',
    investSuggestions: 'നിക്ഷേപ നിർദ്ദേശങ്ങൾ', maxDeductions: '🎉 നിങ്ങൾ ഇതിനകം പരമാവധി കിഴിവുകൾ നേടുന്നുണ്ട്!', best: '✓ മികച്ചത്',
  },
  bn: {
    uploadTab: 'নথি আপলোড করুন', manualTab: 'ম্যানুয়াল এন্ট্রি',
    incomeTitle: 'আয়ের বিবরণ', incomeSub: 'বার্ষিক পরিমাণ (INR)',
    basicSalary: 'মূল বেতন', basicHint: 'বার্ষিক মূল বেতন',
    hra: 'HRA প্রাপ্ত', hraHint: 'বাড়ি ভাড়া ভাতা',
    specialAllowance: 'বিশেষ ভাতা',
    otherIncome: 'অন্যান্য আয়', otherHint: 'সুদ, মূলধনী লাভ ইত্যাদি',
    deductionsTitle: 'ছাড়সমূহ', deductionsSub: 'ধারা অনুযায়ী বার্ষিক বিনিয়োগ ও ব্যয়',
    sec80C: 'ধারা 80C', sec80CHint: 'PF, LIC, ELSS, PPF (সর্বোচ্চ ₹1.5L)',
    med80DSelf: '80D — নিজে ও পরিবার', med80DSelfHint: 'স্বাস্থ্য বিমা প্রিমিয়াম',
    med80DParents: '80D — অভিভাবক', med80DParentsHint: 'অভিভাবকদের চিকিৎসা বিমা',
    nps: 'NPS (80CCD)', npsHint: 'জাতীয় পেনশন প্রকল্প (অতিরিক্ত ₹50K)',
    rentPaid: 'পরিশোধিত ভাড়া', rentHint: 'HRA গণনায় বার্ষিক ভাড়া',
    homeLoan: 'গৃহঋণ সুদ', homeLoanHint: 'ধারা 24(b) — সর্বোচ্চ ₹2L',
    savings: 'সঞ্চয় সুদ', savingsHint: '80TTA — সর্বোচ্চ ₹10K',
    profTax: 'পেশাদার কর', profTaxHint: 'রাজ্য সরকারকে প্রদত্ত',
    optionsTitle: 'বিকল্প',
    metro: 'মেট্রো শহর', metroOn: 'মুম্বাই / দিল্লি / কলকাতা / চেন্নাই', metroOff: 'নন-মেট্রো',
    regime: 'কর ব্যবস্থা', regimeAuto: 'স্বয়ংক্রিয় (সেরা)', regimeOld: 'পুরনো', regimeNew: 'নতুন',
    computeBtn: 'কর গণনা করুন', computing: 'গণনা হচ্ছে…',
    emptyState: 'আয়ের বিবরণ পূরণ করুন এবং "কর গণনা করুন" ক্লিক করুন।',
    computingState: 'আপনার কর গণনা করা হচ্ছে…',
    recommended: 'প্রস্তাবিত', save: 'সাশ্রয় করুন', saveBySwitching: 'পরিবর্তন করে',
    tabSummary: '📊 সারাংশ', tabBreakdown: '📋 ছাড়সমূহ', tabOptimize: '💡 অপ্টিমাইজার',
    grossIncome: 'মোট আয়', totalDeductions: 'মোট ছাড়', taxableIncome: 'করযোগ্য আয়',
    totalTax: 'মোট কর', effectiveRate: 'কার্যকর হার', rebate87A: '87A ছাড়', ifApplicable: 'প্রযোজ্য হলে',
    taxSteps: 'কর গণনার ধাপ', lessDeductions: 'বিয়োগ: ছাড়সমূহ', taxSlabs: 'কর (স্ল্যাব অনুযায়ী)',
    lessRebate: 'বিয়োগ: 87A ছাড়', lessCess: 'বিয়োগ: সেস (4%)', netTax: 'পরিশোধযোগ্য নেট কর',
    oldRegime: 'পুরনো কর ব্যবস্থা', newRegime: 'নতুন কর ব্যবস্থা',
    deductionBreakup: 'ছাড়ের বিবরণ', noDeductions: 'কোনো ছাড় প্রযোজ্য নয়।',
    investSuggestions: 'বিনিয়োগ পরামর্শ', maxDeductions: '🎉 আপনি ইতিমধ্যে সর্বোচ্চ ছাড় পাচ্ছেন!', best: '✓ সেরা',
  },
  mr: {
    uploadTab: 'कागदपत्रे अपलोड करा', manualTab: 'मॅन्युअल एंट्री',
    incomeTitle: 'उत्पन्न तपशील', incomeSub: 'वार्षिक आकडे (INR)',
    basicSalary: 'मूळ पगार', basicHint: 'वार्षिक मूळ वेतन',
    hra: 'HRA मिळाले', hraHint: 'घर भाडे भत्ता',
    specialAllowance: 'विशेष भत्ता',
    otherIncome: 'इतर उत्पन्न', otherHint: 'व्याज, भांडवली नफा इ.',
    deductionsTitle: 'कपाती', deductionsSub: 'कलमवार वार्षिक गुंतवणूक व खर्च',
    sec80C: 'कलम 80C', sec80CHint: 'PF, LIC, ELSS, PPF (कमाल ₹1.5L)',
    med80DSelf: '80D — स्वतः व कुटुंब', med80DSelfHint: 'आरोग्य विमा प्रीमियम',
    med80DParents: '80D — पालक', med80DParentsHint: 'पालकांचा वैद्यकीय विमा',
    nps: 'NPS (80CCD)', npsHint: 'राष्ट्रीय पेन्शन योजना (अतिरिक्त ₹50K)',
    rentPaid: 'भरलेले भाडे', rentHint: 'HRA गणनेसाठी वार्षिक भाडे',
    homeLoan: 'गृहकर्ज व्याज', homeLoanHint: 'कलम 24(b) — कमाल ₹2L',
    savings: 'बचत व्याज', savingsHint: '80TTA — कमाल ₹10K',
    profTax: 'व्यावसायिक कर', profTaxHint: 'राज्य सरकारला भरलेला',
    optionsTitle: 'पर्याय',
    metro: 'मेट्रो शहर', metroOn: 'मुंबई / दिल्ली / कोलकाता / चेन्नई', metroOff: 'बिगर-मेट्रो',
    regime: 'कर व्यवस्था', regimeAuto: 'ऑटो (सर्वोत्तम)', regimeOld: 'जुनी', regimeNew: 'नवीन',
    computeBtn: 'कर मोजा', computing: 'मोजत आहे…',
    emptyState: 'उत्पन्न तपशील भरा आणि "कर मोजा" दाबा.',
    computingState: 'तुमचा कर मोजला जात आहे…',
    recommended: 'शिफारस केलेले', save: 'बचत करा', saveBySwitching: 'बदलून',
    tabSummary: '📊 सारांश', tabBreakdown: '📋 कपाती', tabOptimize: '💡 ऑप्टिमायझर',
    grossIncome: 'एकूण उत्पन्न', totalDeductions: 'एकूण कपात', taxableIncome: 'करपात्र उत्पन्न',
    totalTax: 'एकूण कर', effectiveRate: 'प्रभावी दर', rebate87A: '87A सूट', ifApplicable: 'लागू असल्यास',
    taxSteps: 'कर गणना टप्पे', lessDeductions: 'वजा: कपाती', taxSlabs: 'कर (स्लॅबनुसार)',
    lessRebate: 'वजा: 87A सूट', lessCess: 'वजा: उपकर (4%)', netTax: 'देय निव्वळ कर',
    oldRegime: 'जुनी कर व्यवस्था', newRegime: 'नवीन कर व्यवस्था',
    deductionBreakup: 'कपात तपशील', noDeductions: 'कोणत्याही कपाती लागू नाहीत.',
    investSuggestions: 'गुंतवणूक सूचना', maxDeductions: '🎉 तुम्ही आधीच जास्तीत जास्त कपात घेत आहात!', best: '✓ सर्वोत्तम',
  },
  gu: {
    uploadTab: 'દસ્તાવેજ અપલોડ કરો', manualTab: 'મેન્યુઅલ એન્ટ્રી',
    incomeTitle: 'આવક વિગતો', incomeSub: 'વાર્ષિક આંકડા (INR)',
    basicSalary: 'મૂળ પગાર', basicHint: 'વાર્ષિક મૂળ વેતન',
    hra: 'HRA મળ્યું', hraHint: 'ઘર ભાડા ભથ્થું',
    specialAllowance: 'વિશેષ ભથ્થું',
    otherIncome: 'અન્ય આવક', otherHint: 'વ્યાજ, મૂડી નફો વગેરે',
    deductionsTitle: 'કપાત', deductionsSub: 'કલમ મુજબ વાર્ષિક રોકાણ અને ખર્ચ',
    sec80C: 'કલમ 80C', sec80CHint: 'PF, LIC, ELSS, PPF (મહત્તમ ₹1.5L)',
    med80DSelf: '80D — સ્વ અને પરિવાર', med80DSelfHint: 'સ્વાસ્થ્ય વીમા પ્રીમિયમ',
    med80DParents: '80D — માતાપિતા', med80DParentsHint: 'માતાપિતાનો તબીબી વીમો',
    nps: 'NPS (80CCD)', npsHint: 'રાષ્ટ્રીય પેન્શન યોજના (વધારાના ₹50K)',
    rentPaid: 'ભરેલ ભાડું', rentHint: 'HRA ગણતરી માટે વાર્ષિક ભાડું',
    homeLoan: 'ઘર લોન વ્યાજ', homeLoanHint: 'કલમ 24(b) — મહત્તમ ₹2L',
    savings: 'બચત વ્યાજ', savingsHint: '80TTA — મહત્તમ ₹10K',
    profTax: 'વ્યવસાયિક કર', profTaxHint: 'રાજ્ય સરકારને ભરેલ',
    optionsTitle: 'વિકલ્પ',
    metro: 'મેટ્રો શહેર', metroOn: 'મુંબઈ / દિલ્હી / કોલ્કાતા / ચેન્નઈ', metroOff: 'નોન-મેટ્રો',
    regime: 'કર વ્યવસ્થા', regimeAuto: 'ઓટો (શ્રેષ્ઠ)', regimeOld: 'જૂની', regimeNew: 'નવી',
    computeBtn: 'કર ગણો', computing: 'ગણના ચાલ…',
    emptyState: 'આવક વિગત ભરો અને "કર ગણો" ક્લિક કરો.',
    computingState: 'તમારો કર ગણવામાં આવી રહ્યો છે…',
    recommended: 'ભલામણ', save: 'બચત', saveBySwitching: 'બદલવા પર',
    tabSummary: '📊 સારાંશ', tabBreakdown: '📋 કપાત', tabOptimize: '💡 ઓપ્ટિમાઈઝર',
    grossIncome: 'કુલ આવક', totalDeductions: 'કુલ કપાત', taxableIncome: 'કરપાત્ર આવક',
    totalTax: 'કુલ કર', effectiveRate: 'અસરકારક દર', rebate87A: '87A છૂટ', ifApplicable: 'લાગુ પડે તો',
    taxSteps: 'કર ગણનાના તબક્કા', lessDeductions: 'ઘટાઓ: કપાત', taxSlabs: 'કર (સ્લેબ મુજબ)',
    lessRebate: 'ઘટાઓ: 87A છૂટ', lessCess: 'ઘટાઓ: સેસ (4%)', netTax: 'ભરવાપાત્ર ચોખ્ખો કર',
    oldRegime: 'જૂની કર વ્યવસ્થા', newRegime: 'નવી કર વ્યવસ્થા',
    deductionBreakup: 'કપાત વિગત', noDeductions: 'કોઈ કપાત લાગુ નથી.',
    investSuggestions: 'રોકાણ સૂચનો', maxDeductions: '🎉 તમે પહેલેથી જ મહત્તમ કપાત મેળવી રહ્યા છો!', best: '✓ શ્રેષ્ઠ',
  },
  pa: {
    uploadTab: 'ਦਸਤਾਵੇਜ਼ ਅਪਲੋਡ ਕਰੋ', manualTab: 'ਮੈਨੂਅਲ ਐਂਟਰੀ',
    incomeTitle: 'ਆਮਦਨ ਵੇਰਵੇ', incomeSub: 'ਸਾਲਾਨਾ ਰਕਮ (INR)',
    basicSalary: 'ਮੂਲ ਤਨਖ਼ਾਹ', basicHint: 'ਸਾਲਾਨਾ ਮੂਲ ਤਨਖ਼ਾਹ',
    hra: 'HRA ਪ੍ਰਾਪਤ', hraHint: 'ਮਕਾਨ ਕਿਰਾਇਆ ਭੱਤਾ',
    specialAllowance: 'ਵਿਸ਼ੇਸ਼ ਭੱਤਾ',
    otherIncome: 'ਹੋਰ ਆਮਦਨ', otherHint: 'ਵਿਆਜ, ਪੂੰਜੀ ਲਾਭ ਆਦਿ',
    deductionsTitle: 'ਕਟੌਤੀਆਂ', deductionsSub: 'ਧਾਰਾਵਾਰ ਸਾਲਾਨਾ ਨਿਵੇਸ਼ ਅਤੇ ਖਰਚੇ',
    sec80C: 'ਧਾਰਾ 80C', sec80CHint: 'PF, LIC, ELSS, PPF (ਵੱਧ ਤੋਂ ਵੱਧ ₹1.5L)',
    med80DSelf: '80D — ਆਪਣੇ ਅਤੇ ਪਰਿਵਾਰ', med80DSelfHint: 'ਸਿਹਤ ਬੀਮਾ ਪ੍ਰੀਮੀਅਮ',
    med80DParents: '80D — ਮਾਤਾ-ਪਿਤਾ', med80DParentsHint: 'ਮਾਤਾ-ਪਿਤਾ ਦਾ ਡਾਕਟਰੀ ਬੀਮਾ',
    nps: 'NPS (80CCD)', npsHint: 'ਰਾਸ਼ਟਰੀ ਪੈਨਸ਼ਨ ਯੋਜਨਾ (ਵਾਧੂ ₹50K)',
    rentPaid: 'ਅਦਾ ਕੀਤਾ ਕਿਰਾਇਆ', rentHint: 'HRA ਗਣਨਾ ਲਈ ਸਾਲਾਨਾ ਕਿਰਾਇਆ',
    homeLoan: 'ਘਰ ਕਰਜ਼ਾ ਵਿਆਜ', homeLoanHint: 'ਧਾਰਾ 24(b) — ਵੱਧ ਤੋਂ ਵੱਧ ₹2L',
    savings: 'ਬੱਚਤ ਵਿਆਜ', savingsHint: '80TTA — ਵੱਧ ਤੋਂ ਵੱਧ ₹10K',
    profTax: 'ਪੇਸ਼ੇਵਰ ਕਰ', profTaxHint: 'ਰਾਜ ਸਰਕਾਰ ਨੂੰ ਅਦਾਇਗੀ',
    optionsTitle: 'ਵਿਕਲਪ',
    metro: 'ਮੈਟਰੋ ਸ਼ਹਿਰ', metroOn: 'ਮੁੰਬਈ / ਦਿੱਲੀ / ਕੋਲਕਾਤਾ / ਚੇਨੱਈ', metroOff: 'ਗੈਰ-ਮੈਟਰੋ',
    regime: 'ਕਰ ਵਿਵਸਥਾ', regimeAuto: 'ਆਟੋ (ਸਰਵੋਤਮ)', regimeOld: 'ਪੁਰਾਣੀ', regimeNew: 'ਨਵੀਂ',
    computeBtn: 'ਕਰ ਦੀ ਗਣਨਾ ਕਰੋ', computing: 'ਗਣਨਾ ਹੋ ਰਹੀ ਹੈ…',
    emptyState: 'ਆਮਦਨ ਵੇਰਵੇ ਭਰੋ ਅਤੇ "ਕਰ ਦੀ ਗਣਨਾ ਕਰੋ" ਦਬਾਓ।',
    computingState: 'ਤੁਹਾਡੇ ਕਰ ਦੀ ਗਣਨਾ ਹੋ ਰਹੀ ਹੈ…',
    recommended: 'ਸਿਫ਼ਾਰਸ਼ੀ', save: 'ਬਚਾਓ', saveBySwitching: 'ਬਦਲਣ ਨਾਲ',
    tabSummary: '📊 ਸਾਰਾਂਸ਼', tabBreakdown: '📋 ਕਟੌਤੀਆਂ', tabOptimize: '💡 ਆਪਟੀਮਾਈਜ਼ਰ',
    grossIncome: 'ਕੁੱਲ ਆਮਦਨ', totalDeductions: 'ਕੁੱਲ ਕਟੌਤੀ', taxableIncome: 'ਕਰਯੋਗ ਆਮਦਨ',
    totalTax: 'ਕੁੱਲ ਕਰ', effectiveRate: 'ਪ੍ਰਭਾਵੀ ਦਰ', rebate87A: '87A ਛੋਟ', ifApplicable: 'ਜੇ ਲਾਗੂ ਹੋਵੇ',
    taxSteps: 'ਕਰ ਗਣਨਾ ਕਦਮ', lessDeductions: 'ਘਟਾਓ: ਕਟੌਤੀਆਂ', taxSlabs: 'ਕਰ (ਸਲੈਬ ਅਨੁਸਾਰ)',
    lessRebate: 'ਘਟਾਓ: 87A ਛੋਟ', lessCess: 'ਘਟਾਓ: ਸੈੱਸ (4%)', netTax: 'ਦੇਣਯੋਗ ਕੁੱਲ ਕਰ',
    oldRegime: 'ਪੁਰਾਣੀ ਕਰ ਵਿਵਸਥਾ', newRegime: 'ਨਵੀਂ ਕਰ ਵਿਵਸਥਾ',
    deductionBreakup: 'ਕਟੌਤੀ ਵੇਰਵਾ', noDeductions: 'ਕੋਈ ਕਟੌਤੀ ਲਾਗੂ ਨਹੀਂ।',
    investSuggestions: 'ਨਿਵੇਸ਼ ਸੁਝਾਅ', maxDeductions: '🎉 ਤੁਸੀਂ ਪਹਿਲਾਂ ਹੀ ਵੱਧ ਤੋਂ ਵੱਧ ਕਟੌਤੀਆਂ ਲੈ ਰਹੇ ਹੋ!', best: '✓ ਸਰਵੋਤਮ',
  },
}

const TC_LANG_FALLBACK: Record<string, keyof typeof TC_TEXT> = {
  en: 'en',
  hi: 'hi',
  ta: 'ta',
  te: 'te',
  kn: 'kn',
  ml: 'ml',
  bn: 'bn',
  mr: 'mr',
  gu: 'gu',
  pa: 'pa',
  or: 'bn',
  as: 'bn',
  ur: 'hi',
  ks: 'hi',
  mai: 'hi',
  mni: 'bn',
  ne: 'hi',
  sa: 'hi',
  sd: 'hi',
  kok: 'mr',
  doi: 'hi',
  sat: 'bn',
}
// ────────────────────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 })

const fmtPct = (n: number) => n.toFixed(2) + '%'

function StatCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className={`stat-card${accent ? ' stat-card--accent' : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

function sumDeductionByPredicate(
  items: Array<{ section: string; amount: number }>,
  predicate: (section: string) => boolean,
): number {
  return items
    .filter((item) => predicate(item.section || ''))
    .reduce((sum, item) => sum + (Number(item.amount) || 0), 0)
}

function isExemptionSection(section: string): boolean {
  const normalized = (section || '').toUpperCase()
  return normalized === 'HRA' || normalized.includes('LTA') || normalized.includes('10(5)')
}

function deductionDisplayLabel(item: { section: string; section_label?: string }): string {
  const section = item.section || ''
  if (section === 'standard_deduction') return 'Less: Standard deduction'
  if (section === 'professional_tax') return 'Less: Professional tax'
  if (section === '80D') return 'Less: Section 80D (self/family + parents)'
  if (section === '80C') return 'Less: Section 80C'
  if (section.includes('80CCD')) return 'Less: Section 80CCD(1B) - NPS'
  if (section === '24(b)') return 'Less: Interest on housing loan u/s 24(b)'
  if (section === '80TTA') return 'Less: Section 80TTA'
  return `Less: ${item.section_label || section}`
}

function slabRangeLabel(lower: number, upper: number): string {
  if (!Number.isFinite(upper) || upper <= 0) return `${fmt(lower)} and above`
  return `${fmt(lower)} to ${fmt(upper)}`
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="form-section-header">
      <h3>{title}</h3>
      {subtitle && <p>{subtitle}</p>}
    </div>
  )
}

function Field({
  label, name, value, onChange, hint, prefix = '₹', min = 0, disabled = false, allowNegative = false
}: {
  label: string; name: string; value: number; onChange: (name: string, val: number) => void;
  hint?: string; prefix?: string; min?: number; disabled?: boolean; allowNegative?: boolean
}) {
  const displayValue = value === 0 ? '' : new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value)

  const handleInputChange = (raw: string) => {
    const cleaned = raw.replace(/,/g, '')
    const normalized = allowNegative
      ? cleaned.replace(/(?!^)-/g, '').replace(/[^\d.-]/g, '')
      : cleaned.replace(/[^\d.]/g, '')
    const numericValue = Number(normalized)
    onChange(name, Number.isFinite(numericValue) ? numericValue : 0)
  }

  return (
    <div className="field">
      <label htmlFor={name}>{label}</label>
      <div className="field-input-wrap">
        <span className="field-prefix">{prefix}</span>
        <input
          id={name}
          type="text"
          inputMode="decimal"
          min={min}
          value={displayValue}
          placeholder="0"
          disabled={disabled}
          onChange={(e) => handleInputChange(e.target.value)}
        />
      </div>
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  )
}

export function TaxCalculator({ prefill, onAnimationStateChange, lang }: Props) {
  const requestedLang = (lang || 'en').toLowerCase()
  const resolvedLang = TC_LANG_FALLBACK[requestedLang] || 'en'
  const t = TC_TEXT[resolvedLang] ?? TC_TEXT.en
  const [salary, setSalary] = useState({ basic: 0, hra_received: 0, special_allowance: 0, perquisites: 0, profits_in_lieu: 0, other_income: 0 })
  const [deductions, setDeductions] = useState({
    section80C: 0, medicalSelf: 0, medicalFamily: 0, nps: 0,
    section80ccd1: 0, employerNps: 0, educationLoanInterest: 0, electricVehicleLoanInterest: 0, donation80G50: 0, donation80G100: 0,
    ltaExempt: 0, rentPaid: 0, rent80GG: 0, homeLoanInterest: 0, savingsInterest: 0, professionalTax: 0,
    otherSection10Exemptions: 0,
  })
  const [incomeHeads, setIncomeHeads] = useState({
    housePropertyIncome: 0,
    businessIncome: 0,
    otherSourcesIncome: 0,
    dividendIncome: 0,
    capitalGainsStcg: 0,
    capitalGainsStcgPre23Jul2024: 0,
    capitalGainsStcgPost23Jul2024: 0,
    capitalGainsLtcg: 0,
  })
  const [taxProfile, setTaxProfile] = useState({ selfIsSenior: false, parentsAreSenior: false, claim80GG: false })
  const [inputMode, setInputMode] = useState<'upload' | 'manual'>('upload')

  useEffect(() => {
    if (!prefill) return
    setSalary(() => ({
      basic: prefill.basic ?? 0,
      hra_received: prefill.hra_received ?? 0,
      special_allowance: prefill.special_allowance ?? 0,
      perquisites: prefill.perquisites ?? 0,
      profits_in_lieu: prefill.profits_in_lieu ?? 0,
      other_income: prefill.other_income ?? 0,
    }))
    setDeductions(d => ({
      ...d,
      section80C: prefill.section80C ?? 0,
      section80ccd1: prefill.section80ccd1 ?? 0,
      medicalSelf: prefill.medicalSelf ?? 0,
      medicalFamily: prefill.medicalFamily ?? 0,
      nps: prefill.nps ?? 0,
      ltaExempt: prefill.ltaExempt ?? 0,
      rentPaid: prefill.rentPaid ?? 0,
      homeLoanInterest: prefill.homeLoanInterest ?? 0,
      savingsInterest: prefill.savingsInterest ?? 0,
      professionalTax: prefill.professionalTax ?? 0,
      electricVehicleLoanInterest: prefill.electricVehicleLoanInterest80eeb ?? 0,
      otherSection10Exemptions: prefill.otherSection10Exemptions ?? 0,
    }))
    setIncomeHeads(i => ({
      ...i,
      dividendIncome: prefill.dividendIncome ?? 0,
      capitalGainsStcgPre23Jul2024: prefill.capitalGainsStcgPre23Jul2024 ?? 0,
      capitalGainsStcgPost23Jul2024: prefill.capitalGainsStcgPost23Jul2024 ?? 0,
    }))
    setInputMode('manual')
  }, [prefill])
  const [metro, setMetro] = useState(false)
  const [regime, setRegime] = useState<'old' | 'new' | 'auto'>('auto')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<TaxResult | null>(null)
  const [optResult, setOptResult] = useState<OptimizeResult | null>(null)
  const [activeResultTab, setActiveResultTab] = useState<'summary' | 'breakdown' | 'optimize' | 'insights'>('summary')
  const [summaryRegimeTab, setSummaryRegimeTab] = useState<'old' | 'new'>('new')

  const resetManualValuesToZero = useCallback(() => {
    setSalary({
      basic: 0,
      hra_received: 0,
      special_allowance: 0,
      perquisites: 0,
      profits_in_lieu: 0,
      other_income: 0,
    })
    setDeductions({
      section80C: 0,
      medicalSelf: 0,
      medicalFamily: 0,
      nps: 0,
      section80ccd1: 0,
      employerNps: 0,
      educationLoanInterest: 0,
      electricVehicleLoanInterest: 0,
      donation80G50: 0,
      donation80G100: 0,
      ltaExempt: 0,
      rentPaid: 0,
      rent80GG: 0,
      homeLoanInterest: 0,
      savingsInterest: 0,
      professionalTax: 0,
      otherSection10Exemptions: 0,
    })
    setIncomeHeads({
      housePropertyIncome: 0,
      businessIncome: 0,
      otherSourcesIncome: 0,
      dividendIncome: 0,
      capitalGainsStcg: 0,
      capitalGainsStcgPre23Jul2024: 0,
      capitalGainsStcgPost23Jul2024: 0,
      capitalGainsLtcg: 0,
    })
    setTaxProfile({ selfIsSenior: false, parentsAreSenior: false, claim80GG: false })
    setError(null)
  }, [])

  const updateSalary = (name: string, val: number) => setSalary(s => ({ ...s, [name]: val }))
  const updateDeductions = (name: string, val: number) => setDeductions(d => ({ ...d, [name]: val }))
  const updateIncomeHeads = (name: string, val: number) => setIncomeHeads(s => ({ ...s, [name]: val }))

  const self80DLimit = taxProfile.selfIsSenior ? 50000 : 25000
  const parent80DLimit = taxProfile.parentsAreSenior ? 50000 : 25000
  const oldOnlyEntriesPresent = deductions.section80C > 0 || deductions.section80ccd1 > 0 || deductions.medicalSelf > 0 || deductions.medicalFamily > 0 || deductions.nps > 0 || deductions.ltaExempt > 0 || deductions.rentPaid > 0 || deductions.rent80GG > 0 || deductions.homeLoanInterest > 0 || deductions.savingsInterest > 0 || deductions.educationLoanInterest > 0 || deductions.electricVehicleLoanInterest > 0 || deductions.donation80G50 > 0 || deductions.donation80G100 > 0 || deductions.professionalTax > 0 || taxProfile.claim80GG
  const validationMessages = [
    ...((deductions.section80C + deductions.section80ccd1) > 150000 ? ['Section 80C + 80CCD(1) cannot exceed ₹1,50,000.'] : []),
    ...(deductions.medicalSelf > self80DLimit ? [`Section 80D self/family cannot exceed ${fmt(self80DLimit)}.`] : []),
    ...(deductions.medicalFamily > parent80DLimit ? [`Section 80D parents cannot exceed ${fmt(parent80DLimit)}.`] : []),
    ...(deductions.nps > 50000 ? ['Section 80CCD(1B) cannot exceed ₹50,000.'] : []),
    ...(deductions.ltaExempt > 0 && deductions.ltaExempt > salary.hra_received + salary.basic + salary.special_allowance ? ['LTA exemption looks unusually high compared to salary components.'] : []),
  ]

  const buildPayload = () => ({
    salary: {
      basic: salary.basic,
      hra_received: salary.hra_received,
      special_allowance: salary.special_allowance,
      perquisites: salary.perquisites,
      profits_in_lieu: salary.profits_in_lieu,
      other_income: salary.other_income,
    },
    investments: {
      '80C': [
        ...(deductions.section80C > 0 ? [{ amount: deductions.section80C }] : []),
        ...(deductions.section80ccd1 > 0 ? [{ amount: deductions.section80ccd1 }] : []),
      ],
      '80D': {
        self_family: deductions.medicalSelf,
        parents: deductions.medicalFamily,
      },
      nps: deductions.nps,
    },
    section_80ccd1: deductions.section80ccd1,
    rent_paid: deductions.rentPaid,
    lta_exempt: deductions.ltaExempt,
    other_section10_exemptions: deductions.otherSection10Exemptions,
    home_loan_interest: deductions.homeLoanInterest,
    savings_interest: deductions.savingsInterest,
    house_property_income: incomeHeads.housePropertyIncome,
    business_income: incomeHeads.businessIncome,
    other_sources_income: incomeHeads.otherSourcesIncome,
    dividend_income: incomeHeads.dividendIncome,
    capital_gains_stcg: incomeHeads.capitalGainsStcg,
    capital_gains_stcg_pre_23_jul_2024: incomeHeads.capitalGainsStcgPre23Jul2024,
    capital_gains_stcg_post_23_jul_2024: incomeHeads.capitalGainsStcgPost23Jul2024,
    capital_gains_ltcg: incomeHeads.capitalGainsLtcg,
    employer_nps_80ccd2: deductions.employerNps,
    education_loan_interest_80e: deductions.educationLoanInterest,
    electric_vehicle_loan_interest_80eeb: deductions.electricVehicleLoanInterest,
    donation_80g_50: deductions.donation80G50,
    donation_80g_100: deductions.donation80G100,
    rent_paid_80gg: deductions.rent80GG,
    claim_80gg: taxProfile.claim80GG,
    self_is_senior: taxProfile.selfIsSenior,
    parents_are_senior: taxProfile.parentsAreSenior,
    professional_tax_paid: deductions.professionalTax,
    metro,
  })

  const notifyAnim = useCallback((s: AnimState) => {
    if (onAnimationStateChange) onAnimationStateChange(s)
  }, [onAnimationStateChange])

  const compute = async () => {
    if (validationMessages.length) {
      setError(validationMessages[0])
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    setOptResult(null)
    notifyAnim('computing')
    try {
      const payload = buildPayload()
      const [computeRes, optimizeRes] = await Promise.all([
        fetch(`${API_BASE}/api/compute-tax`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, regime: regime === 'auto' ? undefined : regime }),
        }),
        fetch(`${API_BASE}/api/optimize-tax`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }),
      ])
      if (!computeRes.ok || !optimizeRes.ok) throw new Error('Server error')
      const [computeData, optimizeData] = await Promise.all([computeRes.json(), optimizeRes.json()])
      const safeCompute = normalizeTaxResult(computeData)
      const safeOptimize: OptimizeResult = {
        ...optimizeData,
        result_old: normalizeTaxResult(optimizeData.result_old),
        result_new: normalizeTaxResult(optimizeData.result_new),
      }
      setResult(safeCompute)
      setOptResult(safeOptimize)
      setSummaryRegimeTab(safeOptimize.recommended_regime === 'old' ? 'old' : 'new')
      setActiveResultTab('summary')
      window.dispatchEvent(new CustomEvent('taxai:filing_recorded', {
        detail: {
          record: {
            id: crypto.randomUUID(),
            title: `Tax computation (${safeOptimize.recommended_regime === 'new' ? 'New' : 'Old'} regime recommended)`,
            filedAt: new Date().toISOString(),
          },
        },
      }))
      notifyAnim('celebrating')
      setTimeout(() => notifyAnim('idle'), 3000)
    } catch (e) {
      setError((e as Error).message || 'Failed to compute tax. Make sure the backend is running.')
      notifyAnim('idle')
    } finally {
      setLoading(false)
    }
  }

  const regimeTag = (r: string) => r === 'new' ? t.newRegime : t.oldRegime

  const downloadResultJson = () => {
    if (!result || !optResult) return

    const exportPayload = {
      generated_at: new Date().toISOString(),
      input: {
        salary,
        deductions,
        metro,
        regime,
      },
      compute_result: result,
      optimize_result: optResult,
    }

    const blob = new Blob([JSON.stringify(exportPayload, null, 2)], { type: 'application/json' })
    const fileUrl = URL.createObjectURL(blob)
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const link = document.createElement('a')
    link.href = fileUrl
    link.download = `tax-calculation-${timestamp}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(fileUrl)
  }

  return (
    <div className="tax-calc-layout">
      {/* ─── Left: Input Form ─── */}
      <div className="tax-form">
        <div className="tax-form-inner">

          {/* Input mode toggle */}
          <div className="input-mode-toggle">
            <button
              className={`imt-btn${inputMode === 'upload' ? ' active' : ''}`}
              onClick={() => setInputMode('upload')}
              type="button"
            >
              <svg className="icon-inline" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="12" y1="18" x2="12" y2="12" />
                <line x1="9" y1="15" x2="15" y2="15" />
              </svg>
              Upload Documents
            </button>
            <button
              className={`imt-btn${inputMode === 'manual' ? ' active' : ''}`}
              onClick={() => setInputMode('manual')}
              type="button"
            >
              <svg className="icon-inline" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
              {t.manualTab}
            </button>
          </div>

          <div className="tax-entry-panel">
          {inputMode === 'upload' && (
            <div className="tax-entry-body tax-entry-body--upload">
              <DocumentUpload onPrefill={data => {
                setSalary(() => ({
                  basic: data.basic ?? 0,
                  hra_received: data.hra_received ?? 0,
                  special_allowance: data.special_allowance ?? 0,
                  perquisites: data.perquisites ?? 0,
                  profits_in_lieu: data.profits_in_lieu ?? 0,
                  other_income: data.other_income ?? 0,
                }))
                setDeductions(d => ({
                  ...d,
                  // Reset omitted OCR fields to avoid stale values from prior uploads.
                  section80C: data.section80C ?? 0,
                  section80ccd1: data.section80ccd1 ?? 0,
                  medicalSelf: data.medicalSelf ?? 0,
                  medicalFamily: data.medicalFamily ?? 0,
                  nps: data.nps ?? 0,
                  ltaExempt: data.ltaExempt ?? 0,
                  otherSection10Exemptions: data.otherSection10Exemptions ?? 0,
                  rentPaid: data.rentPaid ?? 0,
                  homeLoanInterest: data.homeLoanInterest ?? 0,
                  savingsInterest: data.savingsInterest ?? 0,
                  professionalTax: data.professionalTax ?? 0,
                  electricVehicleLoanInterest: data.electricVehicleLoanInterest80eeb ?? 0,
                }))
                setIncomeHeads(i => ({
                  ...i,
                  dividendIncome: data.dividendIncome ?? 0,
                  capitalGainsStcgPre23Jul2024: data.capitalGainsStcgPre23Jul2024 ?? 0,
                  capitalGainsStcgPost23Jul2024: data.capitalGainsStcgPost23Jul2024 ?? 0,
                }))
                setInputMode('manual')
              }} />
            </div>
          )}

          {inputMode === 'manual' && (
            <div className="tax-entry-body tax-entry-body--manual">
              <div className="manual-reset-row">
                <button type="button" className="manual-reset-btn" onClick={resetManualValuesToZero}>
                  Reset
                </button>
              </div>

              {/* Income */}
              <SectionHeader title={t.incomeTitle} subtitle={t.incomeSub} />
              <div className="fields-grid">
                <Field label={t.basicSalary} name="basic" value={salary.basic} onChange={updateSalary} hint={t.basicHint} />
                <Field label={t.hra} name="hra_received" value={salary.hra_received} onChange={updateSalary} hint={t.hraHint} />
                <Field label="Perquisites u/s 17(2)" name="perquisites" value={salary.perquisites} onChange={updateSalary} hint="Taxable salary perquisites" />
                <Field label="Profits in lieu u/s 17(3)" name="profits_in_lieu" value={salary.profits_in_lieu} onChange={updateSalary} hint="Taxable salary income" />
                <Field label="LTA exemption u/s 10(5)" name="ltaExempt" value={deductions.ltaExempt} onChange={updateDeductions} hint="Old Regime only" />
                <Field label="Other Section 10 exemptions" name="otherSection10Exemptions" value={deductions.otherSection10Exemptions} onChange={updateDeductions} hint="Old Regime salary exemptions" />
                <Field label={t.specialAllowance} name="special_allowance" value={salary.special_allowance} onChange={updateSalary} />
                <Field label={t.otherIncome} name="other_income" value={salary.other_income} onChange={updateSalary} hint={t.otherHint} />
              </div>

              <div className="divider" />

              {/* Deductions */}
              <SectionHeader title={t.deductionsTitle} subtitle={t.deductionsSub} />
              <div className="fields-grid">
                <Field label={t.sec80C} name="section80C" value={deductions.section80C} onChange={updateDeductions} hint={t.sec80CHint} />
                <Field label="80CCD(1) (within 80C)" name="section80ccd1" value={deductions.section80ccd1} onChange={updateDeductions} hint="Counts toward the 80C limit" />
                <Field label={t.med80DSelf} name="medicalSelf" value={deductions.medicalSelf} onChange={updateDeductions} hint={t.med80DSelfHint} />
                <Field label={t.med80DParents} name="medicalFamily" value={deductions.medicalFamily} onChange={updateDeductions} hint={t.med80DParentsHint} />
                <Field label={t.nps} name="nps" value={deductions.nps} onChange={updateDeductions} hint={t.npsHint} />
                <Field label="Employer NPS 80CCD(2)" name="employerNps" value={deductions.employerNps} onChange={updateDeductions} hint="Allowed in New Regime" />
                <Field label="EV loan interest (80EEB)" name="electricVehicleLoanInterest" value={deductions.electricVehicleLoanInterest} onChange={updateDeductions} hint="Old Regime only" />
                <Field label={t.rentPaid} name="rentPaid" value={deductions.rentPaid} onChange={updateDeductions} hint={t.rentHint} />
                <Field label="Rent for 80GG" name="rent80GG" value={deductions.rent80GG} onChange={updateDeductions} hint="Use only if HRA not received" />
                <Field label={t.homeLoan} name="homeLoanInterest" value={deductions.homeLoanInterest} onChange={updateDeductions} hint={t.homeLoanHint} />
                <Field label={t.savings} name="savingsInterest" value={deductions.savingsInterest} onChange={updateDeductions} hint={t.savingsHint} />
                <Field label="Education loan interest (80E)" name="educationLoanInterest" value={deductions.educationLoanInterest} onChange={updateDeductions} hint="Old Regime only" />
                <Field label="Donations 80G (50%)" name="donation80G50" value={deductions.donation80G50} onChange={updateDeductions} hint="Old Regime only" />
                <Field label="Donations 80G (100%)" name="donation80G100" value={deductions.donation80G100} onChange={updateDeductions} hint="Old Regime only" />
                <Field label={t.profTax} name="professionalTax" value={deductions.professionalTax} onChange={updateDeductions} hint={t.profTaxHint} />
              </div>

              <div className="divider" />

              <SectionHeader title="Other Income Heads" subtitle="Separate heads used for compliance-aware computation" />
              <div className="fields-grid">
                <Field label="House property income / loss" name="housePropertyIncome" value={incomeHeads.housePropertyIncome} onChange={updateIncomeHeads} hint="Use negative for loss" allowNegative />
                <Field label="Business / profession income" name="businessIncome" value={incomeHeads.businessIncome} onChange={updateIncomeHeads} hint="If applicable" />
                <Field label="Other sources income" name="otherSourcesIncome" value={incomeHeads.otherSourcesIncome} onChange={updateIncomeHeads} hint="FD interest, dividends, etc." />
                <Field label="Dividend income" name="dividendIncome" value={incomeHeads.dividendIncome} onChange={updateIncomeHeads} hint="Report separately" />
                <Field label="Capital gains - STCG" name="capitalGainsStcg" value={incomeHeads.capitalGainsStcg} onChange={updateIncomeHeads} hint="Special rate bucket" />
                <Field label="STCG before 23 Jul 2024" name="capitalGainsStcgPre23Jul2024" value={incomeHeads.capitalGainsStcgPre23Jul2024} onChange={updateIncomeHeads} hint="ITR-2 split bucket" />
                <Field label="STCG on/after 23 Jul 2024" name="capitalGainsStcgPost23Jul2024" value={incomeHeads.capitalGainsStcgPost23Jul2024} onChange={updateIncomeHeads} hint="ITR-2 split bucket" />
                <Field label="Capital gains - LTCG" name="capitalGainsLtcg" value={incomeHeads.capitalGainsLtcg} onChange={updateIncomeHeads} hint="12.5% above ₹1L threshold" />
              </div>

              <div className="fields-grid">
                <label className="toggle-wrap"><span>Self is senior citizen (60+)</span><button type="button" className={`toggle${taxProfile.selfIsSenior ? ' on' : ''}`} onClick={() => setTaxProfile(v => ({ ...v, selfIsSenior: !v.selfIsSenior }))}><span className="toggle-thumb" /></button></label>
                <label className="toggle-wrap"><span>Parents are senior citizens</span><button type="button" className={`toggle${taxProfile.parentsAreSenior ? ' on' : ''}`} onClick={() => setTaxProfile(v => ({ ...v, parentsAreSenior: !v.parentsAreSenior }))}><span className="toggle-thumb" /></button></label>
                <label className="toggle-wrap"><span>Claim 80GG (no HRA)</span><button type="button" className={`toggle${taxProfile.claim80GG ? ' on' : ''}`} onClick={() => setTaxProfile(v => ({ ...v, claim80GG: !v.claim80GG }))}><span className="toggle-thumb" /></button></label>
              </div>

              <div className="divider" />
            </div>
          )}
          </div>

          {/* Options */}
          <SectionHeader title={t.optionsTitle} />
          <div className="options-row">
            <label className="toggle-wrap">
              <span>{t.metro}</span>
              <button
                type="button"
                className={`toggle${metro ? ' on' : ''}`}
                onClick={() => setMetro(v => !v)}
              >
                <span className="toggle-thumb" />
              </button>
              <span className="field-hint">{metro ? t.metroOn : t.metroOff}</span>
            </label>
            <div className="regime-select">
              <span>{t.regime}</span>
              <div className="seg-ctrl">
                {(['auto', 'old', 'new'] as const).map(r => (
                  <button key={r} type="button" className={regime === r ? 'active' : ''} onClick={() => setRegime(r)}>
                    {r === 'auto' ? t.regimeAuto : r === 'old' ? t.regimeOld : t.regimeNew}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <button className="compute-btn" onClick={compute} disabled={loading}>
            {loading ? <><span className="spinner" /> {t.computing}</> : (
              <>
                <svg className="icon-inline icon-inline--lg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="1" y1="1" x2="5" y2="5" />
                  <path d="M8 2a6 6 0 1 1 0 12A6 6 0 0 1 8 2Z" />
                  <line x1="18" y1="18" x2="23" y2="23" />
                </svg>
                {t.computeBtn}
              </>
            )}
          </button>

          {regime === 'new' && oldOnlyEntriesPresent && (
            <div className="error-banner">Old Regime-only exemptions/deductions are ignored in the selected New Regime computation, but still used for comparison.</div>
          )}

          {error && <div className="error-banner">{error}</div>}
        </div>
      </div>

      {/* ─── Right: Results ─── */}
      <div className="results-pane">
        {!result && !loading && (
          <div className="results-empty">
            <svg viewBox="0 0 80 80" width="64" height="64"><circle cx="40" cy="40" r="36" fill="var(--surface-alt)" /><text x="40" y="48" textAnchor="middle" fontSize="28" fill="var(--accent)">₹</text></svg>
            <p>{t.emptyState}</p>
          </div>
        )}
        {loading && (
          <div className="results-empty">
            <div className="loader-ring" />
            <p>{t.computingState}</p>
          </div>
        )}
        {result && optResult && (
          <>
            {/* Regime recommendation banner */}
            <div className={`regime-banner${optResult.recommended_regime === 'new' ? ' new' : ' old'}`}>
              <span className="regime-badge">{regimeTag(optResult.recommended_regime)} {t.recommended}</span>
              {optResult.savings_if_switch > 0 && (
                <span>{t.save} <strong>{fmt(optResult.savings_if_switch)}</strong> {t.saveBySwitching} {regimeTag(optResult.recommended_regime)}</span>
              )}
            </div>

            <div className="result-actions">
              <button type="button" className="download-json-btn" onClick={downloadResultJson}>
                ⬇ Download JSON
              </button>
            </div>

            {/* Result tabs */}
            <div className="result-tabs">
              {(['summary', 'breakdown', 'optimize', 'insights'] as const).map(tab => (
                <button key={tab} className={activeResultTab === tab ? 'active' : ''} onClick={() => setActiveResultTab(tab)}>
                  {tab === 'summary' ? t.tabSummary : tab === 'breakdown' ? t.tabBreakdown : tab === 'optimize' ? t.tabOptimize : '🔍 Insights'}
                </button>
              ))}
            </div>

            {activeResultTab === 'summary' && (
              <div className="result-section">
                {(() => {
                  const summaryRegimeResult = summaryRegimeTab === 'old' ? optResult.result_old : optResult.result_new
                  const summaryBars = [
                    { key: 'income', label: t.grossIncome, value: summaryRegimeResult.gross_income, colorClass: 'income' },
                    { key: 'deductions', label: t.totalDeductions, value: summaryRegimeResult.total_deductions, colorClass: 'deductions' },
                    { key: 'taxable', label: t.taxableIncome, value: summaryRegimeResult.taxable_income, colorClass: 'taxable' },
                    { key: 'tax', label: t.totalTax, value: summaryRegimeResult.total_tax, colorClass: 'tax' },
                  ] as const
                  const maxSummaryMetric = Math.max(...summaryBars.map(item => item.value), 1)
                  const hraExemption = sumDeductionByPredicate(summaryRegimeResult.deduction_breakup, (section) => section === 'HRA')
                  const ltaExemption = sumDeductionByPredicate(summaryRegimeResult.deduction_breakup, (section) => section.includes('10(5)') || section.toUpperCase().includes('LTA'))
                  const otherDeductionItems = summaryRegimeResult.deduction_breakup.filter((item) => !isExemptionSection(item.section || ''))
                  return (
                    <>
                <div className="regime-summary-shell">
                  <div className="regime-summary-tabs">
                    {(['new', 'old'] as const).map((r) => (
                      <button
                        key={r}
                        type="button"
                        className={`regime-summary-tab${summaryRegimeTab === r ? ' active' : ''}`}
                        onClick={() => setSummaryRegimeTab(r)}
                      >
                        {regimeTag(r)}
                        {optResult.recommended_regime === r && <span className="regime-summary-rec">{t.recommended}</span>}
                      </button>
                    ))}
                  </div>
                  <div className="regime-summary-content">
                    <div className="regime-summary-chart" role="img" aria-label={`${regimeTag(summaryRegimeTab)} income, deductions and tax chart`}>
                      <div className="regime-summary-bars">
                        {summaryBars.map((metric) => {
                          const barHeight = Math.max(0, (metric.value / maxSummaryMetric) * 100)
                          const barHeightStep = metric.value <= 0 ? 0 : Math.max(10, Math.min(100, Math.round(barHeight / 10) * 10))
                          return (
                            <div key={metric.key} className="regime-summary-bar-col">
                              <span className="regime-summary-bar-value">{fmt(metric.value)}</span>
                              <div className="regime-summary-bar-track">
                                <div className={`regime-summary-bar regime-summary-bar--${metric.colorClass} regime-summary-bar-h--${barHeightStep}`} />
                              </div>
                              <span className="regime-summary-bar-label">{metric.label}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>

                    <div className="regime-summary-cards">
                      <div className="regime-summary-card">
                        <span>{t.grossIncome}</span>
                        <strong>{fmt(summaryRegimeResult.gross_income)}</strong>
                      </div>
                      <div className="regime-summary-card">
                        <span>{t.taxableIncome}</span>
                        <strong>{fmt(summaryRegimeResult.taxable_income)}</strong>
                      </div>
                      <div className="regime-summary-card">
                        <span>{t.totalDeductions}</span>
                        <strong>{fmt(summaryRegimeResult.total_deductions)}</strong>
                      </div>
                      <div className="regime-summary-card regime-summary-card--tax">
                        <span>{t.totalTax}</span>
                        <strong>{fmt(summaryRegimeResult.total_tax)}</strong>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="stat-grid">
                  <StatCard label="Net Salary" value={fmt(summaryRegimeResult.net_salary)} />
                  <StatCard label="Gross Total Income" value={fmt(summaryRegimeResult.gross_total_income)} />
                  <StatCard label={t.grossIncome} value={fmt(summaryRegimeResult.gross_income)} />
                  <StatCard label={t.totalDeductions} value={fmt(summaryRegimeResult.total_deductions)} />
                  <StatCard label={t.taxableIncome} value={fmt(summaryRegimeResult.taxable_income)} />
                  <StatCard label={t.totalTax} value={fmt(summaryRegimeResult.total_tax)} accent />
                  <StatCard label={`${t.oldRegime} Tax`} value={fmt(optResult.tax_old)} sub={optResult.recommended_regime === 'old' ? t.best : 'Alternative'} />
                  <StatCard label={`${t.newRegime} Tax`} value={fmt(optResult.tax_new)} sub={optResult.recommended_regime === 'new' ? t.best : 'Alternative'} />
                  <StatCard label={t.effectiveRate} value={fmtPct(summaryRegimeResult.effective_rate_pct)} sub={regimeTag(summaryRegimeResult.regime)} />
                  <StatCard label={t.rebate87A} value={fmt(summaryRegimeResult.rebate_87a)} sub={t.ifApplicable} />
                  <StatCard label="Marginal Rate" value={fmtPct(summaryRegimeResult.marginal_rate_pct)} />
                </div>
                <div className="tax-breakdown-table">
                  <h4>{t.taxSteps}</h4>
                  <table>
                    <tbody>
                      <tr><td>{t.grossIncome}</td><td>{fmt(summaryRegimeResult.gross_income)}</td></tr>
                      {hraExemption > 0 && <tr><td>Less: HRA exemption (u/s 10(13A))</td><td>− {fmt(hraExemption)}</td></tr>}
                      {ltaExemption > 0 && <tr><td>Less: LTA exemption (u/s 10(5))</td><td>− {fmt(ltaExemption)}</td></tr>}
                      {otherDeductionItems.map((item, idx) => (
                        <tr key={`${item.section}-${idx}`}><td>{deductionDisplayLabel(item)}</td><td>− {fmt(item.amount)}</td></tr>
                      ))}
                      <tr className="total-row"><td>Net Salary / GTI after deductions</td><td>{fmt(summaryRegimeResult.gross_total_income - (incomeHeads.capitalGainsStcg + incomeHeads.capitalGainsStcgPre23Jul2024 + incomeHeads.capitalGainsStcgPost23Jul2024 + incomeHeads.capitalGainsLtcg))}</td></tr>
                      <tr className="total-row"><td>{t.taxableIncome}</td><td>{fmt(summaryRegimeResult.taxable_income)}</td></tr>
                      <tr><td>{t.taxSlabs}</td><td>{fmt(summaryRegimeResult.tax_before_rebate)}</td></tr>
                      {(summaryRegimeResult.slab_breakup ?? []).map((slab, idx) => (
                        <tr key={`slab-${idx}`}>
                          <td>• {slabRangeLabel(slab.lower, slab.upper)} @ {(slab.rate * 100).toFixed(0)}% on {fmt(slab.taxable_at_rate)}</td>
                          <td>{fmt(slab.tax_amount)}</td>
                        </tr>
                      ))}
                      {summaryRegimeResult.surcharge_applies && <tr><td>Surcharge ({summaryRegimeResult.surcharge_rate_pct.toFixed(2)}%)</td><td>{fmt(summaryRegimeResult.surcharge)}</td></tr>}
                      {summaryRegimeResult.marginal_relief > 0 && <tr><td>Less: Marginal relief</td><td>− {fmt(summaryRegimeResult.marginal_relief)}</td></tr>}
                      <tr><td>{t.lessRebate}</td><td>− {fmt(summaryRegimeResult.rebate_87a)}</td></tr>
                      <tr><td>{t.lessCess}</td><td>{fmt(summaryRegimeResult.cess)}</td></tr>
                      <tr className="total-row highlight"><td>{t.netTax}</td><td>{fmt(summaryRegimeResult.total_tax)}</td></tr>
                    </tbody>
                  </table>
                </div>
                <div className="muted-text muted-text--spaced">
                  {summaryRegimeResult.surcharge_applies ? 'Surcharge applies for this income level.' : 'No surcharge applies.'} {' '}
                  {summaryRegimeResult.rebate_applies ? '87A rebate applied.' : '87A rebate not applicable.'}
                </div>
                {/* Regime comparison mini */}
                {(() => {
                  const oldResult = optResult.result_old
                  const newResult = optResult.result_new
                  const maxTax = Math.max(optResult.tax_old, optResult.tax_new, 1)
                  const oldBarPct = Math.max(8, (optResult.tax_old / maxTax) * 100)
                  const newBarPct = Math.max(8, (optResult.tax_new / maxTax) * 100)
                  const savingsAbs = Math.max(0, Math.abs(optResult.tax_old - optResult.tax_new))
                  const otherTax = optResult.recommended_regime === 'old' ? optResult.tax_new : optResult.tax_old
                  const savingsPct = otherTax > 0 ? Math.min(100, Math.round((savingsAbs / otherTax) * 100)) : 0

                  return (
                    <div className="regime-compare-mini">
                      <div className="regime-compare-graph" role="img" aria-label="Visual tax comparison between old and new regimes">
                        <div className="regime-bar-row">
                          <span className="regime-bar-label">{t.oldRegime}</span>
                          <div className="regime-bar-track">
                            <svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
                              <rect x="0" y="0" width="100" height="10" className="regime-bar-bg" />
                              <rect x="0" y="0" width={oldBarPct} height="10" className="regime-bar-fill regime-bar-fill--old" />
                            </svg>
                          </div>
                          <span className="regime-bar-value">{fmt(optResult.tax_old)}</span>
                        </div>
                        <div className="regime-bar-row">
                          <span className="regime-bar-label">{t.newRegime}</span>
                          <div className="regime-bar-track">
                            <svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
                              <rect x="0" y="0" width="100" height="10" className="regime-bar-bg" />
                              <rect x="0" y="0" width={newBarPct} height="10" className="regime-bar-fill regime-bar-fill--new" />
                            </svg>
                          </div>
                          <span className="regime-bar-value">{fmt(optResult.tax_new)}</span>
                        </div>
                      </div>

                      <div className="regime-compare-bottom">
                        <div className={`regime-compare-card regime-compare-card--old${optResult.recommended_regime === 'old' ? ' recommended' : ''}`}>
                          <span className="rc-label">{t.oldRegime}</span>
                          <span className="rc-tax">{fmt(optResult.tax_old)}</span>
                          <span className={`rc-badge${optResult.recommended_regime === 'old' ? '' : ' rc-badge--alt'}`}>
                            {optResult.recommended_regime === 'old' ? t.best : 'Alternative'}
                          </span>
                        </div>

                        <div className="regime-savings-wheel" title={`Potential savings ${fmt(savingsAbs)}`}>
                          <svg viewBox="0 0 80 80" width="80" height="80" aria-hidden="true">
                            <circle cx="40" cy="40" r="30" pathLength="100" className="regime-wheel-track" />
                            <circle
                              cx="40"
                              cy="40"
                              r="30"
                              pathLength="100"
                              className="regime-wheel-progress"
                              strokeDasharray={`${savingsPct} 100`}
                              transform="rotate(-90 40 40)"
                            />
                          </svg>
                          <div className="regime-savings-copy">
                            <span className="regime-savings-label">Potential Save</span>
                            <strong>{fmt(savingsAbs)}</strong>
                            <small>{savingsPct}% lower tax</small>
                          </div>
                        </div>

                        <div className={`regime-compare-card regime-compare-card--new${optResult.recommended_regime === 'new' ? ' recommended' : ''}`}>
                          <span className="rc-label">{t.newRegime}</span>
                          <span className="rc-tax">{fmt(optResult.tax_new)}</span>
                          <span className={`rc-badge${optResult.recommended_regime === 'new' ? '' : ' rc-badge--alt'}`}>
                            {optResult.recommended_regime === 'new' ? t.best : 'Alternative'}
                          </span>
                        </div>
                      </div>

                      {savingsAbs > 0 && (
                        <p className="regime-compare-note">
                          {regimeTag(optResult.recommended_regime)} gives <strong>{fmt(savingsAbs)}</strong> lower tax than the alternative.
                        </p>
                      )}

                      <div className="regime-breakdown-grid">
                        {([oldResult, newResult] as const).map((rr) => (
                          <div key={rr.regime} className="tax-breakdown-table">
                            <h4>{regimeTag(rr.regime)} - Detailed Breakdown</h4>
                            <table>
                              <tbody>
                                <tr><td>{t.grossIncome}</td><td>{fmt(rr.gross_income)}</td></tr>
                                <tr><td>{t.totalDeductions}</td><td>− {fmt(rr.total_deductions)}</td></tr>
                                <tr className="total-row"><td>{t.taxableIncome}</td><td>{fmt(rr.taxable_income)}</td></tr>
                                <tr><td>{t.taxSlabs}</td><td>{fmt(rr.tax_before_rebate)}</td></tr>
                                <tr><td>{t.lessRebate}</td><td>− {fmt(rr.rebate_87a)}</td></tr>
                                <tr><td>{t.lessCess}</td><td>{fmt(rr.cess)}</td></tr>
                                <tr className="total-row highlight"><td>{t.netTax}</td><td>{fmt(rr.total_tax)}</td></tr>
                              </tbody>
                            </table>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })()}
                    </>
                  )
                })()}
              </div>
            )}

            {activeResultTab === 'breakdown' && (
              <div className="result-section">
                <h4>{t.deductionBreakup}</h4>
                {result.deduction_breakup.length === 0 ? (
                  <p className="muted-text">{t.noDeductions}</p>
                ) : (
                  <div className="deduction-list">
                    {result.deduction_breakup.map((item, i) => (
                      <div key={i} className="deduction-item">
                        <div className="deduction-header">
                          <span className="deduction-section">{item.section_label || item.section}</span>
                          <span className="deduction-amount">{fmt(item.amount)}</span>
                        </div>
                        <p className="deduction-explanation">{item.explanation}</p>
                        {item.legal_reference && (
                          <span className="deduction-ref">{item.legal_reference}</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeResultTab === 'optimize' && (
              <div className="result-section">
                <h4>{t.investSuggestions}</h4>
                {optResult.suggested_investments.length === 0 ? (
                  <p className="muted-text">{t.maxDeductions}</p>
                ) : (
                  <div className="suggestion-list">
                    {optResult.suggested_investments.map((s, i) => {
                      const fillPct = Math.max(0, Math.min(100, Math.round((s.current_claim / s.max_deduction) * 10) * 10))
                      return (
                        <div key={i} className="suggestion-item">
                          <div className="suggestion-top">
                            <span className="suggestion-section">{s.section}</span>
                            <span className="suggestion-amount">+ {fmt(s.suggested_additional)}</span>
                          </div>
                          <p>{s.message}</p>
                          <div className="suggestion-bar-wrap">
                            <div className="suggestion-bar">
                              <div className={`suggestion-bar-fill suggestion-bar-fill--${fillPct}`} />
                            </div>
                            <span className="suggestion-bar-label">{fmt(s.current_claim)} / {fmt(s.max_deduction)}</span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            {activeResultTab === 'insights' && (() => {
              const insights = generateInsights(result, optResult, deductions, salary, metro)
              const checklist = getFilingChecklist(salary, result)
              const healthScore = getTaxHealthScore(result, optResult)
              const scoreLabel = healthScore >= 70 ? 'Well Optimised' : healthScore >= 45 ? 'Can Improve' : 'Needs Attention'
              const healthAttr = healthScore >= 70 ? 'good' : healthScore >= 45 ? 'warn' : 'bad'
              return (
                <div className="result-section insights-section">
                  {/* Tax Health Score */}
                  <div className="tax-health-card" data-health={healthAttr}>
                    <div className="tax-health-gauge">
                      <svg viewBox="0 0 80 80" width="80" height="80">
                        <circle cx="40" cy="40" r="32" fill="none" strokeWidth="6" className="health-arc-bg" />
                        <circle
                          cx="40" cy="40" r="32" fill="none"
                          strokeWidth="6" strokeLinecap="round"
                          strokeDasharray={`${(healthScore / 100) * 201} 201`}
                          transform="rotate(-90 40 40)"
                          className="health-arc"
                        />
                        <text x="40" y="45" textAnchor="middle" fontSize="18" fontWeight="700" className="health-arc-text">{healthScore}</text>
                      </svg>
                    </div>
                    <div className="tax-health-copy">
                      <span className="tax-health-score-label">{scoreLabel}</span>
                      <p>Your tax health score based on deduction utilisation and effective rate. Higher = more optimised.</p>
                      <div className="tax-health-meta">
                        <span>Effective rate: <strong>{fmtPct(result.effective_rate_pct)}</strong></span>
                        <span>Deductions: <strong>{fmt(result.total_deductions)}</strong></span>
                        <span>Regime: <strong>{result.regime === 'new' ? 'New' : 'Old'}</strong></span>
                      </div>
                    </div>
                  </div>

                  {/* Personalized insights */}
                  <h4 className="insights-section-title">Personalized Recommendations</h4>
                  {insights.length === 0 ? (
                    <p className="muted-text">🎉 Your tax profile is well optimised! No additional actions needed.</p>
                  ) : (
                    <div className="insights-list">
                      {insights.map((item, i) => (
                        <div key={i} className={`insight-card insight-card--${item.type} insight-card--${item.priority}`}>
                          <div className="insight-card-top">
                            <span className="insight-icon">{item.icon}</span>
                            <div className="insight-body">
                              <div className="insight-title-row">
                                <span className="insight-title">{item.title}</span>
                                {item.impact && <span className="insight-impact">{item.impact}</span>}
                              </div>
                              <p className="insight-desc">{item.description}</p>
                            </div>
                          </div>
                          {item.section && (
                            <span className="insight-section-badge">{item.section}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Filing checklist */}
                  <h4 className="insights-section-title insights-section-title--filing">Filing Checklist</h4>
                  <div className="filing-checklist-card">
                    <div className="filing-checklist-header">
                      <span className="filing-form-badge">{checklist.form}</span>
                      <span className="filing-due">Due: {checklist.dueDate}</span>
                    </div>
                    <p className="filing-reason">{checklist.reason}</p>
                    <ul className="filing-docs">
                      {checklist.docs.map((doc, i) => (
                        <li key={i}><span className="filing-doc-check">✓</span>{doc}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )
            })()}
          </>
        )}
      </div>
    </div>
  )
}
