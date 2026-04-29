export function openExternalUrl(url: string) {
  const nativeBridge = (window as unknown as {
    webkit?: {
      messageHandlers?: {
        secondBrainNative?: {
          postMessage: (payload: { type: string; url: string }) => void
        }
      }
    }
  }).webkit?.messageHandlers?.secondBrainNative

  if (nativeBridge) {
    nativeBridge.postMessage({ type: 'openExternal', url })
    return
  }

  window.open(url, '_blank', 'noopener,noreferrer')
}
