interface Props {
  current: string
  onSelect: (code: string) => void
  onClose: () => void
}

export const INDIAN_LANGUAGES = [
  { code: 'en',  label: 'English',    native: 'English',   script: 'Latin' },
  { code: 'hi',  label: 'Hindi',      native: 'Hindi',     script: 'Devanagari' },
  { code: 'ta',  label: 'Tamil',      native: 'Tamil',     script: 'Tamil' },
  { code: 'te',  label: 'Telugu',     native: 'Telugu',    script: 'Telugu' },
  { code: 'kn',  label: 'Kannada',    native: 'Kannada',   script: 'Kannada' },
  { code: 'ml',  label: 'Malayalam',  native: 'Malayalam', script: 'Malayalam' },
  { code: 'bn',  label: 'Bengali',    native: 'Bengali',   script: 'Bengali' },
  { code: 'mr',  label: 'Marathi',    native: 'Marathi',   script: 'Devanagari' },
  { code: 'gu',  label: 'Gujarati',   native: 'Gujarati',  script: 'Gujarati' },
  { code: 'pa',  label: 'Punjabi',    native: 'Punjabi',   script: 'Gurmukhi' },
  { code: 'or',  label: 'Odia',       native: 'Odia',      script: 'Odia' },
  { code: 'as',  label: 'Assamese',   native: 'Assamese',  script: 'Bengali' },
  { code: 'ur',  label: 'Urdu',       native: 'Urdu',      script: 'Nastaliq' },
  { code: 'ks',  label: 'Kashmiri',   native: 'Kashmiri',  script: 'Perso-Arabic' },
  { code: 'mai', label: 'Maithili',   native: 'Maithili',  script: 'Devanagari' },
  { code: 'mni', label: 'Manipuri',   native: 'Manipuri',  script: 'Meitei' },
  { code: 'ne',  label: 'Nepali',     native: 'Nepali',    script: 'Devanagari' },
  { code: 'sa',  label: 'Sanskrit',   native: 'Sanskrit',  script: 'Devanagari' },
  { code: 'sd',  label: 'Sindhi',     native: 'Sindhi',    script: 'Arabic' },
  { code: 'kok', label: 'Konkani',    native: 'Konkani',   script: 'Devanagari' },
  { code: 'doi', label: 'Dogri',      native: 'Dogri',     script: 'Devanagari' },
  { code: 'sat', label: 'Santali',    native: 'Santali',   script: 'Ol Chiki' },
]

export function LanguagePicker({ current, onSelect, onClose }: Props) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="lang-modal" onClick={e => e.stopPropagation()}>
        <div className="lang-modal-header">
          <div>
            <h3>Choose Your Language</h3>
            <p>TaxAI will process and respond in your selected language.</p>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">x</button>
        </div>

        <div className="lang-grid">
          {INDIAN_LANGUAGES.map(lang => (
            <button
              key={lang.code}
              className={`lang-option${current === lang.code ? ' selected' : ''}`}
              onClick={() => { onSelect(lang.code); onClose() }}
            >
              <div className="lang-option-main">
                <span className="lang-native">{lang.native}</span>
                <span className="lang-english">{lang.label}</span>
              </div>
              <div className="lang-option-meta">
                <span className="lang-script">{lang.script}</span>
                {current === lang.code && <span className="lang-check">Selected</span>}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
