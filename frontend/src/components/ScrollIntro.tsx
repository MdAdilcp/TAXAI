import { useEffect, useMemo, useRef, useState } from 'react'
import { TaxAILogo } from './BrandLogo'
import { IntroTransitionLayer, createIntroTransitionDrops } from './IntroTransitionLayer'

interface Props {
  onComplete: () => void
}

const CLAMP_MIN = 0
const CLAMP_MAX = 100

function clamp(value: number) {
  return Math.min(CLAMP_MAX, Math.max(CLAMP_MIN, value))
}

export function ScrollIntro({ onComplete }: Props) {
  const [progress, setProgress] = useState(0)
  const [exiting, setExiting] = useState(false)
  const touchStartY = useRef<number | null>(null)
  const progressFillRef = useRef<HTMLSpanElement | null>(null)
  const doneRef = useRef(false)
  const targetProgressRef = useRef(0)
  const velocityRef = useRef(0)
  const lastInputTsRef = useRef(0)

  const steps = useMemo(
    () => [
      { title: 'Income Inputs', note: 'Salary and investments captured in one place' },
      { title: 'Deduction Mapping', note: '80C, 80D, and HRA organized automatically' },
      { title: 'Regime Decision', note: 'Old vs New comparison with clear savings view' },
    ],
    [],
  )

  const moneyDrops = useMemo(
    () => createIntroTransitionDrops(),
    [],
  )

  const finish = () => {
    if (doneRef.current) return
    doneRef.current = true
    setExiting(true)
    window.setTimeout(onComplete, 1380)
  }

  useEffect(() => {
    if (progress >= 90 && !doneRef.current) {
      setProgress(100)
      targetProgressRef.current = 100
      finish()
      return
    }
    if (progress >= 100) finish()
  }, [progress])

  useEffect(() => {
    if (!progressFillRef.current) return
    progressFillRef.current.style.width = `${progress}%`
  }, [progress])

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [])

  useEffect(() => {
    let rafId = 0
    let lastTs = performance.now()
    const FRAME_MS = 16.67

    const animate = (ts: number) => {
      const dt = Math.min(32, ts - lastTs)
      lastTs = ts

      const sinceInput = ts - lastInputTsRef.current

      // Keep short inertial glide after input, but with stronger damping for smooth control.
      if (Math.abs(velocityRef.current) > 0.003 && sinceInput < 1200) {
        targetProgressRef.current = clamp(targetProgressRef.current + velocityRef.current * (dt / FRAME_MS))
        const friction = Math.pow(0.87, dt / FRAME_MS)
        velocityRef.current *= friction
      } else {
        velocityRef.current = 0
      }

      setProgress(prev => {
        const target = targetProgressRef.current
        if (sinceInput < 90) return target
        const diff = target - prev
        const smoothFactor = Math.abs(diff) > 14 ? 0.34 : 0.46
        const next = prev + diff * smoothFactor
        return Math.abs(next - target) < 0.015 ? target : next
      })

      if (!doneRef.current) {
        rafId = requestAnimationFrame(animate)
      }
    }

    rafId = requestAnimationFrame(animate)

    const applyDelta = (delta: number) => {
      if (doneRef.current) return
      const boundedDelta = Math.max(-11, Math.min(11, delta))
      lastInputTsRef.current = performance.now()
      targetProgressRef.current = clamp(targetProgressRef.current + boundedDelta)
      // Update visual progress immediately on input to avoid perceived lag.
      setProgress(targetProgressRef.current)
      velocityRef.current = Math.max(-1.6, Math.min(1.6, velocityRef.current * 0.28 + boundedDelta * 0.055))
      // Prevent end-range stalling: once user pushes forward near completion, finish.
      if (boundedDelta > 0 && targetProgressRef.current >= 86) {
        targetProgressRef.current = 100
      }
    }

    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const delta = Math.abs(event.deltaY) * 0.027
      const signedDelta = event.deltaY >= 0 ? delta : -delta
      applyDelta(signedDelta)
    }

    const onTouchStart = (event: TouchEvent) => {
      touchStartY.current = event.touches[0]?.clientY ?? null
    }

    const onTouchMove = (event: TouchEvent) => {
      if (touchStartY.current == null) return
      const currentY = event.touches[0]?.clientY ?? touchStartY.current
      const deltaY = touchStartY.current - currentY
      touchStartY.current = currentY
      applyDelta(deltaY * 0.12)
      event.preventDefault()
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'ArrowDown' || event.key === 'PageDown' || event.key === ' ') {
        event.preventDefault()
        applyDelta(6)
      }
      if (event.key === 'ArrowUp' || event.key === 'PageUp') {
        event.preventDefault()
        applyDelta(-6)
      }
    }

    window.addEventListener('wheel', onWheel, { passive: false })
    window.addEventListener('touchstart', onTouchStart, { passive: true })
    window.addEventListener('touchmove', onTouchMove, { passive: false })
    window.addEventListener('keydown', onKeyDown)

    return () => {
      window.removeEventListener('wheel', onWheel)
      window.removeEventListener('touchstart', onTouchStart)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('keydown', onKeyDown)
      cancelAnimationFrame(rafId)
    }
  }, [])

  return (
    <div className={`tax-intro ${exiting ? 'is-exiting' : ''}`} role="region" aria-label="TaxAI Introduction">
      <IntroTransitionLayer drops={moneyDrops} />

      <div className="tax-intro-mini-menu" role="navigation" aria-label="Quick tax context">
        <button type="button" className="tax-intro-mini-item">
          <span>AY</span>
          <strong>2025-26</strong>
        </button>
        <button type="button" className="tax-intro-mini-item">
          <span>Residency</span>
          <strong>India</strong>
        </button>
        <button type="button" className="tax-intro-mini-item">
          <span>Mode</span>
          <strong>Local only</strong>
        </button>
      </div>

      <div className="tax-intro-content">
        <div className="tax-intro-brand">
          <TaxAILogo size="lg" className="tax-intro-logo" />
          <p>Tax-ready intelligence for Indian filing. Local-first and private by default.</p>
        </div>

        <div className="tax-intro-main">
          <div className="tax-intro-copy">
            <h1>
              Your taxes, calculated by intelligence
            </h1>
            <p className="tax-intro-benefits">
              Faster filing, clearer deductions, and private local data.
            </p>

            <div className="tax-intro-steps">
              {steps.map((item, index) => (
                <article key={item.title} className={`tax-intro-step tax-intro-step--${index + 1}`}>
                  <strong>{item.title}</strong>
                  <small>{item.note}</small>
                </article>
              ))}
            </div>
          </div>

          <div className="tax-intro-art" aria-hidden="true">
            <svg viewBox="0 0 520 180" preserveAspectRatio="xMidYMid meet" className="tax-intro-art-svg">
              <defs>
                <linearGradient id="taxDocCard" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(174,220,255,0.18)" />
                  <stop offset="100%" stopColor="rgba(77,126,214,0.06)" />
                </linearGradient>
                <linearGradient id="taxPipeFlow" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="rgba(122,190,255,0.08)" />
                  <stop offset="55%" stopColor="rgba(168,230,255,0.7)" />
                  <stop offset="100%" stopColor="rgba(105,176,255,0.1)" />
                </linearGradient>
                <radialGradient id="taxInsightGlow" cx="50%" cy="50%" r="65%">
                  <stop offset="0%" stopColor="rgba(132,242,193,0.9)" />
                  <stop offset="100%" stopColor="rgba(91,178,140,0.05)" />
                </radialGradient>
                <linearGradient id="taxChip" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="rgba(102,164,255,0.22)" />
                  <stop offset="100%" stopColor="rgba(137,209,255,0.44)" />
                </linearGradient>
              </defs>

              <text x="58" y="26" className="tax-art-label">1. Upload</text>
              <text x="174" y="26" className="tax-art-label">2. Parse</text>
              <text x="282" y="26" className="tax-art-label">3. Deduct</text>
              <text x="392" y="26" className="tax-art-label">4. Decide</text>

              <rect x="44" y="42" width="94" height="98" rx="12" className="tax-art-doc-card tax-art-doc-card--back" />
              <rect x="52" y="34" width="94" height="98" rx="12" className="tax-art-doc-card" />
              <line x1="68" y1="58" x2="132" y2="58" className="tax-art-doc-line" />
              <line x1="68" y1="72" x2="126" y2="72" className="tax-art-doc-line" />
              <line x1="68" y1="86" x2="130" y2="86" className="tax-art-doc-line" />
              <line x1="68" y1="100" x2="116" y2="100" className="tax-art-doc-line" />

              <rect x="168" y="63" width="94" height="44" rx="10" className="tax-art-chip" />
              <text x="186" y="89" className="tax-art-value">Parser AI</text>

              <rect x="278" y="48" width="102" height="74" rx="10" className="tax-art-insight-card" />
              <circle cx="294" cy="69" r="5.5" className="tax-art-insight-dot" />
              <circle cx="294" cy="87" r="5.5" className="tax-art-insight-dot" />
              <circle cx="294" cy="105" r="5.5" className="tax-art-insight-dot" />
              <text x="306" y="72" className="tax-art-label">80C matched</text>
              <text x="306" y="90" className="tax-art-label">80D valid</text>
              <text x="306" y="108" className="tax-art-label">HRA optimized</text>

              <rect x="396" y="58" width="102" height="54" rx="10" className="tax-art-insight-card" />
              <text x="414" y="98" className="tax-art-label">Save Rs 42,300</text>
              <circle cx="484" cy="70" r="18" className="tax-art-insight-glow" />

              <line x1="146" y1="84" x2="166" y2="84" className="tax-art-pipe" />
              <line x1="262" y1="84" x2="276" y2="84" className="tax-art-pipe" />
              <line x1="380" y1="84" x2="394" y2="84" className="tax-art-pipe" />
              <line x1="146" y1="84" x2="166" y2="84" className="tax-art-pipe-flow" />
              <line x1="262" y1="84" x2="276" y2="84" className="tax-art-pipe-flow tax-art-pipe-flow--2" />
              <line x1="380" y1="84" x2="394" y2="84" className="tax-art-pipe-flow tax-art-pipe-flow--3" />

              <circle cx="154" cy="84" r="3.8" className="tax-art-token tax-art-token--1" />
              <circle cx="154" cy="84" r="3.8" className="tax-art-token tax-art-token--2" />

              <rect x="52" y="148" width="446" height="12" rx="6" className="tax-art-workflow-base" />
              <rect x="52" y="148" width="446" height="12" rx="6" className="tax-art-workflow-active" />
            </svg>
          </div>
        </div>

        <div className="tax-intro-progress" aria-live="polite">
          <div className="tax-intro-progress-bar">
            <span ref={progressFillRef} />
          </div>
          <p>
            Scroll to login <em>{Math.round(progress)}%</em>
          </p>
        </div>
      </div>
    </div>
  )
}
