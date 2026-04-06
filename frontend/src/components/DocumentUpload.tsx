import { useState, useRef, useCallback } from 'react'
import type { PrefilledTaxData } from '../types'

const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
const API_FALLBACK = (import.meta.env.VITE_API_FALLBACK_URL || '').replace(/\/$/, '')
const DEV_LOCAL_FALLBACK = 'http://127.0.0.1:8001'
const ALLOW_DEMO_UPLOAD = import.meta.env.VITE_ALLOW_DEMO_UPLOAD === '1'
const UPLOAD_TIMEOUT_MS = Number(import.meta.env.VITE_UPLOAD_TIMEOUT_MS || 240000)

function endpointBases(): string[] {
  const bases = [API_BASE, API_FALLBACK || (import.meta.env.DEV ? DEV_LOCAL_FALLBACK : '')]
    .map((x) => (x || '').replace(/\/$/, ''))
    .filter(Boolean)
  return Array.from(new Set(bases))
}

async function backendReachable(): Promise<{ ok: boolean; endpoint: string }> {
  const bases = endpointBases()
  for (const base of bases) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 6000)
    try {
      const res = await fetch(`${base}/health`, { method: 'GET', signal: controller.signal })
      if (res.ok) return { ok: true, endpoint: base }
    } catch {
      // Try next endpoint.
    } finally {
      clearTimeout(timeout)
    }
  }
  return { ok: false, endpoint: bases[0] || '/api' }
}

async function postUpload(fd: FormData): Promise<Response> {
  const bases = endpointBases()
  const primary = `${(bases[0] || '').replace(/\/$/, '')}/api/upload-doc`
  const fallback = bases[1] ? `${bases[1]}/api/upload-doc` : ''

  const tryPost = async (url: string): Promise<Response> => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS)
    try {
      return await fetch(url, { method: 'POST', body: fd, signal: controller.signal })
    } finally {
      clearTimeout(timeout)
    }
  }

  let primaryErr: Error | null = null
  try {
    const res = await tryPost(primary)
    if (res.ok) return res
    const body = await res.text().catch(() => '')
    if (body) {
      throw new Error(`Upload failed: ${res.status} ${body}`)
    }
    throw new Error(`Upload failed: ${res.status}`)
  } catch (err) {
    primaryErr = err instanceof Error ? err : new Error('Primary upload failed')
    // Try fallback below.
  }

  // Avoid duplicate or invalid fallback calls.
  if (!fallback || primary === fallback) {
    throw primaryErr || new Error('Upload failed on primary API endpoint')
  }

  const fallbackRes = await tryPost(fallback)
  if (!fallbackRes.ok) {
    const body = await fallbackRes.text().catch(() => '')
    throw new Error(body ? `Upload failed: ${fallbackRes.status} ${body}` : `Upload failed: ${fallbackRes.status}`)
  }
  return fallbackRes
}

interface UploadedDoc {
  doc_id: string
  doc_type: string
  structured_data: Record<string, unknown>
  tax_calculator_json?: {
    compute_tax_payload?: Record<string, unknown>
    prefill?: PrefilledTaxData
    doc_type?: string
  }
  raw_text_preview?: string
  confidence: number
  ocr_status?: 'verified' | 'needs_review'
  ocr_clarity?: 'clear' | 'readable' | 'unclear'
  ocr_accuracy?: 'high' | 'medium' | 'low'
  ocr_issues?: string[]
  extracted_fields?: number
  expected_fields?: number
  fileName: string
}

interface Props {
  onPrefill: (data: PrefilledTaxData) => void
}

const DOC_TYPES = [
  { value: 'payslip',       label: 'Form 16 / Payslip',   desc: 'Salary certificate, Form 16 Part A/B', icon: '📄' },
  { value: 'form16',        label: 'Form 16',             desc: 'Part A & Part B with TDS and deductions', icon: '🧾' },
  { value: 'ais',           label: 'AIS',                 desc: 'Annual Information Statement categories', icon: '📊' },
  { value: 'form26as',      label: 'Form 26AS',           desc: 'TDS/TCS tax credit statement', icon: '🗂️' },
  { value: 'investment',    label: 'Investment Proof',     desc: '80C, 80D, NPS, ELSS statements',       icon: '📈' },
  { value: 'rent_receipt',  label: 'Rent Receipt',         desc: 'HRA rent receipts / agreements',       icon: '🏠' },
  { value: 'medical_bill',  label: 'Medical Bills',        desc: 'Health insurance, medical expenses',   icon: '🏥' },
  { value: 'other',         label: 'Other Document',       desc: 'Any other tax-relevant document',      icon: '📎' },
]

function ConfidencePill({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const cls = pct >= 75 ? 'high' : pct >= 45 ? 'med' : 'low'
  return <span className={`conf-pill conf-${cls}`}>{pct}% confidence</span>
}

function FieldRow({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === '' || value === 0) return null
  const rendered = typeof value === 'object'
    ? JSON.stringify(value)
    : String(value)
  return (
    <tr>
      <td className="extracted-key">{label.replace(/_/g, ' ')}</td>
      <td className="extracted-val">{rendered}</td>
    </tr>
  )
}

function mergePrefillFromDocs(docs: UploadedDoc[]): PrefilledTaxData {
  const merged: PrefilledTaxData = {}
  const add = (key: keyof PrefilledTaxData, value: number) => {
    if (!value) return
    merged[key] = (Number(merged[key]) || 0) + value
  }

  for (const doc of docs) {
    const prefill = doc.tax_calculator_json?.prefill
    if (!prefill) continue
    for (const [key, raw] of Object.entries(prefill)) {
      const value = Number(raw) || 0
      add(key as keyof PrefilledTaxData, value)
    }
  }
  return merged
}

export function DocumentUpload({ onPrefill }: Props) {
  const [docs, setDocs] = useState<UploadedDoc[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [selectedType, setSelectedType] = useState('payslip')
  const [error, setError] = useState<string | null>(null)
  const [applied, setApplied] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const upload = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setUploading(true)
    setError(null)

    if (!ALLOW_DEMO_UPLOAD) {
      const status = await backendReachable()
      if (!status.ok) {
        setUploading(false)
        setError(`Backend is not reachable at ${status.endpoint}. Start backend on http://127.0.0.1:8001 and retry.`)
        return
      }
    }

    const results: UploadedDoc[] = []
    const failedFiles: string[] = []
    const failedReasons: string[] = []
    for (const file of Array.from(files)) {
      try {
        const fd = new FormData()
        fd.append('file', file)
        fd.append('doc_type', selectedType)
        const res = await postUpload(fd)
        if (!res.ok) throw new Error(`Server error ${res.status}`)
        const data = await res.json()
        results.push({ ...data, fileName: file.name })
      } catch (err) {
        if (ALLOW_DEMO_UPLOAD) {
          const simulated = simulateExtraction(file.name, selectedType)
          results.push(simulated)
        } else {
          failedFiles.push(file.name)
          const isAbort = err instanceof DOMException && err.name === 'AbortError'
          const reason = err instanceof Error ? err.message : 'upload request failed'
          failedReasons.push(
            isAbort
              ? `${file.name}: processing timeout after ${Math.round(UPLOAD_TIMEOUT_MS / 1000)}s`
              : `${file.name}: ${reason}`,
          )
          // Keep processing remaining files so one failure does not block batch upload.
          console.error('Upload failed for file:', file.name, err)
        }
      }
    }
    if (failedFiles.length > 0) {
      const endpointHint = API_FALLBACK || (import.meta.env.DEV ? DEV_LOCAL_FALLBACK : '/api')
      const hint = failedReasons.length
        ? failedReasons.join(' | ')
        : `Upload failed for: ${failedFiles.join(', ')}`
      setError(`${hint}. Backend endpoint: ${endpointHint}.`)
    }
    if (results.length === 0) {
      setUploading(false)
      return
    }
    setDocs(prev => [...prev, ...results])
    const apiPrefill = mergePrefillFromDocs(results)
    if (Object.keys(apiPrefill).length > 0) {
      onPrefill(apiPrefill)
      setApplied(true)
    } else {
      setApplied(false)
    }
    window.dispatchEvent(new CustomEvent('taxai:docs_uploaded', {
      detail: {
        items: results.map((r) => ({
          id: r.doc_id,
          fileName: r.fileName,
          docType: r.doc_type,
          uploadedAt: new Date().toISOString(),
          ocrStatus: r.ocr_status || 'needs_review',
          ocrAccuracy: r.ocr_accuracy || 'low',
          ocrClarity: r.ocr_clarity || 'unclear',
        })),
      },
    }))
    setUploading(false)
  }, [onPrefill, selectedType])

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    upload(e.dataTransfer.files)
  }

  const removeDoc = (id: string) => setDocs(d => d.filter(x => x.doc_id !== id))

  const applyAll = () => {
    const merged: PrefilledTaxData = mergePrefillFromDocs(docs)
    for (const doc of docs) {
      if (doc.tax_calculator_json?.prefill && Object.keys(doc.tax_calculator_json.prefill).length > 0) {
        continue
      }
      const d = doc.structured_data
      const n = (k: string) => Number(d[k]) || 0
      if (doc.doc_type === 'payslip') {
        if (n('basic_salary') || n('basic')) merged.basic = (merged.basic || 0) + (n('basic_salary') || n('basic'))
        if (n('hra')) merged.hra_received = (merged.hra_received || 0) + n('hra')
        if (n('special_allowance')) merged.special_allowance = (merged.special_allowance || 0) + n('special_allowance')
        if (n('perquisites') || n('perquisites_u_s_17_2')) merged.perquisites = (merged.perquisites || 0) + (n('perquisites') || n('perquisites_u_s_17_2'))
        if (n('profits_in_lieu') || n('profits_in_lieu_u_s_17_3')) merged.profits_in_lieu = (merged.profits_in_lieu || 0) + (n('profits_in_lieu') || n('profits_in_lieu_u_s_17_3'))
        if (n('lta') || n('lta_exempt')) merged.ltaExempt = (merged.ltaExempt || 0) + (n('lta_exempt') || n('lta'))
        if (n('professional_tax') || n('pt')) merged.professionalTax = (merged.professionalTax || 0) + (n('professional_tax') || n('pt'))
        if (n('other_income')) merged.other_income = (merged.other_income || 0) + n('other_income')
      }
      if (doc.doc_type === 'form16') {
        const safe = (value: number, min: number) => (value >= min ? value : 0)
        const hraExempt = safe((n('hra_exemption_u_s_10_13a') || n('hra') || 0), 500)
        if (n('gross_salary') || n('gross_total_income')) {
          const grossAnnual = n('gross_total_income') || n('gross_salary')
          merged.basic = (merged.basic || 0) + Math.max(0, grossAnnual * 0.4)
          merged.hra_received = (merged.hra_received || 0) + hraExempt
        }
        if (hraExempt > 0) merged.otherSection10Exemptions = (merged.otherSection10Exemptions || 0) + hraExempt
        if (safe(n('professional_tax') || n('pt'), 100)) merged.professionalTax = (merged.professionalTax || 0) + safe(n('professional_tax') || n('pt'), 100)
        if (safe(n('deduction_80c') || n('amount_80c'), 1000)) merged.section80C = (merged.section80C || 0) + safe(n('deduction_80c') || n('amount_80c'), 1000)
        if (n('deduction_80ccd_1b') || n('amount_80ccd_1b')) merged.nps = (merged.nps || 0) + (n('deduction_80ccd_1b') || n('amount_80ccd_1b'))
        if (safe(n('deduction_80d') || n('amount_80d'), 1000)) merged.medicalSelf = (merged.medicalSelf || 0) + safe(n('deduction_80d') || n('amount_80d'), 1000)
      }
      if (doc.doc_type === 'ais') {
        const interestEntries = Array.isArray(d['interest_entries']) ? d['interest_entries'] as Array<Record<string, unknown>> : []
        const dividendEntries = Array.isArray(d['dividend_entries']) ? d['dividend_entries'] as Array<Record<string, unknown>> : []
        const capSec = Array.isArray(d['capital_gains_securities']) ? d['capital_gains_securities'] as Array<Record<string, unknown>> : []
        const capOther = Array.isArray(d['capital_gains_other']) ? d['capital_gains_other'] as Array<Record<string, unknown>> : []
        const sum = (arr: Array<Record<string, unknown>>, k: string) => arr.reduce((acc, row) => acc + (Number(row[k]) || 0), 0)

        const interestTotal = sum(interestEntries, 'amount')
        const dividendTotal = sum(dividendEntries, 'amount')
        const capTotal = sum(capSec, 'amount') + sum(capOther, 'amount')

        if (interestTotal > 0) merged.other_income = (merged.other_income || 0) + interestTotal
        if (dividendTotal > 0) merged.dividendIncome = (merged.dividendIncome || 0) + dividendTotal
        if (capTotal > 0) merged.other_income = (merged.other_income || 0) + capTotal
      }
      if (doc.doc_type === 'form26as') {
        const tdsCredits = Array.isArray(d['tds_credits']) ? d['tds_credits'] as Array<Record<string, unknown>> : []
        const tdsTotal = tdsCredits.reduce((acc, row) => acc + (Number(row['amount_deducted']) || 0), 0)
        if (tdsTotal > 0) merged.other_income = (merged.other_income || 0)
      }
      if (doc.doc_type === 'investment') {
        if (n('amount_80c') || n('total_80c')) merged.section80C = (merged.section80C || 0) + (n('amount_80c') || n('total_80c'))
        if (n('amount_80ccd_1') || n('deduction_80ccd_1')) merged.section80ccd1 = (merged.section80ccd1 || 0) + (n('amount_80ccd_1') || n('deduction_80ccd_1'))
        if (n('nps_amount') || n('nps')) merged.nps = (merged.nps || 0) + (n('nps_amount') || n('nps'))
        if (n('health_insurance') || n('medical_premium')) merged.medicalSelf = (merged.medicalSelf || 0) + (n('health_insurance') || n('medical_premium'))
      }
      if (doc.doc_type === 'rent_receipt') {
        if (n('monthly_rent')) merged.rentPaid = (merged.rentPaid || 0) + n('monthly_rent') * 12
        if (n('annual_rent') || n('rent_paid')) merged.rentPaid = (merged.rentPaid || 0) + (n('annual_rent') || n('rent_paid'))
      }
      if (doc.doc_type === 'medical_bill') {
        if (n('amount') || n('total')) merged.medicalSelf = (merged.medicalSelf || 0) + (n('amount') || n('total'))
      }
    }
    onPrefill(merged)
    setApplied(true)
  }

  const docTypeInfo = (type: string) => DOC_TYPES.find(d => d.value === type) || DOC_TYPES[4]

  return (
    <div className="doc-upload-section">
      <div className="doc-upload-intro">
        <h4>What is Form 16 & other documents?</h4>
        <p>
          Form 16 / payslip gives your salary breakup and tax deducted. Investment proofs,
          rent receipts, and medical bills help identify eligible deductions (80C, 80D, HRA, etc.).
        </p>
        <div className="doc-intro-chips">
          <span className="doc-chip">Form 16 / Payslip → Salary data</span>
          <span className="doc-chip">Investment Proof → 80C / NPS</span>
          <span className="doc-chip">Rent Receipt → HRA claim</span>
          <span className="doc-chip">Medical Bills → 80D claim</span>
        </div>
      </div>

      {/* Doc type selector */}
      <div className="doc-type-grid">
        {DOC_TYPES.map(dt => (
          <button
            key={dt.value}
            className={`doc-type-card${selectedType === dt.value ? ' selected' : ''}`}
            onClick={() => {
              setSelectedType(dt.value)
              inputRef.current?.click()
            }}
            type="button"
          >
            <span className="dtc-icon">{dt.icon}</span>
            <span className="dtc-label">{dt.label}</span>
            <span className="dtc-desc">{dt.desc}</span>
          </button>
        ))}
      </div>

      {/* Drop zone */}
      <label
        className={`drop-zone${dragOver ? ' drag-over' : ''}${uploading ? ' uploading' : ''}`}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        htmlFor="taxai-upload-input"
      >
        <input
          ref={inputRef}
          id="taxai-upload-input"
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.tiff"
          className="hidden-file-input"
          title="Upload document"
          aria-label="Upload document"
          onChange={e => upload(e.target.files)}
        />
        {uploading ? (
          <>
            <div className="loader-ring" />
            <p>Processing document…</p>
            <span className="dz-hint">Extracting data with OCR</span>
          </>
        ) : (
          <>
            <div className="dz-icon">
              <svg viewBox="0 0 48 48" width="48" height="48" fill="none">
                <rect width="48" height="48" rx="12" fill="var(--accent-glow)"/>
                <path d="M24 14v14M17 21l7-7 7 7" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M14 34h20" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round"/>
              </svg>
            </div>
            <p>Drop files here or <span className="dz-link">browse</span></p>
            <span className="dz-hint">PDF, PNG, JPG — Form 16, payslips, investment proofs, rent receipts</span>
          </>
        )}
      </label>

      {error && <div className="error-banner">{error}</div>}

      {/* Uploaded docs */}
      {docs.length > 0 && (
        <div className="uploaded-docs">
          <div className="ud-header">
            <h4>Extracted Data ({docs.length} document{docs.length > 1 ? 's' : ''})</h4>
            {docs.length > 0 && (
              <button
                className={`apply-btn${applied ? ' applied' : ''}`}
                onClick={applyAll}
                type="button"
              >
                {applied ? (
                  <>
                    <svg className="icon-inline icon-inline--sm" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                    Applied to Calculator
                  </>
                ) : (
                  <>
                    <svg className="icon-inline icon-inline--sm" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="12 5 19 12 12 19" />
                      <polyline points="5 12 12 19 5 26" className="hidden-polyline" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                    Import Data
                  </>
                )}
              </button>
            )}
          </div>

          {docs.map(doc => {
            const info = docTypeInfo(doc.doc_type)
            return (
              <div key={doc.doc_id} className="ud-card">
                <div className="ud-card-header">
                  <div className="ud-card-title">
                    <span className="ud-icon">{info.icon}</span>
                    <div>
                      <strong>{doc.fileName}</strong>
                      <span className="ud-type-label">{info.label}</span>
                    </div>
                  </div>
                  <div className="ud-card-actions">
                    <ConfidencePill score={doc.confidence} />
                    <button className="ud-remove" onClick={() => removeDoc(doc.doc_id)} title="Remove">✕</button>
                  </div>
                </div>

                <div className={`ocr-verdict ${(doc.ocr_status || 'needs_review') === 'verified' ? 'ok' : 'warn'}`}>
                  <span className="ov-pill">
                    {(doc.ocr_status || 'needs_review') === 'verified' ? '✓ OCR Verified' : '⚠ Needs Review'}
                  </span>
                  <span className="ov-meta">
                    Clarity: {(doc.ocr_clarity || 'unclear').toUpperCase()} · Accuracy: {(doc.ocr_accuracy || 'low').toUpperCase()}
                  </span>
                  <span className="ov-meta">
                    Fields: {doc.extracted_fields || 0}/{doc.expected_fields || 0}
                  </span>
                </div>

                {doc.ocr_issues && doc.ocr_issues.length > 0 && (
                  <ul className="ocr-issues">
                    {doc.ocr_issues.map((issue, idx) => (
                      <li key={`${doc.doc_id}-${idx}`}>{issue}</li>
                    ))}
                  </ul>
                )}

                {Object.keys(doc.structured_data).length > 0 ? (
                  <div className="extracted-table-wrap">
                    <table className="extracted-table">
                      <tbody>
                        {Object.entries(doc.structured_data).map(([k, v]) => (
                          <FieldRow key={k} label={k} value={v} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="ud-nodata">No structured data extracted. Try a clearer scan.</p>
                )}

                {doc.raw_text_preview && (
                  <details className="raw-text-details">
                    <summary>Raw OCR text preview</summary>
                    <pre>{doc.raw_text_preview}</pre>
                  </details>
                )}
              </div>
            )
          })}
        </div>
      )}

      {applied && (
        <div className="apply-success">
          ✓ Tax Calculator has been pre-filled with extracted values. Switch to Manual Entry to review and edit.
        </div>
      )}
    </div>
  )
}

// Simulates extraction when OCR is not available (demo mode)
function simulateExtraction(fileName: string, docType: string): UploadedDoc {
  const name = fileName.toLowerCase()
  let structured: Record<string, unknown> = {}
  if (docType === 'payslip') {
    structured = {
      basic_salary: 480000, hra: 192000, special_allowance: 120000,
      professional_tax: 2400, gross_salary: 792000,
    }
  } else if (docType === 'investment') {
    structured = { total_80c: 150000, nps: 50000, health_insurance: 25000 }
  } else if (docType === 'form16') {
    structured = {
      employee_name: 'Rahul Sharma', employee_pan: 'ABCDE1234F', assessment_year: '2025-26',
      gross_total_income: 1240000, taxable_income: 1055000, total_tax_payable: 112500,
      tds_deducted: 105000, deduction_80c: 150000, deduction_80d: 25000,
    }
  } else if (docType === 'ais') {
    structured = {
      salary_entries: [{ employer: 'ACME Pvt Ltd', amount: 1240000, tds: 105000, status: 'confirmed' }],
      interest_entries: [{ source: 'Bank', type: 'fd', amount: 25000, tds: 2500 }],
      dividend_entries: [{ company: 'ABC Ltd', amount: 12000, tds: 1200 }],
      tds_credits: [{ section: '194A', deductor_name: 'Bank', tan: 'BLRA12345K', amount_deducted: 2500 }],
    }
  } else if (docType === 'form26as') {
    structured = {
      tds_credits: [{ section: '192', deductor_name: 'ACME Pvt Ltd', tan: 'BLRA12345K', amount_deducted: 105000 }],
      total_tds_deposited: 105000,
    }
  } else if (docType === 'rent_receipt') {
    structured = { monthly_rent: 20000, annual_rent: 240000 }
  } else if (docType === 'medical_bill') {
    structured = { amount: 12000, description: 'Health insurance premium' }
  }
  // hint from filename
  if (name.includes('form16') || name.includes('form_16')) {
    structured = { basic_salary: 600000, hra: 240000, special_allowance: 160000, professional_tax: 2400, total_80c: 150000 }
  }
  return {
    doc_id: crypto.randomUUID(),
    doc_type: docType,
    structured_data: structured,
    raw_text_preview: `[Demo mode] OCR not configured. Showing simulated data for "${fileName}".`,
    confidence: 0.72,
    fileName,
  }
}
