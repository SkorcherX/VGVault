import { useEffect, useRef, useState } from 'react'
import { Modal } from './components'

const FORMATS = ['upc_a', 'upc_e', 'ean_13', 'ean_8']

interface Detector {
  detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]>
}

/** Native BarcodeDetector where available (Chrome/Android), otherwise a bundled
 *  WebAssembly ponyfill. The wasm is served from this app, never a CDN. */
async function createDetector(): Promise<Detector> {
  const Native = (globalThis as { BarcodeDetector?: { new (o: object): Detector; getSupportedFormats(): Promise<string[]> } })
    .BarcodeDetector
  if (Native) {
    const supported = await Native.getSupportedFormats()
    if (FORMATS.some((f) => supported.includes(f))) return new Native({ formats: FORMATS })
  }
  const [{ BarcodeDetector, prepareZXingModule }, { default: wasmUrl }] = await Promise.all([
    import('barcode-detector/ponyfill'),
    import('zxing-wasm/reader/zxing_reader.wasm?url'),
  ])
  prepareZXingModule({
    overrides: { locateFile: (path: string, prefix: string) => (path.endsWith('.wasm') ? wasmUrl : prefix + path) },
  })
  return new BarcodeDetector({ formats: FORMATS as never })
}

/** Readers often report a UPC-A as EAN-13 with a leading 0; PriceCharting and stored UPCs use 12 digits. */
export const normalizeUpc = (code: string) => (code.length === 13 && code.startsWith('0') ? code.slice(1) : code)

export const cameraAvailable = () => window.isSecureContext && !!navigator.mediaDevices?.getUserMedia

export default function BarcodeScanner({ onDetected, onClose }: { onDetected: (code: string) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let stream: MediaStream | null = null
    let stopped = false
    let timer: number | undefined

    ;(async () => {
      try {
        const detector = await createDetector()
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } },
          audio: false,
        })
        if (stopped || !video.current) return
        video.current.srcObject = stream
        await video.current.play()
        setReady(true)
        const tick = async () => {
          if (stopped || !video.current) return
          try {
            const codes = await detector.detect(video.current)
            const code = codes.find((c) => /^\d{8,14}$/.test(c.rawValue))
            if (code) {
              stopped = true
              onDetected(normalizeUpc(code.rawValue))
              return
            }
          } catch {
            /* frame not ready */
          }
          timer = window.setTimeout(tick, 200)
        }
        tick()
      } catch (e) {
        const name = (e as { name?: string }).name
        setError(
          name === 'NotAllowedError'
            ? 'Camera permission was denied.'
            : name === 'NotFoundError'
              ? 'No camera found.'
              : `Could not start the scanner: ${e instanceof Error ? e.message : String(e)}`,
        )
      }
    })()

    return () => {
      stopped = true
      window.clearTimeout(timer)
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [onDetected])

  return (
    <Modal title="Scan barcode" onClose={onClose}>
      {error ? (
        <p className="error">{error}</p>
      ) : (
        <>
          <div className="scanner">
            <video ref={video} playsInline muted />
            <div className="scanner-guide" />
          </div>
          <p className="muted small">{ready ? 'Point the camera at the UPC barcode on the box.' : 'Starting camera…'}</p>
        </>
      )}
    </Modal>
  )
}
