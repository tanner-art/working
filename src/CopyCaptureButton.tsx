import { useRef, useState } from 'react'

export async function copyCaptureText(text: string, clipboard: Pick<Clipboard, 'writeText'> | undefined): Promise<void> {
  if (!clipboard) throw Error('Copy is unavailable here. Select the text and choose Copy.')
  await clipboard.writeText(text)
}

export function CopyCaptureButton({ text }: { text: string }) {
  const [notice, setNotice] = useState<{ text: string; message: string } | null>(null)
  const request = useRef(0)
  return <span className="copy-capture"><button type="button" className="secondary" onClick={async () => {
    const current = ++request.current
    setNotice(null)
    try { await copyCaptureText(text, navigator.clipboard); if (request.current === current) setNotice({ text, message: 'Copied' }) }
    catch { if (request.current === current) setNotice({ text, message: 'Select the text to copy it manually.' }) }
  }}>Copy text</button><span role="status">{notice?.text === text ? notice.message : ''}</span></span>
}
