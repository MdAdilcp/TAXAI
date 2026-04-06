import { useState } from 'react'
import { ParticleCanvas } from './ParticleCanvas'
import { TaxAILogo } from './BrandLogo'
import type { User } from '../types'

interface Props {
  onLogin: (user: User) => Promise<void> | void
}

export function LoginPage({ onLogin }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [form, setForm] = useState({ name: '', email: '', password: '', pan: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!form.email || !form.password) { setError('Email and password are required.'); return }
    if (mode === 'register' && !form.name) { setError('Name is required.'); return }
    setLoading(true)
    await new Promise(r => setTimeout(r, 600)) // simulate network
    const existing = localStorage.getItem(`taxai_user_${form.email}`)
    if (mode === 'login') {
      if (!existing) { setError('No account found. Please register.'); setLoading(false); return }
      const stored = JSON.parse(existing) as User & { password: string }
      if (stored.password !== form.password) { setError('Incorrect password.'); setLoading(false); return }
      await onLogin(stored)
    } else {
      if (existing) { setError('Account already exists. Please log in.'); setLoading(false); return }
      const user: User & { password: string } = {
        id: crypto.randomUUID(), name: form.name, email: form.email,
        pan: form.pan.toUpperCase(), language: 'en', password: form.password,
      }
      localStorage.setItem(`taxai_user_${form.email}`, JSON.stringify(user))
      await onLogin(user)
    }
    setLoading(false)
  }

  return (
    <div className="login-page login-page--clean">
      <ParticleCanvas transparent densityMultiplier={1.6} speedMultiplier={0.88} linkDistance={95} cursorLinkDistance={115} />

      {/* Left panel */}
      <div className="login-hero">
        <div className="login-hero-inner">
          <div className="login-brand-stack">
            <span className="login-chip">Secure tax workspace</span>
            <div className="login-logo login-logo--royal">
              <TaxAILogo size="lg" glowWordmark className="login-logo-mark login-logo-mark--large" />
            </div>
          </div>
          <h1 className="login-hero-title">
            Old vs new regime.<br />Decided in seconds.
          </h1>
          <p className="login-hero-sub">
            Sign in to continue your structured filing workflow.
          </p>

          <div className="login-hero-steps" aria-hidden="true">
            <article className="login-hero-step">
              <strong>Income Inputs</strong>
              <small>Salary and proofs captured in one place.</small>
            </article>
            <article className="login-hero-step">
              <strong>Deduction Mapping</strong>
              <small>80C, 80D, and HRA organized automatically.</small>
            </article>
            <article className="login-hero-step">
              <strong>Regime Decision</strong>
              <small>Clear comparison with projected savings.</small>
            </article>
          </div>

          <div className="login-hero-progress" aria-hidden="true">
            <div className="login-hero-progress-bar">
              <span style={{ width: '74%' }} />
            </div>
            <p>
              Filing workflow readiness <em>74%</em>
            </p>
          </div>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="login-form-wrap">
        <div className="login-card-shell">
          <div className="login-card">
            <div className="login-card-kicker">TaxAI Workspace</div>
            <div className="login-card-header">
              <h2>{mode === 'login' ? 'Welcome back' : 'Create account'}</h2>
              <p>{mode === 'login' ? 'Sign in to continue' : 'Create your local workspace'}</p>
            </div>
            <div className="login-mode-tabs" aria-label="Auth mode">
              <button
                type="button"
                className={mode === 'login' ? 'active' : ''}
                onClick={() => { setMode('login'); setError('') }}
              >
                Sign In
              </button>
              <button
                type="button"
                className={mode === 'register' ? 'active' : ''}
                onClick={() => { setMode('register'); setError('') }}
              >
                Register
              </button>
            </div>

            <form onSubmit={submit} className="login-form" noValidate>
              {mode === 'register' && (
                <div className="lf-field">
                  <label htmlFor="lf-name">Full Name</label>
                  <div className="field-input-wrap">
                    <input id="lf-name" type="text" placeholder="Rahul Sharma" value={form.name} onChange={e => set('name', e.target.value)} autoComplete="name" />
                  </div>
                </div>
              )}
              <div className="lf-field">
                <label htmlFor="lf-email">Email address</label>
                <div className="field-input-wrap">
                  <input id="lf-email" name="email" type="email" placeholder="you@example.com" value={form.email} onChange={e => set('email', e.target.value)} autoComplete="email" />
                </div>
              </div>

              <div className="lf-field">
                <div className="lf-password-header">
                  <label htmlFor="lf-password">Password</label>
                  {mode === 'login' && <button type="button" className="lf-forgot-btn">Forgot?</button>}
                </div>
                <div className="field-input-wrap">
                  {mode === 'login' ? (
                    <input id="lf-password" name="current-password" type="password" placeholder="••••••••" value={form.password} onChange={e => set('password', e.target.value)} autoComplete="current-password" />
                  ) : (
                    <input id="lf-password" name="new-password" type="password" placeholder="••••••••" value={form.password} onChange={e => set('password', e.target.value)} autoComplete="new-password" />
                  )}
                </div>
              </div>

              {mode === 'register' && (
                <div className="lf-field">
                  <label htmlFor="lf-pan">
                    PAN Number <span className="lf-optional">(optional)</span>
                  </label>
                  <div className="field-input-wrap">
                    <input id="lf-pan" type="text" placeholder="ABCDE1234F" value={form.pan} onChange={e => set('pan', e.target.value.toUpperCase())} maxLength={10} />
                  </div>
                </div>
              )}

              {error && <div className="lf-error">{error}</div>}

              <button type="submit" className="lf-submit" disabled={loading}>
                {loading
                  ? <><span className="spinner" /> {mode === 'login' ? 'Signing in…' : 'Creating account…'}</>
                  : mode === 'login' ? 'Sign In' : 'Create Account'}
              </button>
            </form>

            <p className="login-switch">
              {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
              <button type="button" onClick={() => { setMode(m => m === 'login' ? 'register' : 'login'); setError('') }}>
                {mode === 'login' ? 'Register' : 'Sign in'}
              </button>
            </p>

            <p className="login-disclaimer">
              Local-first workspace. No government portal sync.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
