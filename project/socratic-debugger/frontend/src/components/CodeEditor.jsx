/**
 * Deliberately a plain textarea for the scaffold. @monaco-editor/react is
 * already in package.json -- swap this component's internals for
 * <Editor language={language} value={code} onChange={...} /> when you're
 * ready; nothing else in the app needs to change since this component owns
 * the editor's props contract.
 */
export default function CodeEditor({ code, onChange, language }) {
  return (
    <textarea
      spellCheck={false}
      value={code}
      onChange={(e) => onChange(e.target.value)}
      style={{
        width: '100%',
        height: '320px',
        fontFamily: 'monospace',
        fontSize: '14px',
        padding: '12px',
        boxSizing: 'border-box',
      }}
      aria-label={`${language} code editor`}
    />
  )
}
