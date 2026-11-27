// Run with: npm run check:launch
// Fails (exit code 1) if anything on the launch checklist is not done.

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

// fileURLToPath, not URL.pathname: on Windows the pathname keeps a leading slash and
// join() then produces an unusable E:\E:\... path.
const root = fileURLToPath(new URL('..', import.meta.url))
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

// 4. Production API base is either the same origin (recommended: /api, proxied by
// vercel.json) or an absolute https URL for a deliberately cross-origin backend.
const prodEnv = join(root, '.env.production')
const apiBaseOk =
  existsSync(prodEnv) &&
  /VITE_API_BASE_URL=(\/api|https:\/\/\S+)[ \t]*$/m.test(readFileSync(prodEnv, 'utf8'))
if (!apiBaseOk) {
  problems.push(
    'Create .env.production with VITE_API_BASE_URL=/api (same-origin proxy) or https://... (see .env.example).',
  )
}

// 4b. The proxy config must route the account API before the general /api rule, and
// keep the SPA fallback away from API paths.
const vercelPath = join(root, 'vercel.json')
if (!existsSync(vercelPath)) {
  problems.push('Missing vercel.json (reverse proxy and SPA rewrites).')
} else {
  let config = null
  try {
    config = JSON.parse(readFileSync(vercelPath, 'utf8'))
  } catch {
    problems.push('vercel.json is not valid JSON.')
  }
  if (config) {
    const rules = config.rewrites || []
    const sources = rules.map((rule) => rule.source)
    const v1Index = sources.findIndex((source) => source.startsWith('/api/v1'))
    const apiIndex = sources.findIndex(
      (source) => source.startsWith('/api/') && !source.startsWith('/api/v1'),
    )
    const spaIndex = rules.findIndex((rule) => String(rule.destination).includes('index.html'))
    if (v1Index === -1) problems.push('vercel.json: no /api/v1 rewrite.')
    if (apiIndex === -1) problems.push('vercel.json: no /api rewrite.')
    if (spaIndex === -1) problems.push('vercel.json: no SPA fallback rewrite.')
    if (v1Index !== -1 && apiIndex !== -1 && v1Index > apiIndex) {
      problems.push('vercel.json: the /api/v1 rewrite must come before the /api rewrite.')
    }
    if (apiIndex !== -1 && spaIndex !== -1 && apiIndex > spaIndex) {
      problems.push('vercel.json: API rewrites must come before the SPA fallback.')
    }
    const headers = config.headers || []
    if (!headers.some((rule) => (rule.source || '').startsWith('/api/v1'))) {
      problems.push('vercel.json: no cache-control header rule for /api/v1.')
    }
  }
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
