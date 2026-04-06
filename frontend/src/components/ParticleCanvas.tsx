import { useEffect, useRef } from 'react'

type ParticleCanvasProps = {
  transparent?: boolean
  densityMultiplier?: number
  speedMultiplier?: number
  linkDistance?: number
  cursorLinkDistance?: number
}

type Particle = {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  opacity: number
  color: '122,142,255' | '146,102,255'
}

const PARTICLE_AREA = 9000
const PARTICLE_MIN_RADIUS = 1.6
const PARTICLE_MAX_RADIUS = 3.4
const PARTICLE_MIN_OPACITY = 0.52
const PARTICLE_MAX_OPACITY = 1.0
const MAX_SPEED = 0.28
const DEFAULT_LINK_DISTANCE = 110
const DEFAULT_CURSOR_LINK_DISTANCE = 130

function randomBetween(min: number, max: number) {
  return Math.random() * (max - min) + min
}

function createParticle(width: number, height: number, index: number): Particle {
  return {
    x: Math.random() * width,
    y: Math.random() * height,
    vx: randomBetween(-MAX_SPEED, MAX_SPEED),
    vy: randomBetween(-MAX_SPEED, MAX_SPEED),
    radius: randomBetween(PARTICLE_MIN_RADIUS, PARTICLE_MAX_RADIUS),
    opacity: randomBetween(PARTICLE_MIN_OPACITY, PARTICLE_MAX_OPACITY),
    color: index % 2 === 0 ? '122,142,255' : '146,102,255',
  }
}

export function ParticleCanvas({
  transparent = false,
  densityMultiplier = 1,
  speedMultiplier = 1,
  linkDistance = DEFAULT_LINK_DISTANCE,
  cursorLinkDistance = DEFAULT_CURSOR_LINK_DISTANCE,
}: ParticleCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const context = canvas.getContext('2d')
    if (!context) return

    let animationFrameId = 0
    let particles: Particle[] = []
    let width = window.innerWidth
    let height = window.innerHeight
    let pixelRatio = Math.max(1, window.devicePixelRatio || 1)
    const mouse = { x: 0, y: 0, active: false }

    const initializeParticles = () => {
      width = window.innerWidth
      height = window.innerHeight
      pixelRatio = Math.max(1, window.devicePixelRatio || 1)

      canvas.width = Math.floor(width * pixelRatio)
      canvas.height = Math.floor(height * pixelRatio)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`

      context.setTransform(1, 0, 0, 1, 0, 0)
      context.scale(pixelRatio, pixelRatio)

      const particleCount = Math.max(1, Math.ceil(((width * height) / PARTICLE_AREA) * Math.max(0.2, densityMultiplier)))
      particles = Array.from({ length: particleCount }, (_, index) => createParticle(width, height, index))
    }

    const wrapParticle = (particle: Particle) => {
      if (particle.x < -particle.radius) particle.x = width + particle.radius
      else if (particle.x > width + particle.radius) particle.x = -particle.radius

      if (particle.y < -particle.radius) particle.y = height + particle.radius
      else if (particle.y > height + particle.radius) particle.y = -particle.radius
    }

    const drawConnections = () => {
      for (let i = 0; i < particles.length; i += 1) {
        const a = particles[i]
        for (let j = i + 1; j < particles.length; j += 1) {
          const b = particles[j]
          const dx = a.x - b.x
          const dy = a.y - b.y
          const distance = Math.hypot(dx, dy)
          if (distance > linkDistance) continue

          const alpha = (1 - distance / linkDistance) * 0.65
          context.beginPath()
          context.moveTo(a.x, a.y)
          context.lineTo(b.x, b.y)
          context.strokeStyle = `rgba(80,130,230,${alpha})`
          context.lineWidth = 0.95
          context.stroke()
        }
      }
    }

    const drawMouseConnections = () => {
      if (!mouse.active) return

      for (const particle of particles) {
        const dx = particle.x - mouse.x
        const dy = particle.y - mouse.y
        const distance = Math.hypot(dx, dy)
        if (distance > cursorLinkDistance) continue

        const alpha = (1 - distance / cursorLinkDistance) * 0.72
        context.beginPath()
        context.moveTo(particle.x, particle.y)
        context.lineTo(mouse.x, mouse.y)
        context.strokeStyle = `rgba(100,200,255,${alpha})`
        context.lineWidth = 1.1
        context.stroke()
      }
    }

    const drawParticles = () => {
      for (const particle of particles) {
        particle.x += particle.vx * Math.max(0.1, speedMultiplier)
        particle.y += particle.vy * Math.max(0.1, speedMultiplier)
        wrapParticle(particle)

        context.beginPath()
        context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2)
        context.fillStyle = `rgba(${particle.color},${particle.opacity})`
        context.fill()
      }
    }

    const render = () => {
      context.clearRect(0, 0, width, height)

      if (!transparent) {
        const background = context.createLinearGradient(0, 0, width, height)
        background.addColorStop(0, '#080f1f')
        background.addColorStop(0.55, '#0a1330')
        background.addColorStop(1, '#120f2b')
        context.fillStyle = background
        context.fillRect(0, 0, width, height)

        const glowLeft = context.createRadialGradient(width * 0.18, height * 0.16, 0, width * 0.18, height * 0.16, width * 0.38)
        glowLeft.addColorStop(0, 'rgba(85, 110, 255, 0.16)')
        glowLeft.addColorStop(1, 'rgba(85, 110, 255, 0)')
        context.fillStyle = glowLeft
        context.fillRect(0, 0, width, height)

        const glowRight = context.createRadialGradient(width * 0.84, height * 0.2, 0, width * 0.84, height * 0.2, width * 0.28)
        glowRight.addColorStop(0, 'rgba(134, 92, 255, 0.14)')
        glowRight.addColorStop(1, 'rgba(134, 92, 255, 0)')
        context.fillStyle = glowRight
        context.fillRect(0, 0, width, height)
      }

      drawConnections()
      drawMouseConnections()
      drawParticles()

      animationFrameId = window.requestAnimationFrame(render)
    }

    const handleMouseMove = (event: MouseEvent) => {
      mouse.x = event.clientX
      mouse.y = event.clientY
      mouse.active = true
    }

    const handleMouseLeave = () => {
      mouse.active = false
    }

    const handleResize = () => {
      initializeParticles()
    }

    initializeParticles()
    render()

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseleave', handleMouseLeave)
    window.addEventListener('resize', handleResize)

    return () => {
      window.cancelAnimationFrame(animationFrameId)
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseleave', handleMouseLeave)
      window.removeEventListener('resize', handleResize)
    }
  }, [])

  return <canvas ref={canvasRef} className={`particle-canvas${transparent ? ' particle-canvas--transparent' : ''}`} aria-hidden="true" />
}
