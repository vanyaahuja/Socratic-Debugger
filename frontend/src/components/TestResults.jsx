/**
 * Renders pass/fail per test. For hidden tests we only ever have
 * {test_identifier, passed, hidden} from the API (no actual_output) --
 * this component can't leak what it was never given.
 */
export default function TestResults({ result }) {
  if (!result) return null

  return (
    <div>
      <p>
        <strong>{result.tests_passed} / {result.tests_total}</strong> tests passed
        {result.solved && ' — solved!'}
      </p>
      {result.compiler_error && (
        <pre style={{ color: 'crimson', whiteSpace: 'pre-wrap' }}>{result.compiler_error}</pre>
      )}
      {result.runtime_error && (
        <pre style={{ color: 'crimson', whiteSpace: 'pre-wrap' }}>{result.runtime_error}</pre>
      )}
      <ul>
        {result.test_results.map((t) => (
          <li key={t.test_identifier} style={{ color: t.passed ? 'green' : 'crimson' }}>
            {t.hidden ? 'Hidden test' : t.test_identifier}: {t.passed ? 'passed' : 'failed'}
          </li>
        ))}
      </ul>
    </div>
  )
}
