/*  Ready Player Me 3D Avatar
    Loads GLB from Ready Player Me and renders with:
    • Idle head-bob + sway
    • Random eye-blink (morph targets)
    • Speaking mouth animation
  • Context-aware animation states (idle/greeting/computing/speaking/celebrating)
    • Professional 3-light studio setup + particles
*/

import { useRef, useEffect, useState } from 'react'
import * as THREE from 'three'
// @ts-expect-error - GLTFLoader not in main three types
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader'

const AVATAR_MODEL_URLS = Array.from(new Set([
  `${import.meta.env.BASE_URL}assets/avatar.glb`,
  '/assets/avatar.glb',
  'assets/avatar.glb',
  './assets/avatar.glb',
]))

/* ── Public interface ──────────────────── */
export interface AvatarPrompt {
  text?: string
  language?: string
  intent?: string
  avatar?: { expression?: string; gesture?: string }
}

interface AvatarProps {
  isSpeaking?: boolean
  prompt?: AvatarPrompt | null
  className?: string
  animationState?: 'idle' | 'greeting' | 'computing' | 'speaking' | 'celebrating'
}

/* ══════════════════════════════════════════
   Avatar Component (Ready Player Me GLB)
══════════════════════════════════════════ */
export function Avatar({ isSpeaking = false, prompt, className, animationState = 'idle' }: AvatarProps) {
  const mountRef         = useRef<HTMLDivElement>(null)
  const speakRef         = useRef(isSpeaking)
  const exprRef          = useRef(prompt?.avatar?.expression ?? 'neutral')
  const animStateRef     = useRef(animationState)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => { speakRef.current = isSpeaking }, [isSpeaking])
  useEffect(() => { exprRef.current = prompt?.avatar?.expression ?? 'neutral' }, [prompt])
  useEffect(() => { animStateRef.current = animationState }, [animationState])

  useEffect(() => {
    const el = mountRef.current
    if (!el) return
    setLoadError(false)
    let disposed = false

    const W = el.clientWidth  || 320
    const H = el.clientHeight || 400

    /* ── Renderer ──────────────────────────── */
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(W, H)
    renderer.shadowMap.enabled   = true
    renderer.shadowMap.type      = THREE.PCFSoftShadowMap
    renderer.toneMapping         = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.1
    el.appendChild(renderer.domElement)

    /* ── Scene / Camera ────────────────────── */
    const scene  = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 50)
    camera.position.set(0, 1.42, 1.08)
    camera.lookAt(0, 1.46, 0)

    /* ── Lighting ──────────────────────────── */
    scene.add(new THREE.AmbientLight(0x2a3550, 3.4))

    const keyL = new THREE.DirectionalLight(0xfff5e8, 2.8)
    keyL.position.set(-1.8, 2.2, 1.6)
    keyL.castShadow = true
    scene.add(keyL)

    const fillL = new THREE.DirectionalLight(0xd0e8ff, 1.1)
    fillL.position.set(2.0, 0.8, 1.2)
    scene.add(fillL)

    const rimL = new THREE.DirectionalLight(0xb8c6ff, 1.9)
    rimL.position.set(0, 2.1, -2.2)
    scene.add(rimL)

    const accentL = new THREE.PointLight(0xff9060, 0.5, 4)
    accentL.position.set(1.2, 0.6, 1.2)
    scene.add(accentL)

    /* ── Background particles ──────────────── */
    const pCount = 85
    const pGeo   = new THREE.BufferGeometry()
    const pPos   = new Float32Array(pCount * 3)
    for (let i = 0; i < pCount; i++) {
      pPos[i * 3]     = (Math.random() - 0.5) * 8
      pPos[i * 3 + 1] = (Math.random() - 0.5) * 8
      pPos[i * 3 + 2] = (Math.random() - 0.5) * 3.5 - 2
    }
    pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3))
    const particles = new THREE.Points(pGeo, new THREE.PointsMaterial({
      color: 0x5a78ff, size: 0.05, sizeAttenuation: true, transparent: true, opacity: 0.5,
    }))
    scene.add(particles)

    const root = new THREE.Group()
    scene.add(root)

    /* ── State managed per-frame ───────────── */
    type BlinkPhase = 'open' | 'closing' | 'closed' | 'opening'
    let blinkPhase: BlinkPhase = 'open'
    let blinkT    = 0
    let nextBlink = 2 + Math.random() * 3
    let speakPhase = 0
    let frameId    = 0
    const clock    = new THREE.Clock()

    let modelRoot: THREE.Group | null = null

    // Direct bone references populated after load
    let rightArmBone:     THREE.Bone | null = null
    let rightForeArmBone: THREE.Bone | null = null
    let rightHandBone:    THREE.Bone | null = null
    let leftArmBone:      THREE.Bone | null = null
    let leftForeArmBone:  THREE.Bone | null = null
    let headBone:         THREE.Bone | null = null

    // Bind-pose quaternions so we can return to rest
    let rArmQ0:  THREE.Quaternion | null = null
    let rForeQ0: THREE.Quaternion | null = null
    let rHandQ0: THREE.Quaternion | null = null
    let lArmQ0:  THREE.Quaternion | null = null
    let lForeQ0: THREE.Quaternion | null = null
    let headQ0:  THREE.Quaternion | null = null

    // Phase counters per animation
    let greetPhase = 0
    let typePhase  = 0
    let speakGesturePhase = 0
    let celebPhase = 0
    let prevState  = 'idle'

    const _q = new THREE.Quaternion()
    const _e = new THREE.Euler()

    function targetBone(bone: THREE.Bone | null, init: THREE.Quaternion | null, ex: number, ey: number, ez: number, alpha: number) {
      if (!bone || !init) return
      _e.set(ex, ey, ez)
      _q.setFromEuler(_e)
      _q.premultiply(init)
      bone.quaternion.slerp(_q, alpha)
    }
    function resetBone(bone: THREE.Bone | null, init: THREE.Quaternion | null, alpha = 0.08) {
      if (bone && init) bone.quaternion.slerp(init, alpha)
    }

    function normalizeBoneName(name: string) {
      return name.toLowerCase().replace(/[^a-z]/g, '')
    }

    /* ── Load GLB ──────────────────────────── */
    const loader = new GLTFLoader()
    const loadModelAt = (urlIndex: number) => {
      const modelUrl = AVATAR_MODEL_URLS[urlIndex]
      if (!modelUrl) {
        if (!disposed) setLoadError(true)
        return
      }

      loader.load(
        modelUrl,
        (gltf: any) => {
          if (disposed) return
          const model = gltf.scene
          root.add(model)
          modelRoot = model
          setLoadError(false)

          model.traverse((n: any) => {
            if (n instanceof THREE.Mesh) {
              n.castShadow    = true
              n.receiveShadow = true
            }
          })

          // Find and store bone references + bind-pose quaternions
          model.traverse((n: any) => {
            if (!n.isBone) return
            const nm = normalizeBoneName(n.name)
            if (nm.includes('rightforearm') && !rightForeArmBone) { rightForeArmBone = n; rForeQ0 = n.quaternion.clone() }
            if (nm.includes('rightarm') && !nm.includes('forearm') && !rightArmBone) { rightArmBone = n; rArmQ0 = n.quaternion.clone() }
            if (nm.includes('righthand') && !rightHandBone)       { rightHandBone    = n; rHandQ0 = n.quaternion.clone() }
            if (nm.includes('leftforearm') && !leftForeArmBone)   { leftForeArmBone  = n; lForeQ0 = n.quaternion.clone() }
            if (nm.includes('leftarm') && !nm.includes('forearm') && !leftArmBone) { leftArmBone = n; lArmQ0 = n.quaternion.clone() }
            if (nm.endsWith('head') && !headBone)                 { headBone         = n; headQ0  = n.quaternion.clone() }
          })
        },
        undefined,
        (error: any) => {
          if (disposed) return
          console.warn(`Avatar load failed at ${modelUrl}:`, error)
          loadModelAt(urlIndex + 1)
        }
      )
    }

    loadModelAt(0)

    /* ── Animate ───────────────────────────── */
    function animate() {
      frameId = requestAnimationFrame(animate)
      const dt = clock.getDelta()
      const t  = clock.elapsedTime

      const st = animStateRef.current

      // Reset phase counters on state change
      if (st !== prevState) {
        greetPhase = typePhase = speakGesturePhase = celebPhase = 0
        prevState = st
      }

      /* idle head sway */
      if (modelRoot) {
        modelRoot.rotation.y = Math.sin(t * 0.5) * 0.14
        modelRoot.rotation.x = 0
        modelRoot.position.y = 0
      }

      /* ── BONE ANIMATIONS ──────────────────── */
      if (st === 'greeting' && rArmQ0 && rForeQ0) {
        greetPhase += dt * 3.0
        const wave = Math.sin(greetPhase)
        // Simple, safe pose: arm lifted near shoulder level
        if (rightArmBone) targetBone(rightArmBone, rArmQ0, -0.32, 0.10, -1.05, 0.12)
        // Small forearm wave so it reads as "hi" without extreme bends
        if (rightForeArmBone) targetBone(rightForeArmBone, rForeQ0, 0.12, 0, 0.45 + wave * 0.35, 0.14)
        // Very subtle wrist movement
        if (rightHandBone) targetBone(rightHandBone, rHandQ0, 0, 0, wave * 0.18, 0.14)
        // gentle friendly head nod/tilt
        if (headBone && headQ0) targetBone(headBone, headQ0, 0, -0.08, 0.04, 0.1)
        // keep left arm at rest
        resetBone(leftArmBone, lArmQ0)
        resetBone(leftForeArmBone, lForeQ0)
      } else if (st === 'computing' && rArmQ0 && lArmQ0) {
        typePhase += dt * 7
        // Both arms forward and down (typing posture)
        if (rightArmBone)     targetBone(rightArmBone,     rArmQ0,  0.55,  0, -0.2, 0.1)
        if (rightForeArmBone) targetBone(rightForeArmBone, rForeQ0, 0,     0, Math.sin(typePhase + 1.1) * 0.07, 0.12)
        if (leftArmBone)      targetBone(leftArmBone,      lArmQ0,  0.55,  0,  0.2, 0.1)
        if (leftForeArmBone)  targetBone(leftForeArmBone,  lForeQ0, 0,     0, Math.sin(typePhase) * 0.07, 0.12)
        // slight look-down
        if (headBone && headQ0) targetBone(headBone, headQ0, 0, 0, 0, 0.06)
      } else if (st === 'speaking' && (rArmQ0 || lArmQ0)) {
        speakGesturePhase += dt * 4.6
        const gesture = Math.sin(speakGesturePhase)
        const counter = Math.sin(speakGesturePhase + 1.3)
        if (rightArmBone)     targetBone(rightArmBone,     rArmQ0,  -0.18, 0.04, -0.56 + gesture * 0.12, 0.12)
        if (rightForeArmBone) targetBone(rightForeArmBone, rForeQ0,  0.10, 0.00,  0.34 + gesture * 0.18, 0.14)
        if (rightHandBone)    targetBone(rightHandBone,    rHandQ0,  0.00, 0.00,  gesture * 0.10, 0.14)
        if (leftArmBone)      targetBone(leftArmBone,      lArmQ0,  -0.10, 0.00,  0.28 + counter * 0.08, 0.10)
        if (leftForeArmBone)  targetBone(leftForeArmBone,  lForeQ0,  0.04, 0.00, -0.18 + counter * 0.08, 0.10)
        if (headBone && headQ0) targetBone(headBone, headQ0, -0.04 + Math.sin(speakGesturePhase * 1.2) * 0.03, -0.03, 0.02, 0.12)
      } else if (st === 'celebrating' && rArmQ0 && lArmQ0) {
        celebPhase += dt * 4
        const swing = Math.sin(celebPhase * 2) * 0.25
        // Both arms raised and wiggling
        if (rightArmBone)     targetBone(rightArmBone,     rArmQ0,  -0.3, 0, -1.85 + swing, 0.12)
        if (rightForeArmBone) targetBone(rightForeArmBone, rForeQ0,  0,   0,  0.35, 0.1)
        if (leftArmBone)      targetBone(leftArmBone,      lArmQ0,  -0.3, 0,  1.85 - swing, 0.12)
        if (leftForeArmBone)  targetBone(leftForeArmBone,  lForeQ0,  0,   0, -0.35, 0.1)
        if (headBone && headQ0) targetBone(headBone, headQ0, -0.15, 0, 0, 0.06)
      } else {
        // IDLE – return all bones to bind pose
        resetBone(rightArmBone,     rArmQ0)
        resetBone(rightForeArmBone, rForeQ0)
        resetBone(rightHandBone,    rHandQ0)
        resetBone(leftArmBone,      lArmQ0)
        resetBone(leftForeArmBone,  lForeQ0)
        resetBone(headBone,         headQ0)
      }

      // Fallback visible motion when arm rig is not detected
      if (modelRoot && (!rightArmBone || !rightForeArmBone)) {
        if (st === 'greeting') {
          modelRoot.rotation.y += Math.sin(t * 3.2) * 0.14
          modelRoot.rotation.x = 0
        } else if (st === 'computing') {
          modelRoot.rotation.x = 0
          modelRoot.rotation.y += Math.sin(t * 4.0) * 0.04
        } else if (st === 'speaking') {
          modelRoot.rotation.x = Math.sin(t * 2.8) * 0.025
          modelRoot.rotation.y += Math.sin(t * 2.4) * 0.05
          modelRoot.position.y = Math.sin(t * 3.2) * 0.015
        } else if (st === 'celebrating') {
          modelRoot.rotation.y += Math.sin(t * 6.0) * 0.16
        }
      }

      /* speaking morph */
      if (modelRoot && speakRef.current) {
        speakPhase += dt * 7.5
        const amt = Math.abs(Math.sin(speakPhase)) * 0.14 + 0.04
        modelRoot.traverse((n: any) => {
          if (n instanceof THREE.Mesh && n.morphTargetInfluences && n.morphTargetDictionary) {
            const dict = n.morphTargetDictionary as Record<string, number>
            const targets = ['mouthOpen', 'jawOpen', 'visemes_PP', 'visemes_AA']
            targets.forEach(name => {
              if (name in dict) {
                n.morphTargetInfluences![dict[name]] = amt
              }
            })
          }
        })
      } else if (modelRoot) {
        modelRoot.traverse((n: any) => {
          if (n instanceof THREE.Mesh && n.morphTargetInfluences && n.morphTargetDictionary) {
            const dict = n.morphTargetDictionary as Record<string, number>
            const targets = ['mouthOpen', 'jawOpen', 'visemes_PP', 'visemes_AA']
            targets.forEach(name => {
              if (name in dict) {
                n.morphTargetInfluences![dict[name]] = THREE.MathUtils.lerp(
                  n.morphTargetInfluences![dict[name]],
                  0,
                  0.18
                )
              }
            })
          }
        })
      }

      /* blink */
      const BS = 8
      nextBlink -= dt
      if (nextBlink <= 0 && blinkPhase === 'open') { blinkPhase = 'closing'; blinkT = 0 }
      if (blinkPhase === 'closing') {
        blinkT += dt * BS
        if (blinkT >= 1) { blinkT = 1; blinkPhase = 'closed'; nextBlink = 0.08 }
      } else if (blinkPhase === 'closed') {
        nextBlink -= dt
        if (nextBlink <= 0) { blinkPhase = 'opening'; blinkT = 1 }
      } else if (blinkPhase === 'opening') {
        blinkT -= dt * BS
        if (blinkT <= 0) { blinkT = 0; blinkPhase = 'open'; nextBlink = 2 + Math.random() * 3 }
      }
      if (modelRoot) {
        modelRoot.traverse((n: any) => {
          if (n instanceof THREE.Mesh && n.morphTargetInfluences && n.morphTargetDictionary) {
            const dict = n.morphTargetDictionary as Record<string, number>
            const keys = ['eyeBlinkLeft', 'eyeBlinkRight']
            keys.forEach(k => {
              if (k in dict) {
                n.morphTargetInfluences![dict[k]] = blinkT
              }
            })
          }
        })
      }

      /* particles drift */
      const pp = pGeo.attributes.position as THREE.BufferAttribute
      for (let i = 0; i < pCount; i++) {
        ;(pp.array as Float32Array)[i * 3 + 1] += dt * 0.04
        if ((pp.array as Float32Array)[i * 3 + 1] > 4) {
          ;(pp.array as Float32Array)[i * 3 + 1] = -4
        }
      }
      pp.needsUpdate = true
      particles.rotation.y += dt * 0.015

      renderer.render(scene, camera)
    }
    animate()

    /* ── Resize ────────────────────────────── */
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth
      const h = el.clientHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    })
    ro.observe(el)

    /* ── Cleanup ───────────────────────────── */
    return () => {
      disposed = true
      cancelAnimationFrame(frameId)
      ro.disconnect()
      renderer.dispose()
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement)
    }
  }, [])

  if (loadError) {
    return (
      <div className={['avatar-unavailable', className].filter(Boolean).join(' ')}>
        Avatar unavailable
      </div>
    )
  }

  return (
    <div
      ref={mountRef}
      className={['avatar-3d-root', className].filter(Boolean).join(' ')}
      aria-label="3D animated female tax assistant"
      role="img"
    />
  )
}

export default Avatar