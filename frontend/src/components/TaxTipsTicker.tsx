import { useState, useEffect, useCallback } from 'react'

type TipCategory = '80C' | 'HRA' | 'NPS' | 'New Regime' | 'Old Regime' | '80D' | 'Filing' | 'General' | 'Home Loan' | '87A'

type TaxTip = {
  id: number
  category: TipCategory
  headline: string
  body: string
  impact?: string
}

const TAX_TIPS: TaxTip[] = [
  {
    id: 1, category: '80C',
    headline: 'Max out Section 80C — Save up to ₹46,800',
    body: 'Invest up to ₹1,50,000 in ELSS, PPF, EPF, LIC, or NSC to claim the full 80C deduction. At the 30% slab, that\'s ₹46,800 saved in tax (including cess).',
    impact: 'Save ₹46,800/yr',
  },
  {
    id: 2, category: 'NPS',
    headline: 'Extra ₹50,000 via NPS — Exclusive of 80C',
    body: 'Section 80CCD(1B) lets you claim an additional ₹50,000 deduction for NPS contributions, over and above the ₹1.5L 80C limit. A salaried employee can save ~₹15,600 extra in tax.',
    impact: 'Save ₹15,600 extra',
  },
  {
    id: 3, category: 'New Regime',
    headline: 'New Regime: Zero tax up to ₹7 Lakh',
    body: 'Post Budget 2023, the new tax regime offers a rebate under 87A making income up to ₹7L effectively tax-free. It also has lower slab rates but no deductions (80C, HRA, etc.) apply.',
    impact: 'Zero tax ≤ ₹7L',
  },
  {
    id: 4, category: 'Old Regime',
    headline: 'Old Regime best if you have a home loan + heavy investments',
    body: 'If you pay rent (HRA), have a home loan (Sec 24b — ₹2L), and max out 80C + NPS, the old regime usually saves more tax. Run a comparison before you decide.',
  },
  {
    id: 5, category: 'HRA',
    headline: 'HRA Exemption — Submit rent receipts on time',
    body: 'HRA exemption = minimum of (i) HRA received, (ii) rent paid − 10% basic, (iii) 50% basic (metro) / 40% basic (non-metro). Submit rent receipts to your employer before March 31.',
    impact: 'Often ₹60K–₹1.2L',
  },
  {
    id: 6, category: '80D',
    headline: 'Health insurance for parents — claim up to ₹50,000 (80D)',
    body: 'Premiums paid for parents\' health insurance qualify for an additional ₹25,000 deduction (₹50,000 if parents are senior citizens) under Section 80D, on top of your own ₹25,000.',
    impact: 'Up to ₹50,000 extra',
  },
  {
    id: 7, category: 'Home Loan',
    headline: 'Home Loan Interest — Deduct up to ₹2 Lakh (Sec 24b)',
    body: 'Interest paid on a home loan for a self-occupied property is deductible up to ₹2,00,000 per year under Section 24(b). For let-out property there is no upper limit.',
    impact: 'Save up to ₹62,400',
  },
  {
    id: 8, category: 'General',
    headline: 'Standard Deduction — ₹50,000 automatically applied',
    body: 'Salaried employees get a flat ₹50,000 standard deduction in both old and new regimes. No receipts needed — it is automatically allowed when you file your ITR.',
    impact: '₹50,000 free',
  },
  {
    id: 9, category: '87A',
    headline: 'Section 87A Rebate — Fully offsets your tax',
    body: 'If your total taxable income does not exceed ₹5L (old) or ₹7L (new), Section 87A rebate wipes out your entire tax. Ensure deductions are properly claimed to stay below the threshold.',
    impact: 'Zero tax possible',
  },
  {
    id: 10, category: 'Filing',
    headline: 'File by July 31 to avoid ₹5,000 late fee',
    body: 'Missing the due date (July 31 for non-audit cases) attracts a late fee of ₹5,000 under Section 234F (₹1,000 if total income ≤ ₹5L). Filing on time also helps process refunds faster.',
  },
  {
    id: 11, category: 'General',
    headline: 'ELSS: Shortest lock-in in 80C with equity upside',
    body: 'ELSS mutual funds have only a 3-year lock-in — the shortest among all 80C options. They also provide market-linked returns, historically outperforming PPF over the long term.',
    impact: 'Min lock-in: 3 yrs',
  },
  {
    id: 12, category: 'Old Regime',
    headline: 'PPF — EEE Status: Invest, Earn & Withdraw Tax-Free',
    body: 'Public Provident Fund enjoys Exempt-Exempt-Exempt (EEE) tax status. Contributions (under 80C), annual interest, and the full maturity amount are all completely tax-free.',
  },
  {
    id: 13, category: 'Filing',
    headline: 'Reconcile Form 26AS and AIS before filing',
    body: 'Form 26AS shows TDS credits; AIS (Annual Information Statement) shows all financial transactions reported by third parties. Reconcile both with your income to avoid scrutiny notices.',
  },
  {
    id: 14, category: '80C',
    headline: 'Children\'s tuition fees are covered under 80C',
    body: 'Tuition fees paid for up to two children\'s school or college education qualify for deduction under Section 80C. Only tuition fees count — not donations or development fees.',
    impact: 'Part of ₹1.5L limit',
  },
  {
    id: 15, category: 'General',
    headline: 'Section 80E: Education loan interest is fully deductible',
    body: 'Interest paid on a loan taken for higher education (self, spouse, children) is 100% deductible under Section 80E for up to 8 years from the year repayment starts. No upper limit.',
    impact: 'No cap on deduction',
  },
  {
    id: 16, category: 'General',
    headline: '80G: Donate and save tax simultaneously',
    body: 'Donations to notified charities, the PM Relief Fund, or approved NGOs give 50–100% deduction under Section 80G. Ensure you get an 80G receipt with a valid PAN.',
  },
  {
    id: 17, category: 'HRA',
    headline: 'Paying rent to parents? Claim HRA the right way',
    body: 'You can genuinely pay rent to your parents (who own the house) and claim HRA. Your parents must show this rent as income in their returns. Maintain a rent agreement and payment proof.',
  },
  {
    id: 18, category: 'New Regime',
    headline: 'New Regime default from AY 2024-25',
    body: 'As per Budget 2023, the new tax regime is now the default. If you want the old regime\'s deductions (80C, HRA, etc.), explicitly opt in by filing your ITR under the old regime.',
  },
  {
    id: 19, category: 'General',
    headline: '80TTA: ₹10,000 deduction on savings account interest',
    body: 'Interest earned on savings bank accounts (not FD) is deductible up to ₹10,000 under Section 80TTA. Senior citizens get ₹50,000 under 80TTB (covers FD interest too).',
    impact: 'Up to ₹10,000',
  },
  {
    id: 20, category: 'Home Loan',
    headline: 'First home buyer? Extra ₹1.5L under Section 80EEA',
    body: 'If you bought your first home with a loan sanctioned between April 2019–March 2022 and stamp duty ≤ ₹45L, claim an extra ₹1,50,000 deduction under Section 80EEA over and above 24(b).',
    impact: 'Extra ₹1.5L',
  },
  {
    id: 21, category: 'Filing',
    headline: 'ITR-1 (Sahaj) for simple salary income',
    body: 'If your income is only from salary, one house property, and interest (total ≤ ₹50L), use ITR-1. Move to ITR-2 if you have capital gains or overseas assets.',
  },
  {
    id: 22, category: 'General',
    headline: 'Leave Travel Allowance (LTA) — Claim twice in 4 years',
    body: 'LTA is exempt for travel within India (for shortest route airfare / fare by A/C 1st class train). You can claim it twice in a 4-calendar-year block. Keep boarding passes and tickets.',
  },
  {
    id: 23, category: 'NPS',
    headline: 'Employer NPS contribution (80CCD(2)) — Most underused benefit',
    body: 'If your employer contributes to your NPS (Tier I), you can deduct up to 10% of Basic + DA under Section 80CCD(2) — completely separate from the ₹1.5L 80C + ₹50K 80CCD(1B) limits.',
    impact: 'Uncapped extra saving',
  },
  {
    id: 24, category: '80D',
    headline: 'Preventive health check-up: ₹5,000 under 80D',
    body: 'Expenses on preventive health check-ups (blood tests, ECG, etc.) up to ₹5,000 count towards your 80D limit. Keep the bills — they\'re easy to miss but quick to claim.',
    impact: 'Up to ₹5,000',
  },
  {
    id: 25, category: '80C',
    headline: 'SCSS — Safe 80C option for senior citizens',
    body: 'Senior Citizens Savings Scheme (SCSS) qualifies under 80C, pays higher interest than FDs, and is government-backed. Maximum deposit: ₹30L. Interest is taxable but can be offset by 80TTB.',
  },
]

interface Props {
  autoplayMs?: number
}

export function TaxTipsTicker({ autoplayMs = 6000 }: Props) {
  const [current, setCurrent] = useState(0)
  const [animating, setAnimating] = useState(false)
  const [direction, setDirection] = useState<'next' | 'prev'>('next')

  const goTo = useCallback((next: number, dir: 'next' | 'prev') => {
    if (animating) return
    setDirection(dir)
    setAnimating(true)
    setTimeout(() => {
      setCurrent(next)
      setAnimating(false)
    }, 320)
  }, [animating])

  const next = useCallback(() => {
    goTo((current + 1) % TAX_TIPS.length, 'next')
  }, [current, goTo])

  const prev = useCallback(() => {
    goTo((current - 1 + TAX_TIPS.length) % TAX_TIPS.length, 'prev')
  }, [current, goTo])

  useEffect(() => {
    const id = setInterval(next, autoplayMs)
    return () => clearInterval(id)
  }, [next, autoplayMs])

  const tip = TAX_TIPS[current]

  return (
    <div className="tips-ticker" aria-label="Tax tips carousel">
      <div className="tips-ticker-header">
        <span className="tips-ticker-label">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
            <path d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1zm0 1.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM7.25 5h1.5v1.5h-1.5V5zm0 3h1.5v4h-1.5V8z"/>
          </svg>
          Tax Wisdom
        </span>
        <div className="tips-ticker-dots">
          {TAX_TIPS.map((_, i) => (
            <button
              key={i}
              className={`tips-dot${i === current ? ' active' : ''}`}
              onClick={() => goTo(i, i > current ? 'next' : 'prev')}
              aria-label={`Tip ${i + 1}`}
            />
          ))}
        </div>
        <div className="tips-ticker-nav">
          <button className="tips-nav-btn" onClick={prev} aria-label="Previous tip">‹</button>
          <span className="tips-counter">{current + 1} / {TAX_TIPS.length}</span>
          <button className="tips-nav-btn" onClick={next} aria-label="Next tip">›</button>
        </div>
      </div>

      <div className={`tips-ticker-body tips-ticker-body--${direction}${animating ? ' animating' : ''}`}>
        <div className="tips-card">
          <div className="tips-card-top">
            <span className="tips-category-badge" data-cat={tip.category}>
              {tip.category}
            </span>
            {tip.impact && (
              <span className="tips-impact-badge">{tip.impact}</span>
            )}
          </div>
          <h4 className="tips-headline">{tip.headline}</h4>
          <p className="tips-body">{tip.body}</p>
        </div>
      </div>
    </div>
  )
}
