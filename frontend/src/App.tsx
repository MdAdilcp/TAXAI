import { useState, useEffect, useMemo } from 'react'
import { ParticleCanvas } from './components/ParticleCanvas'
import { LoginPage } from './components/LoginPage'
import { LanguagePicker, INDIAN_LANGUAGES } from './components/LanguagePicker'
import { Avatar } from './components/Avatar'
import { ConversationWidget } from './components/ConversationWidget'
import { TaxCalculator } from './components/TaxCalculator'
import { TaxTipsTicker } from './components/TaxTipsTicker'
import { TaxAILogo } from './components/BrandLogo'
import { ScrollIntro } from './components/ScrollIntro'
import { IntroTransitionLayer, createIntroTransitionDrops } from './components/IntroTransitionLayer'
import type { AvatarPrompt } from './components/Avatar'
import type { User } from './types'

type Tab = 'calculator' | 'assistant'
type ThemeMode = 'dark' | 'light'
const AUTH_TRANSITION_MS = 1900

type FilingRecord = {
  id: string
  title: string
  filedAt: string
}

type UploadedDocHistory = {
  id: string
  fileName: string
  docType: string
  uploadedAt: string
  ocrStatus?: string
  ocrAccuracy?: string
  ocrClarity?: string
}

const DOC_TYPE_LABELS: Record<string, string> = {
  payslip: 'Form 16 / Payslip',
  investment: 'Investment Proof',
  rent_receipt: 'Rent Receipt',
  medical_bill: 'Medical Bills',
  other: 'Other Document',
}

function CalcIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="currentColor">
      <rect x="3" y="2" width="14" height="16" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5"/>
      <rect x="6" y="5" width="8" height="3" rx="1"/>
      <rect x="6" y="10" width="2.5" height="2.5" rx=".5"/>
      <rect x="8.75" y="10" width="2.5" height="2.5" rx=".5"/>
      <rect x="11.5" y="10" width="2.5" height="2.5" rx=".5"/>
      <rect x="6" y="13.5" width="2.5" height="2.5" rx=".5"/>
      <rect x="8.75" y="13.5" width="2.5" height="2.5" rx=".5"/>
      <rect x="11.5" y="13.5" width="2.5" height="2.5" rx=".5"/>
    </svg>
  )
}

function AiIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="currentColor">
      <path d="M10 2a8 8 0 1 1 0 16A8 8 0 0 1 10 2zm0 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM9.25 6h1.5v5.5h-1.5V6zm0 7h1.5v1.5h-1.5V13z"/>
    </svg>
  )
}

function GlobeIcon() {
  return (
    <svg viewBox="0 0 20 20" width="15" height="15" fill="currentColor">
      <path d="M10 2a8 8 0 1 1 0 16A8 8 0 0 1 10 2zm0 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zm0 .5c.55 0 1.5.9 2.18 2.5H7.82C8.5 4.9 9.45 4 10 4zm-2.5.4A8.3 8.3 0 0 0 6.06 7H4.1A6.52 6.52 0 0 1 7.5 4.4zm5 0A6.52 6.52 0 0 1 15.9 7h-1.96A8.3 8.3 0 0 0 12.5 4.4zM3.6 8.5h2.15c-.1.48-.25 1-.25 1.5s.1 1.02.25 1.5H3.6A6.44 6.44 0 0 1 3.5 10c0-.52.04-1.02.1-1.5zm3.65 0h5.5c.13.48.25.99.25 1.5s-.12 1.02-.25 1.5h-5.5A6.7 6.7 0 0 1 7 10c0-.51.12-1.02.25-1.5zm6 0h2.15c.06.48.1.98.1 1.5 0 .52-.04 1.02-.1 1.5h-2.15c.15-.48.25-1 .25-1.5s-.1-1.02-.25-1.5zM4.1 13H6.06c.35.93.83 1.73 1.44 2.38A6.52 6.52 0 0 1 4.1 13zm2.46 0h6.88C12.86 14.73 11.5 16 10 16s-2.86-1.27-3.44-3zm4.4 2.6c.61-.65 1.09-1.45 1.44-2.38l1.96-.02A6.52 6.52 0 0 1 10.96 15.6z"/>
    </svg>
  )
}

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [introDone, setIntroDone] = useState(false)
  const [showLangPicker, setShowLangPicker] = useState(false)
  const [avatarPrompt, setAvatarPrompt] = useState<AvatarPrompt | null>(null)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [tab, setTab] = useState<Tab>('calculator')
  const [calculatorAnimState, setCalculatorAnimState] = useState<'idle' | 'greeting' | 'computing' | 'celebrating'>('greeting')
  const [theme, setTheme] = useState<ThemeMode>(() => (localStorage.getItem('taxai_theme') as ThemeMode) || 'dark')
  const [authTransitioning, setAuthTransitioning] = useState(false)
  const [leftPanelOpen, setLeftPanelOpen] = useState(true)
  const [filingHistory, setFilingHistory] = useState<FilingRecord[]>([])
  const [uploadedHistory, setUploadedHistory] = useState<UploadedDocHistory[]>([])

  const transitionDrops = useMemo(
    () => createIntroTransitionDrops(),
    [],
  )

  const filingHistoryKey = user ? `taxai_filing_history_${user.email}` : null
  const legacyHistoryKey = user ? `taxai_history_${user.email}` : null
  const uploadsKey = user ? `taxai_uploads_${user.email}` : null

  // Restore session
  useEffect(() => {
    const saved = localStorage.getItem('taxai_session')
    if (saved) {
      try { setUser(JSON.parse(saved)) } catch { /* ignore */ }
    }
  }, [])

  useEffect(() => {
    // Keep pre-auth screens (intro/login) consistently in dark mode.
    const activeTheme: ThemeMode = user ? theme : 'dark'
    document.documentElement.setAttribute('data-theme', activeTheme)
    localStorage.setItem('taxai_theme', theme)
  }, [theme, user])

  useEffect(() => {
    if (!filingHistoryKey || !uploadsKey) {
      setFilingHistory([])
      setUploadedHistory([])
      return
    }

    let filingLoaded = false
    try {
      const h = JSON.parse(localStorage.getItem(filingHistoryKey) || '[]') as FilingRecord[]
      if (Array.isArray(h) && h.length > 0) {
        setFilingHistory(h)
        filingLoaded = true
      }
    } catch {
      setFilingHistory([])
    }

    if (!filingLoaded && legacyHistoryKey) {
      try {
        const legacy = JSON.parse(localStorage.getItem(legacyHistoryKey) || '[]') as Array<{ id?: string; message?: string; at?: string }>
        const migrated = (Array.isArray(legacy) ? legacy : [])
          .filter((x) => /itr|return|filing|filed|submit/i.test(x.message || ''))
          .map((x) => ({
            id: x.id || crypto.randomUUID(),
            title: x.message || 'Previous filing',
            filedAt: x.at || new Date().toISOString(),
          }))
          .slice(0, 80)
        setFilingHistory(migrated)
        localStorage.setItem(filingHistoryKey, JSON.stringify(migrated))
      } catch {
        setFilingHistory([])
      }
    }

    try {
      const u = JSON.parse(localStorage.getItem(uploadsKey) || '[]') as UploadedDocHistory[]
      setUploadedHistory(Array.isArray(u) ? u : [])
    } catch {
      setUploadedHistory([])
    }
  }, [filingHistoryKey, legacyHistoryKey, uploadsKey])

  useEffect(() => {
    if (!filingHistoryKey) return
    localStorage.setItem(filingHistoryKey, JSON.stringify(filingHistory))
  }, [filingHistoryKey, filingHistory])

  useEffect(() => {
    if (!uploadsKey) return
    localStorage.setItem(uploadsKey, JSON.stringify(uploadedHistory))
  }, [uploadsKey, uploadedHistory])

  useEffect(() => {
    const handler = (ev: Event) => {
      const ce = ev as CustomEvent<{ record?: FilingRecord }>
      const record = ce.detail?.record
      if (!record) return
      setFilingHistory((prev) => [record, ...prev.filter((x) => x.id !== record.id)].slice(0, 80))
    }
    window.addEventListener('taxai:filing_recorded', handler as EventListener)
    return () => window.removeEventListener('taxai:filing_recorded', handler as EventListener)
  }, [])

  useEffect(() => {
    const handler = (ev: Event) => {
      const ce = ev as CustomEvent<{ items?: UploadedDocHistory[] }>
      const items = ce.detail?.items || []
      if (!items.length) return
      setUploadedHistory(prev => [...items, ...prev].slice(0, 120))
    }
    window.addEventListener('taxai:docs_uploaded', handler as EventListener)
    return () => window.removeEventListener('taxai:docs_uploaded', handler as EventListener)
  }, [])

  const handleLogin = async (u: User) => {
    if (authTransitioning) return
    setAuthTransitioning(true)
    await new Promise(resolve => window.setTimeout(resolve, AUTH_TRANSITION_MS))
    setUser(u)
    localStorage.setItem('taxai_session', JSON.stringify(u))
    window.requestAnimationFrame(() => setAuthTransitioning(false))
  }

  const handleLogout = () => {
    // Clear persisted chat history for this user before logging out
    if (user) {
      localStorage.removeItem(`taxai_chat_${user.email}`)
    }
    setUser(null)
    localStorage.removeItem('taxai_session')
  }

  const handleLanguageSelect = (code: string) => {
    if (!user) return
    const updated = { ...user, language: code }
    setUser(updated)
    localStorage.setItem('taxai_session', JSON.stringify(updated))
    // also update stored account
    localStorage.setItem(`taxai_user_${user.email}`, JSON.stringify({ ...updated, password: (JSON.parse(localStorage.getItem(`taxai_user_${user.email}`) || '{}') as Record<string,string>).password }))
  }

  const handleTabChange = (nextTab: Tab) => {
    setTab(nextTab)
  }

  const toggleTheme = () => {
    const next: ThemeMode = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
  }

  const uploadsByDepartment = useMemo(() => {
    const grouped: Record<string, UploadedDocHistory[]> = {}
    for (const item of uploadedHistory) {
      const key = item.docType || 'other'
      if (!grouped[key]) grouped[key] = []
      grouped[key].push(item)
    }
    return grouped
  }, [uploadedHistory])

  const currentLang = INDIAN_LANGUAGES.find(l => l.code === (user?.language || 'en'))
  const firstName = user?.name.split(' ')[0] || 'there'
  const dashboardHighlights = [
    { label: 'Documents', value: uploadedHistory.length, meta: uploadedHistory.length ? 'Ready for review' : 'Start by uploading docs' },
    { label: 'Filings', value: filingHistory.length, meta: filingHistory.length ? 'Saved activity' : 'No filings yet' },
    { label: 'Mode', value: tab === 'calculator' ? 'Tax' : 'AI', meta: tab === 'calculator' ? 'Direct computation' : 'Conversational help' },
  ]

  const authTransitionOverlay = authTransitioning ? (
    <div className="auth-transition-overlay" aria-hidden="true">
      <div className="tax-intro is-exiting">
        <IntroTransitionLayer drops={transitionDrops} />
      </div>
    </div>
  ) : null

  if (!user && !introDone) {
    return (
      <ScrollIntro
        onComplete={() => {
          setIntroDone(true)
        }}
      />
    )
  }

  if (!user && authTransitioning) {
    return authTransitionOverlay
  }

  if (!user) {
    return (
      <>
        <LoginPage onLogin={handleLogin} />
        {authTransitionOverlay}
      </>
    )
  }

  return (
    <div className="page-root page-root--app">
      {authTransitionOverlay}
      <div className="app-ambient" aria-hidden="true">
        <ParticleCanvas transparent />
        <span className="app-ambient-orb app-ambient-orb--1" />
        <span className="app-ambient-orb app-ambient-orb--2" />
        <span className="app-ambient-orb app-ambient-orb--3" />
        <span className="app-ambient-grid" />
        <span className="app-ambient-comet" />
      </div>

      {showLangPicker && (
        <LanguagePicker
          current={user.language}
          onSelect={handleLanguageSelect}
          onClose={() => setShowLangPicker(false)}
        />
      )}

      {/* Header */}
      <header className="site-header">
        <div className="header-inner">
          <div className="header-brand">
            <TaxAILogo size="md" showText className="brand-logo-mark" />
          </div>
          <nav className="header-tabs">
            <button className={`htab${tab === 'calculator' ? ' active' : ''}`} onClick={() => handleTabChange('calculator')}>
              <CalcIcon /> Tax Calculator
            </button>
            <button className={`htab${tab === 'assistant' ? ' active' : ''}`} onClick={() => handleTabChange('assistant')}>
              <AiIcon /> AI Assistant
            </button>
          </nav>
          <div className="header-right">
            <button className="lang-btn" onClick={() => setLeftPanelOpen(v => !v)} title="Toggle left menu">
              <span>{leftPanelOpen ? '▾' : '▸'}</span>
              <span>Menu</span>
            </button>
            <button className="lang-btn" onClick={toggleTheme} title="Toggle theme">
              <span>{theme === 'dark' ? '☀' : '🌙'}</span>
              <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
            </button>
            <button className="lang-btn" onClick={() => setShowLangPicker(true)} title="Change language">
              <GlobeIcon />
              <span>{currentLang?.native || 'English'}</span>
            </button>
            <div className="user-pill">
              <div className="user-avatar-letter">{user.name.charAt(0).toUpperCase()}</div>
              <div className="user-info">
                <span className="user-name">{user.name}</span>
                {user.pan && <span className="user-pan">{user.pan}</span>}
              </div>
              <button className="logout-btn" onClick={handleLogout} title="Sign out">
                <svg viewBox="0 0 20 20" width="14" height="14" fill="currentColor">
                  <path d="M3 3h8v2H5v10h6v2H3V3zm10.293 3.293 1.414 1.414L12.414 10l2.293 2.293-1.414 1.414L10.586 10l2.707-3.707z"/>
                  <path d="M12 9h8v2h-8V9z"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="site-main">
        <div className={`main-shell ${leftPanelOpen ? 'menu-open' : 'menu-closed'}`}>
          {leftPanelOpen && (
          <aside className="left-history open">
              <>
                <div className="lh-head">
                  <h3>My Workspace</h3>
                  <p>Manage documents, filings, and profile</p>
                </div>

                <div className="lh-block">
                  <details className="lh-section">
                    <summary className="lh-title">
                      <span className="lh-title-main"><span className="lh-title-icon">🗂</span>My Docs</span>
                      <span className="lh-count">{uploadedHistory.length}</span>
                    </summary>
                    <div className="lh-section-content">
                      {Object.keys(uploadsByDepartment).length === 0 ? (
                        <p className="lh-empty">No uploaded docs yet.</p>
                      ) : (
                        Object.entries(uploadsByDepartment).map(([dept, docs]) => (
                          <details className="lh-dept" key={dept}>
                            <summary>{DOC_TYPE_LABELS[dept] || dept} ({docs.length})</summary>
                            <ul>
                              {docs.map((d) => (
                                <li key={d.id}>
                                  <span>{d.fileName}</span>
                                  <small>{d.ocrStatus || 'needs_review'} · {new Date(d.uploadedAt).toLocaleString()}</small>
                                </li>
                              ))}
                            </ul>
                          </details>
                        ))
                      )}
                    </div>
                  </details>
                </div>

                <div className="lh-block">
                  <details className="lh-section">
                    <summary className="lh-title">
                      <span className="lh-title-main"><span className="lh-title-icon">🧾</span>Filing History</span>
                      <span className="lh-count">{filingHistory.length}</span>
                    </summary>
                    <div className="lh-section-content">
                      {filingHistory.length === 0 ? (
                        <p className="lh-empty">No filing activity yet.</p>
                      ) : (
                        <ul className="lh-list">
                          {filingHistory.map((f) => (
                            <li key={f.id}>
                              <span>{f.title}</span>
                              <small>{new Date(f.filedAt).toLocaleString()}</small>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </details>
                </div>

                <div className="lh-block">
                  <details className="lh-section">
                    <summary className="lh-title">
                      <span className="lh-title-main"><span className="lh-title-icon">👤</span>My Profile</span>
                    </summary>
                    <div className="lh-section-content">
                      <div className="lh-profile-card">
                        <span><strong>Name:</strong> {user.name}</span>
                        <span><strong>Email:</strong> {user.email}</span>
                        {user.pan && <span><strong>PAN:</strong> {user.pan}</span>}
                        <span><strong>Language:</strong> {currentLang?.label || 'English'}</span>
                      </div>
                    </div>
                  </details>
                </div>

                <div className="lh-block">
                  <details className="lh-section">
                    <summary className="lh-title">
                      <span className="lh-title-main"><span className="lh-title-icon">⎋</span>Logout</span>
                    </summary>
                    <div className="lh-section-content">
                      <button className="lh-logout-btn" onClick={handleLogout} type="button">Sign out</button>
                    </div>
                  </details>
                </div>
              </>
            
          </aside>
          )}

          <div className="main-content">
        <section className="dashboard-hero">
          <div className="dashboard-hero-copy">
            <span className="dashboard-chip">Workspace overview</span>
            <h1>Welcome back, {firstName}</h1>
            <p>
              Manage your tax workflow in one place — upload documents, compare regimes, and get AI-guided answers in {currentLang?.native || 'English'}.
            </p>
            <div className="dashboard-pill-row">
              <span className="dashboard-pill">AY 2024-25</span>
              <span className="dashboard-pill">{tab === 'calculator' ? 'Calculator active' : 'Assistant active'}</span>
              <span className="dashboard-pill">{theme === 'dark' ? 'Dark theme' : 'Light theme'}</span>
            </div>
          </div>
          <div className="dashboard-hero-stats">
            {dashboardHighlights.map((item) => (
              <div key={item.label} className="dashboard-stat-card">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.meta}</small>
              </div>
            ))}
          </div>
        </section>

        {tab === 'calculator' && (
          <section className="tab-section tab-section--calculator">
            <div className="section-intro">
              <h2>Direct Tax Computation</h2>
              <p>Upload Form 16 or enter manually. Compute Old vs New regime, get deduction advice — no govt portal needed.</p>
            </div>
            <TaxTipsTicker />
            <div className="home-welcome-card">
              <div className="home-welcome-avatar">
                <Avatar
                  isSpeaking={false}
                  animationState={calculatorAnimState}
                  prompt={{ text: `Hi ${user.name.split(' ')[0]}`, avatar: { expression: 'helpful' } }}
                  className="avatar-canvas"
                />
              </div>
              <div className="home-welcome-copy">
                <p className="home-welcome-title">Hi {firstName} 👋</p>
                <p className="home-welcome-sub">I'm your TaxAI assistant. Upload your Form 16 or enter details manually to compute tax instantly.</p>
                <div className="home-welcome-badges">
                  <span>Old vs New regime</span>
                  <span>Deduction insights</span>
                  <span>Form 16 ready</span>
                </div>
              </div>
            </div>
            <TaxCalculator onAnimationStateChange={setCalculatorAnimState} lang={user.language} />
          </section>
        )}
        {tab === 'assistant' && (
          <section className="tab-section tab-section--assistant">
            <div className="section-intro">
              <h2>AI Tax Assistant</h2>
              <p>Ask tax questions in {currentLang?.native || 'English'} — your CA-avatar will respond.</p>
            </div>
            <div className="assistant-layout">
              <div className="avatar-panel">
                <Avatar
                  isSpeaking={isSpeaking}
                  animationState={isSpeaking ? 'speaking' : 'idle'}
                  prompt={avatarPrompt}
                  className="avatar-canvas"
                />
                <p className="avatar-greeting">Namaste, {user.name.split(' ')[0]}!</p>
                <button className="lang-btn lang-btn--panel" onClick={() => setShowLangPicker(true)}>
                  <GlobeIcon /> {currentLang?.native} · Change
                </button>
                <p className="avatar-hint">Responding in {currentLang?.label}</p>
              </div>
              <ConversationWidget
                languageHint={user.language}
                onAvatarPrompt={setAvatarPrompt}
                onSpeakingChange={setIsSpeaking}
                storageKey={`taxai_chat_${user.email}`}
                uploadedDocs={uploadedHistory.map(doc => ({
                  file_name: doc.fileName,
                  doc_type: doc.docType,
                  extracted_fields: 0,
                  ocr_status: doc.ocrStatus,
                }))}
                userProfile={{
                  filing_status: 'Individual',
                }}
              />
            </div>
          </section>
        )}
          </div>
        </div>
      </main>

      <footer className="site-footer">
        <span className="footer-brand">Tax<span className="footer-brand-ai">AI</span></span>
        <span className="footer-sep">·</span>
        Standalone computation engine
        <span className="footer-sep">·</span>
        No ERI / PAN / GSTN
        <span className="footer-sep">·</span>
        AY 2024-25
      </footer>
    </div>
  )
}

export default App
