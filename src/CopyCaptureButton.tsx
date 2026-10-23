import { useState } from 'react'

export async function copyCaptureText(text: string, clipboard: Pick<Clipboard, 'writeText'> | undefined): Promise<void> {
  if (!clipboard) throw Error('Copy is unavailable here. Select the text and choose Copy.')
  await clipboard.writeText(text)
}

export function CopyCaptureButton({ text }: { text: string }) {
  const [notice, setNotice] = useState('')
  return <span className="copy-capture"><button type="button" className="secondary" onClick={async () => {
    try { await copyCaptureText(text, navigator.clipboard); setNotice('Copied') }
    catch { setNotice('Select the text to copy it manually.') }
  }}>Copy text</button><span role="status">{notice}</span></span>
}
