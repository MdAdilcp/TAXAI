type Size = 'sm' | 'md' | 'lg'
type Variant = 'dark' | 'light'

const ICON_SIZE: Record<Size, number> = { sm: 32, md: 42, lg: 58 }

interface TaxAILogoProps {
  size?: Size
  variant?: Variant
  animateRupee?: boolean
  glowWordmark?: boolean
  showText?: boolean
  className?: string
}

export function TaxAILogo({
  size = 'md',
  variant = 'dark',
  animateRupee = false,
  glowWordmark = false,
  showText = true,
  className,
}: TaxAILogoProps) {
  const iconHeight = ICON_SIZE[size]
  const iconWidth = Math.round(iconHeight * 0.92)
  const classes = [
    'taxai-logo',
    `taxai-logo--${size}`,
    `taxai-logo--${variant}`,
    animateRupee ? 'taxai-logo--animated' : '',
    glowWordmark ? 'taxai-logo--glow' : '',
    showText ? '' : 'taxai-logo--icon-only',
    className || '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={classes} role="img" aria-label="TaxAI">
      <span className="taxai-logo-icon-wrap" aria-hidden="true">
        <img
          src="/assets/brand-logo.png?v=6"
          alt=""
          aria-hidden="true"
          width={iconWidth}
          height={iconHeight}
          className="taxai-logo-icon"
          loading="eager"
          decoding="async"
          draggable={false}
        />
      </span>
      {showText && (
        <span className="taxai-logo-text" aria-hidden="true">
          <span className="taxai-logo-text-tax">Tax</span>
          <span className="taxai-logo-text-ai">AI</span>
        </span>
      )}
    </span>
  )
}

