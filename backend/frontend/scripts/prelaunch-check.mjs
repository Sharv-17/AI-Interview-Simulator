// Run with: npm run check:launch
// Fails (exit code 1) if anything on the launch checklist is not done.

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const root = new URL('..', import.meta.url).pathname
const problems = []

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    return statSync(full).isDirectory() ? walk(full) : [full]
  })
}

// 1. Site settings filled in (operator, contact email, domain, policy date...).
const config = readFileSync(join(root, 'src/siteConfig.js'), 'utf8')
const todos = config.split('\n').filter((line) => line.includes("'TODO_"))
if (todos.length) problems.push(`src/siteConfig.js still has ${todos.length} TODO value(s).`)

// 2. Favicon files present and linked.
for (const file of ['public/favicon.svg', 'public/favicon.ico', 'public/apple-touch-icon.png']) {
  if (!existsSync(join(root, file))) problems.push(`Missing ${file}.`)
}
const html = readFileSync(join(root, 'index.html'), 'utf8')
if (!html.includes('rel="icon"')) problems.push('index.html does not link a favicon.')
if (/<title>\s*(frontend|vite[^<]*)\s*<\/title>/i.test(html)) problems.push('index.html still has the default title.')

// 3. Privacy policy and terms pages routed.
const app = readFileSync(join(root, 'src/App.jsx'), 'utf8')
if (!app.includes('path="privacy"')) problems.push('No /privacy route in src/App.jsx.')
if (!app.includes('path="terms"')) problems.push('No /terms route in src/App.jsx.')

// 4. Production API URL set (custom domain for the backend).
const prodEnv = join(root, '.env.production')
if (!existsSync(prodEnv) || !/VITE_API_BASE_URL=https:\/\/\S+/.test(readFileSync(prodEnv, 'utf8'))) {
  problems.push('Create .env.production with VITE_API_BASE_URL=https://... (see .env.example).')
}

// 5. Text rules across source files.
const files = [join(root, 'index.html'), ...walk(join(root, 'src'))].filter((f) => /\.(jsx?|html|css)$/.test(f))
for (const file of files) {
  const text = readFileSync(file, 'utf8')
  const rel = file.replace(root, '')
  if (/made with|built with|powered by/i.test(text)) problems.push(`${rel}: contains a "made with / built with / powered by" tag.`)
  if (text.includes('\u2014')) problems.push(`${rel}: contains an em dash.`)
  if (/lorem ipsum/i.test(text)) problems.push(`${rel}: contains placeholder text.`)
  if (/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(text)) problems.push(`${rel}: contains an emoji.`)
}

if (problems.length) {
  console.error('Not ready to launch:\n')
  for (const p of problems) console.error(`  - ${p}`)
  console.error('\nAlso check by hand: custom domain connected with HTTPS, backend CORS allows your domain.')
  process.exit(1)
}
console.log('Launch checklist passed. Also confirm the custom domain loads over HTTPS.')
