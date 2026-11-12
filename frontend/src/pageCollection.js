// Chrome may return no result when injection fails or the page navigates.
// Give both Preview and Analyze an explicit error instead of an empty update.
export async function collectPageContext(chromeApi, tabId, collector, timeoutMs = 10000) {
  if (!Number.isInteger(tabId)) throw new Error('No LeetCode tab selected. Return to the problem and reopen the panel.')
  let timer
  try {
    const results = await Promise.race([
      chromeApi.scripting.executeScript({ target: { tabId }, world: 'MAIN', func: collector }),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('Reading the page timed out. Refresh LeetCode and reopen the extension.')), timeoutMs)
      }),
    ])
    const result = results?.find((r) => r.frameId === 0) || results?.[0]
    if (result?.error) throw new Error('Chrome could not run the page reader. Refresh LeetCode and reload the extension.')
    if (!result?.result || typeof result.result !== 'object') {
      throw new Error('Chrome returned no page data. Reload the extension, refresh LeetCode, then try Preview again.')
    }
    return result.result
  } finally {
    clearTimeout(timer)
  }
}
