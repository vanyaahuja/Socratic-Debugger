import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ExtensionApp from './ExtensionApp'

// Same React bundle: inside the Chrome side panel render the extension UI,
// in a normal browser tab keep the original local practice UI.
const inExtension = typeof chrome !== 'undefined' && !!chrome.runtime?.id
const Root = inExtension ? ExtensionApp : App

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
)
