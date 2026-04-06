import { useEffect, useRef } from 'react'

export type IntroTransitionDrop = {
  left: number
  delay: number
  duration: number
  size: number
  drift: number
  opacity: number
  rotate: number
  start: number
}

export function createIntroTransitionDrops(count = 34): IntroTransitionDrop[] {
  return Array.from({ length: count }, (_, index) => ({
    left: 2 + ((index * 9) % 96),
    delay: Number((index * 0.035).toFixed(2)),
    duration: Number((1.05 + (index % 7) * 0.14).toFixed(2)),
    size: Number((0.92 + (index % 5) * 0.16).toFixed(2)),
    drift: Number((-30 + (index % 11) * 6).toFixed(0)),
    opacity: Number((0.58 + (index % 4) * 0.1).toFixed(2)),
    rotate: Number((-20 + (index % 8) * 6).toFixed(0)),
    start: Number((-14 - (index % 6) * 18).toFixed(0)),
  }))
}

interface IntroTransitionLayerProps {
  drops: IntroTransitionDrop[]
}

export function IntroTransitionLayer({ drops }: IntroTransitionLayerProps) {
  const layerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const host = layerRef.current
    if (!host) return

    const elements = host.querySelectorAll<HTMLSpanElement>('.tax-intro-money-drop')
    elements.forEach((element, index) => {
      const drop = drops[index % drops.length]
      if (!drop) return
      element.style.setProperty('--drop-left', `${drop.left}%`)
      element.style.setProperty('--drop-delay', `${drop.delay}s`)
      element.style.setProperty('--drop-duration', `${drop.duration}s`)
      element.style.setProperty('--drop-size', String(drop.size))
      element.style.setProperty('--drop-drift', `${drop.drift}px`)
      element.style.setProperty('--drop-opacity', String(drop.opacity))
      element.style.setProperty('--drop-rotate', `${drop.rotate}deg`)
      element.style.setProperty('--drop-start', `${drop.start}%`)
    })
  }, [drops])

  return (
    <div ref={layerRef} className="tax-intro-bg" aria-hidden="true">
      <span className="tax-intro-orb tax-intro-orb--one" />
      <span className="tax-intro-orb tax-intro-orb--two" />
      <span className="tax-intro-grid" />

      <div className="tax-intro-money-flow tax-intro-money-flow--bg">
        {drops.map((_, index) => (
          <span key={`bg-drop-${index}`} className="tax-intro-money-drop is-rupee">
            {'\u20B9'}
          </span>
        ))}
      </div>

      <div className="tax-intro-money-flow tax-intro-money-flow--exit">
        {drops.map((_, index) => (
          <span key={`exit-drop-${index}`} className="tax-intro-money-drop is-rupee">
            {'\u20B9'}
          </span>
        ))}
      </div>
    </div>
  )
}
