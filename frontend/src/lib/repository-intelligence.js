// Pure functions deriving Overview-page intelligence from data already on
// the page (the day-2 repository analysis, plus whatever's already been
// cached by visiting other sections). Nothing here makes a network call --
// see components/RepositoryOverview.jsx for how these are wired up.

const NON_SOURCE_BASENAMES = new Set([
  'package-lock.json',
  'pnpm-lock.yaml',
  'yarn.lock',
  'bun.lockb',
  'Cargo.lock',
  'poetry.lock',
  'composer.lock',
  'Pipfile.lock',
  'go.sum',
  'package.json',
  'tsconfig.json',
])

// dist/, build/, coverage/, node_modules/ are already excluded from
// scanning entirely (see backend IGNORED_DIRS) -- vendor/ and generated/
// aren't, so they're the ones actually worth filtering here.
const NON_SOURCE_PATH_PREFIXES = ['vendor/', 'generated/']

// "Meaningful source" == an actual programming language, not a data/doc/
// config format -- a huge CSS file or JSON fixture isn't "application
// logic" any more than a lockfile is.
const SOURCE_LANGUAGES = new Set([
  'Python',
  'JavaScript',
  'TypeScript',
  'Go',
  'Rust',
  'Ruby',
  'PHP',
  'Java',
  'Kotlin',
  'Swift',
  'C',
  'C++',
  'C#',
  'Dart',
  'Vue',
  'Svelte',
])

// Machine-generated source -- OpenAPI/gRPC/protobuf client code and similar
// codegen output technically parses as "source" but isn't application logic
// anyone wrote or should review for responsibility boundaries.
const GENERATED_BASENAME_PATTERN = /\.(gen|generated|g|pb)\.[a-z]+$/i
const GENERATED_PATH_SEGMENT_PATTERN = /(^|\/)(generated|__generated__|\.generated)(\/|$)/i

export function isMeaningfulSourceFile(file) {
  const basename = file.path.split('/').pop()
  if (NON_SOURCE_BASENAMES.has(basename)) return false
  if (/\.min\.(js|css)$/.test(basename) || basename.endsWith('.map')) return false
  if (NON_SOURCE_PATH_PREFIXES.some((prefix) => file.path.startsWith(prefix))) return false
  if (GENERATED_BASENAME_PATTERN.test(basename) || GENERATED_PATH_SEGMENT_PATTERN.test(file.path)) return false
  return SOURCE_LANGUAGES.has(file.language)
}

export function findLargestSourceFile(files) {
  const candidates = files.filter(isMeaningfulSourceFile)
  if (candidates.length === 0) return null
  return candidates.reduce((largest, file) => (file.lines > largest.lines ? file : largest), candidates[0])
}

export function formatBytes(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

export function computeTopFolders(files) {
  const counts = new Map()
  for (const file of files) {
    const top = file.path.includes('/') ? file.path.split('/')[0] : '(root)'
    counts.set(top, (counts.get(top) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6)
}

// Data/doc formats that show up in `languages` but aren't a "technology" the
// repository is built with -- a repo full of Python shouldn't have its tech
// stack diluted by package.json/tsconfig.json being 16% "JSON".
const NON_TECH_STACK_LANGUAGES = new Set(['Other', 'JSON', 'YAML', 'Markdown'])

// Line-count share per language -- more meaningful than a raw file count
// (a handful of huge files can outweigh many tiny ones), and computable
// from data already on the page.
export function computeLanguageBreakdown(files) {
  const linesByLanguage = new Map()
  let totalLines = 0
  for (const file of files) {
    if (NON_TECH_STACK_LANGUAGES.has(file.language)) continue
    linesByLanguage.set(file.language, (linesByLanguage.get(file.language) ?? 0) + file.lines)
    totalLines += file.lines
  }
  return [...linesByLanguage.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([language, lines]) => ({
      language,
      lines,
      percent: totalLines > 0 ? Math.round((lines / totalLines) * 100) : 0,
    }))
}

const FRONTEND_MARKERS = new Set(['frontend', 'client', 'web'])
const BACKEND_MARKERS = new Set(['backend', 'server', 'api'])

// Mirrors the backend's own layer-guessing heuristic (graph_builder.py) --
// only claims a frontend/backend split when the repo's own top-level
// folder names make it unambiguous, never invented.
function guessLayerLineShare(files) {
  const topDirs = new Set(files.map((f) => (f.path.includes('/') ? f.path.split('/')[0] : '.')))
  const hasFrontend = [...topDirs].some((d) => FRONTEND_MARKERS.has(d))
  const hasBackend = [...topDirs].some((d) => BACKEND_MARKERS.has(d))
  if (!hasFrontend || !hasBackend) return null

  let frontendLines = 0
  let backendLines = 0
  let totalLines = 0
  for (const file of files) {
    const top = file.path.includes('/') ? file.path.split('/')[0] : '.'
    totalLines += file.lines
    if (FRONTEND_MARKERS.has(top)) frontendLines += file.lines
    else if (BACKEND_MARKERS.has(top)) backendLines += file.lines
  }
  if (totalLines === 0) return null
  return { frontendPercent: Math.round((frontendLines / totalLines) * 100), backendPercent: Math.round((backendLines / totalLines) * 100) }
}

const FRONTEND_FRAMEWORKS = ['React', 'Vue.js', 'Angular', 'Svelte', 'Next.js']
const BUILD_TOOLS = ['Vite', 'Next.js']
const DATA_FETCHING = ['React Query', 'Axios']
const BACKEND_FRAMEWORKS = ['FastAPI', 'Express', 'Django', 'Flask', 'NestJS']

function joinWithAnd(items) {
  if (items.length <= 1) return items.join('')
  if (items.length === 2) return items.join(' and ')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

function describeFrontendStack(frameworks) {
  const framework = FRONTEND_FRAMEWORKS.find((name) => frameworks.includes(name))
  if (!framework) return null
  const extras = [...BUILD_TOOLS, ...DATA_FETCHING].filter((name) => name !== framework && frameworks.includes(name))
  const body = extras.length > 0 ? `The frontend uses ${framework} with ${joinWithAnd(extras)}.` : `The frontend uses ${framework}.`
  return { title: `${framework} frontend`, body }
}

function describeBackendStack(frameworks) {
  const framework = BACKEND_FRAMEWORKS.find((name) => frameworks.includes(name))
  if (!framework) return null
  return { title: `${framework} backend`, body: `The backend is built with ${framework}.` }
}

// Every insight is derived from data already on screen (or already cached
// from a section the user visited) -- never invented. Capped at 5.
export function buildInsights(data, gitSummary, healthCache) {
  const insights = []
  const { languages, frameworks, files } = data

  const layerShare = guessLayerLineShare(files)
  if (layerShare && Math.max(layerShare.frontendPercent, layerShare.backendPercent) >= 60) {
    const heavier = layerShare.backendPercent >= layerShare.frontendPercent ? 'backend' : 'frontend'
    const percent = heavier === 'backend' ? layerShare.backendPercent : layerShare.frontendPercent
    insights.push({ title: `${heavier[0].toUpperCase()}${heavier.slice(1)}-heavy architecture`, body: `${percent}% of the source code is concentrated in the ${heavier}.` })
  } else {
    const languageEntries = Object.entries(languages)
    if (languageEntries.length > 0) {
      const [topLanguage, topCount] = languageEntries[0]
      const share = Math.round((topCount / data.total_files) * 100)
      if (share >= 40) {
        insights.push({ title: `Primarily ${topLanguage}`, body: `${share}% of the ${data.total_files} analyzed files are ${topLanguage}.` })
      }
    }
  }

  const frontendStack = describeFrontendStack(frameworks)
  if (frontendStack) insights.push(frontendStack)

  const backendStack = describeBackendStack(frameworks)
  if (backendStack) insights.push(backendStack)

  const largestSource = findLargestSourceFile(files)
  if (largestSource && largestSource.lines >= 200) {
    insights.push({
      title: 'Large source module',
      body: `${largestSource.path} is ${largestSource.lines.toLocaleString()} lines -- worth reviewing for responsibility boundaries.`,
    })
  }

  const topFolders = computeTopFolders(files)
  const bigFolders = topFolders.filter(([, count]) => count >= 10)
  if (bigFolders.length >= 3) {
    const names = bigFolders.slice(0, 3).map(([name]) => name)
    insights.push({ title: 'Multi-package structure', body: `${names.join(', ')} are each substantial, independently-organized areas of the codebase.` })
  }

  if (healthCache?.findings?.length > 0) {
    const top = healthCache.findings[0]
    insights.push({ title: top.severity === 'high' ? 'Potential hotspot' : 'Worth reviewing', body: top.reason })
  }

  if (gitSummary?.has_git_history && gitSummary.activity.most_modified_files.length > 0) {
    const [hotFile] = gitSummary.activity.most_modified_files
    insights.push({ title: 'High-change area', body: `${hotFile.path} has changed frequently across recent commits (${hotFile.commit_count} commits).` })
  }

  return insights.slice(0, 5)
}

const BASE_QUESTIONS = ['What is this repository about?', 'How is the project structured?', 'What are the most important files?']

const FRONTEND_FRAMEWORK_NAMES = new Set(['React', 'Vue.js', 'Angular', 'Svelte', 'Next.js'])
const BACKEND_FRAMEWORK_NAMES = new Set(['FastAPI', 'Express', 'Django', 'Flask', 'NestJS'])

// Only suggests questions the repository can plausibly answer -- e.g. never
// suggests "how does authentication work" for a repo with nothing
// auth-shaped in it. Falls back to the base questions if nothing else applies.
export function buildSuggestedQuestions(data, codeIntelligence) {
  const questions = [...BASE_QUESTIONS]
  const paths = data.files.map((f) => f.path.toLowerCase())
  const frameworks = new Set(data.frameworks)

  const hasFrontend = [...frameworks].some((f) => FRONTEND_FRAMEWORK_NAMES.has(f))
  const hasBackend = [...frameworks].some((f) => BACKEND_FRAMEWORK_NAMES.has(f))
  if (hasFrontend && hasBackend) {
    questions.push('How does the frontend communicate with the backend?')
  }

  if (paths.some((p) => p.includes('auth'))) {
    questions.push('Where is authentication implemented?')
  }

  const routeCount = codeIntelligence?.routes?.length ?? 0
  if (routeCount > 0) {
    questions.push('Where are the API routes defined?')
  }

  if (paths.some((p) => /(database|models?\/|schema|migrations?)/.test(p))) {
    questions.push('Where is database access handled?')
  }

  if (data.frameworks.length > 0) {
    questions.push('What are the most important dependencies?')
  }

  return questions.slice(0, 6)
}
