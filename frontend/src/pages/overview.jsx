import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Code2, Folder, FolderTree, Layers, Loader2, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import {
  SiAngular,
  SiApachemaven,
  SiAxios,
  SiC,
  SiComposer,
  SiCplusplus,
  SiCss,
  SiDart,
  SiDjango,
  SiExpress,
  SiFastapi,
  SiFlask,
  SiFlutter,
  SiGit,
  SiGnubash,
  SiGo,
  SiHtml5,
  SiJavascript,
  SiJson,
  SiKotlin,
  SiLess,
  SiMarkdown,
  SiMongoose,
  SiNestjs,
  SiNextdotjs,
  SiNumpy,
  SiPandas,
  SiPhp,
  SiPydantic,
  SiPython,
  SiReact,
  SiReactquery,
  SiRuby,
  SiRust,
  SiSass,
  SiSocketdotio,
  SiSqlalchemy,
  SiSvelte,
  SiSwift,
  SiTailwindcss,
  SiTypescript,
  SiVite,
  SiVuedotjs,
  SiYaml,
} from 'react-icons/si'

import { ApiError, askRepositoryQuestion, fetchGitSummary, generateRepositorySummary } from '@/api'
import { buildInsights, buildSuggestedQuestions, computeLanguageBreakdown, computeTopFolders } from '@/repository-intelligence'
import '../css/overview.css'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
}

// Maps the exact language/framework names the backend returns (see
// backend/app/analyzer/constants.py LANGUAGE_EXTENSIONS and
// app/analyzer/tech_stack_detector.py) to a real Simple Icons brand icon.
// Every key here was verified to exist in the installed react-icons/si
// package before being added -- an unmapped name just falls back to a
// generic icon rather than crashing on an undefined component.
const LANGUAGE_ICONS = {
  Python: SiPython,
  JavaScript: SiJavascript,
  TypeScript: SiTypescript,
  HTML: SiHtml5,
  CSS: SiCss,
  SCSS: SiSass,
  Sass: SiSass,
  Less: SiLess,
  JSON: SiJson,
  Markdown: SiMarkdown,
  YAML: SiYaml,
  Shell: SiGnubash,
  Go: SiGo,
  Rust: SiRust,
  Ruby: SiRuby,
  PHP: SiPhp,
  Kotlin: SiKotlin,
  Swift: SiSwift,
  C: SiC,
  'C++': SiCplusplus,
  Dart: SiDart,
  Vue: SiVuedotjs,
  Svelte: SiSvelte,
}

const FRAMEWORK_ICONS = {
  React: SiReact,
  'Next.js': SiNextdotjs,
  Express: SiExpress,
  Vite: SiVite,
  'Socket.IO': SiSocketdotio,
  Axios: SiAxios,
  Mongoose: SiMongoose,
  'Vue.js': SiVuedotjs,
  Angular: SiAngular,
  NestJS: SiNestjs,
  'Tailwind CSS': SiTailwindcss,
  'React Query': SiReactquery,
  FastAPI: SiFastapi,
  Flask: SiFlask,
  Django: SiDjango,
  NumPy: SiNumpy,
  Pandas: SiPandas,
  SQLAlchemy: SiSqlalchemy,
  Pydantic: SiPydantic,
  GitPython: SiGit,
  'PHP (Composer)': SiComposer,
  'Java (Maven)': SiApachemaven,
  'Dart/Flutter': SiFlutter,
}

function getLanguageIcon(name) {
  return LANGUAGE_ICONS[name] ?? null
}

function getFrameworkIcon(name) {
  return FRAMEWORK_ICONS[name] ?? null
}

// Original Simple Icons brand hex per technology, limited to values with
// enough contrast against the app's near-black background -- a handful of
// brand marks (Next.js, Express, Flask, Django, NumPy, Pandas...) are
// black or near-black and would be invisible here, so those are left
// unmapped and just keep the default muted icon treatment instead.
const BRAND_COLORS = {
  Python: '#3776AB',
  JavaScript: '#F7DF1E',
  TypeScript: '#3178C6',
  HTML: '#E34F26',
  CSS: '#1572B6',
  SCSS: '#CC6699',
  Sass: '#CC6699',
  Less: '#1D365D',
  Shell: '#4EAA25',
  Go: '#00ADD8',
  Ruby: '#CC342D',
  PHP: '#777BB4',
  Kotlin: '#7F52FF',
  Swift: '#F05138',
  C: '#A8B9CC',
  'C++': '#00599C',
  Dart: '#0175C2',
  Vue: '#4FC08D',
  Svelte: '#FF3E00',
  React: '#61DAFB',
  Vite: '#646CFF',
  Axios: '#5A29E4',
  Mongoose: '#880000',
  'Vue.js': '#4FC08D',
  Angular: '#DD0031',
  NestJS: '#E0234E',
  'Tailwind CSS': '#06B6D4',
  'React Query': '#FF4154',
  FastAPI: '#009688',
  SQLAlchemy: '#D71F00',
  Pydantic: '#E92063',
  GitPython: '#F05032',
  'PHP (Composer)': '#885630',
  'Java (Maven)': '#C71A36',
  'Dart/Flutter': '#02569B',
}

function getBrandColor(name) {
  return BRAND_COLORS[name]
}

const FRAMEWORK_CATEGORY = {
  React: 'Frameworks',
  'Next.js': 'Frameworks',
  'Vue.js': 'Frameworks',
  Angular: 'Frameworks',
  Svelte: 'Frameworks',
  Express: 'Frameworks',
  NestJS: 'Frameworks',
  FastAPI: 'Frameworks',
  Flask: 'Frameworks',
  Django: 'Frameworks',
  'Dart/Flutter': 'Frameworks',
  Axios: 'Libraries',
  Mongoose: 'Libraries',
  'React Query': 'Libraries',
  NumPy: 'Libraries',
  Pandas: 'Libraries',
  SQLAlchemy: 'Libraries',
  Pydantic: 'Libraries',
  'Tailwind CSS': 'Libraries',
  'Socket.IO': 'Libraries',
  Vite: 'Tooling',
  GitPython: 'Tooling',
  'PHP (Composer)': 'Tooling',
  'Java (Maven)': 'Tooling',
}
const CATEGORY_ORDER = ['Frameworks', 'Libraries', 'Infrastructure', 'Tooling']

function groupFrameworksByCategory(frameworks) {
  const groups = new Map()
  for (const framework of frameworks) {
    const category = FRAMEWORK_CATEGORY[framework] ?? 'Frameworks'
    if (!groups.has(category)) groups.set(category, [])
    groups.get(category).push(framework)
  }
  return CATEGORY_ORDER.filter((category) => groups.has(category)).map((category) => [category, groups.get(category)])
}

function TechIcon({ icon: Icon, size = 18, color }) {
  const style = color ? { color } : undefined
  return Icon ? <Icon size={size} style={style} /> : <Code2 size={size} style={style} />
}

// Overview's compact tech-stack presentation groups everything that isn't
// tooling under one "Frameworks & Libraries" heading -- the Frameworks vs.
// Libraries vs. Infrastructure split from groupFrameworksByCategory is more
// granularity than a glanceable pill row needs.
function mergeFrameworkGroups(frameworkGroups) {
  const merged = new Map()
  for (const [category, names] of frameworkGroups) {
    const label = category === 'Tooling' ? 'Tooling' : 'Frameworks & Libraries'
    if (!merged.has(label)) merged.set(label, [])
    merged.get(label).push(...names)
  }
  return [...merged.entries()]
}

const SUMMARY_LOADING_PHRASES = ['Analyzing architecture…', 'Understanding major modules…', 'Connecting dependencies…', 'Building explanation…']

function SummaryLoadingState() {
  const [phraseIndex, setPhraseIndex] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setPhraseIndex((index) => (index + 1) % SUMMARY_LOADING_PHRASES.length), 1600)
    return () => clearInterval(interval)
  }, [])
  return (
    <div className="summary-loading">
      <Loader2 className="spinner" size={16} />
      <span>{SUMMARY_LOADING_PHRASES[phraseIndex]}</span>
    </div>
  )
}

function SourcesList({ sources }) {
  if (sources.length === 0) return null
  return (
    <div className="sources">
      <p className="sources-title">Sources</p>
      <ul className="sources-list">
        {sources.map((source) => (
          <li key={source}>
            <button
              type="button"
              className="source-link"
              onClick={() => toast('File viewer is coming in a future update', { description: source })}
            >
              {source}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

// The single Ask CodeMap experience -- lives inline on Overview. `prefill`
// (an object `{ question, key }`) is how other pages hand it a
// context-specific question: bump `key` to force the effect even if the
// question text repeats, since a plain string wouldn't re-trigger.
function AskCodeMapPanel({ data, autoFocus = false, suggestionsLabel = 'Suggested questions', prefill }) {
  const [question, setQuestion] = useState('')
  const [conversation, setConversation] = useState([])
  const chat = useMutation({ mutationFn: askRepositoryQuestion })
  const queryClient = useQueryClient()
  const inputRef = useRef(null)

  const codeIntelligence = queryClient.getQueryData(['code-intelligence'])
  const suggestions = buildSuggestedQuestions(data, codeIntelligence)

  useEffect(() => {
    if (!prefill) return
    setQuestion(prefill.question)
    inputRef.current?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.key])

  function handleAsk(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || chat.isPending) return

    chat.mutate(
      { question: trimmed, mode: 'developer' },
      {
        onSuccess: (result) => {
          setConversation((prev) => [{ question: trimmed, ...result }, ...prev])
          setQuestion('')
        },
        onError: (error) => toast.error('Could not get an answer', { description: errorMessage(error) }),
      },
    )
  }

  return (
    <>
      <form onSubmit={handleAsk} className="ask-codemap-form">
        <input
          ref={inputRef}
          className="input ask-codemap-input"
          type="text"
          placeholder="Ask anything about this codebase…"
          value={question}
          disabled={chat.isPending}
          onChange={(event) => setQuestion(event.target.value)}
          autoFocus={autoFocus}
        />
        <button type="submit" className="btn btn-primary" disabled={chat.isPending || !question.trim()}>
          {chat.isPending ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      {conversation.length === 0 && (
        <div className="suggested-questions">
          <p className="sources-title">{suggestionsLabel}</p>
          <div className="suggested-question-grid">
            {suggestions.map((suggested) => (
              <button key={suggested} type="button" className="suggested-question" onClick={() => setQuestion(suggested)}>
                {suggested}
              </button>
            ))}
          </div>
        </div>
      )}

      {conversation.length > 0 && (
        <div className="conversation-list">
          {conversation.map((entry, index) => (
            <div className="conversation-entry" key={`${entry.question}-${index}`}>
              <p className="conversation-question">{entry.question}</p>
              <p className="conversation-answer">{entry.answer}</p>
              <SourcesList sources={entry.sources} />
            </div>
          ))}
        </div>
      )}
    </>
  )
}

// Hover-driven flex-grow per card, keyed by which card currently has focus.
// Repository structure is the default focus (center, slightly larger) --
// hovering (or tab-focusing) a card reassigns focus to it; leaving the
// carousel entirely falls back to 'structure'. Values stay close together
// on purpose (0.85-1.3) so the three cards always read as one composition
// rather than one card ballooning over the other two.
const FOCUS_GROW = {
  tech: { tech: 1.3, structure: 0.9, ai: 0.85 },
  structure: { tech: 0.88, structure: 1.28, ai: 0.88 },
  ai: { tech: 0.85, structure: 0.9, ai: 1.3 },
}

function IntelligenceCard({ id, focused, onFocus, headerIcon: HeaderIcon, title, children, footer }) {
  return (
    <div
      className={`intel-card${focused === id ? ' intel-card-focused' : ''}`}
      style={{ flexGrow: FOCUS_GROW[focused][id] }}
      onMouseEnter={() => onFocus(id)}
      onFocus={() => onFocus(id)}
      tabIndex={0}
    >
      <div className="intel-card-header">
        <HeaderIcon size={16} className="intel-card-icon" />
        <h3 className="intel-title">{title}</h3>
      </div>
      <div className="intel-card-body">{children}</div>
      {footer}
    </div>
  )
}

export function RepositoryOverview({ data, onExploreStructure, askPrefill }) {
  const [summaryMode, setSummaryMode] = useState('beginner')
  const [focusedCard, setFocusedCard] = useState('structure')
  const askSectionRef = useRef(null)

  // Other pages hand this a { question, key } via onAskAbout -- scrolling
  // the hero into view is this component's job (it owns the page layout);
  // AskCodeMapPanel owns filling in and focusing the input itself.
  useEffect(() => {
    if (!askPrefill) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    askSectionRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askPrefill?.key])

  // enabled: false -- this only ever runs when the user explicitly clicks
  // "Generate Summary" and calls refetch(). No AI call happens just from
  // viewing Overview, and no percentage/stage is faked while it's pending.
  const summary = useQuery({
    queryKey: ['repository-summary'],
    queryFn: generateRepositorySummary,
    retry: false,
    staleTime: Infinity,
    enabled: false,
  })
  const gitSummary = useQuery({ queryKey: ['git-summary'], queryFn: fetchGitSummary, retry: false })

  const { total_files, total_folders, frameworks, statistics } = data
  const topFolders = computeTopFolders(data.files)
  const languageBreakdown = computeLanguageBreakdown(data.files)
  const frameworkGroups = mergeFrameworkGroups(groupFrameworksByCategory(frameworks))
  const insights = buildInsights(data, gitSummary.data, null)
  const contributors = gitSummary.data?.has_git_history ? gitSummary.data.activity.contributors : null

  return (
    <div className="overview">
      <section className="overview-identity">
        <h1>{data.repository_name}</h1>
        <p className="card-subtitle">Repository analysis</p>
      </section>

      <section className="ask-codemap-hero" ref={askSectionRef}>
        <div className="ask-codemap-hero-header">
          <Sparkles size={18} />
          <h2>Ask CodeMap</h2>
        </div>
        <p className="ask-codemap-tagline">
          Your repository, explained. Ask questions about architecture, files, dependencies, implementation and
          behavior — grounded in what CodeMap actually found in this codebase.
        </p>
        <AskCodeMapPanel data={data} suggestionsLabel="Try asking" prefill={askPrefill} />
      </section>

      <div className="metrics-row">
        <span>
          <strong>{total_files}</strong> files
        </span>
        <span>
          <strong>{total_folders}</strong> folders
        </span>
        <span>
          <strong>{statistics.total_lines.toLocaleString()}</strong> lines
        </span>
        {contributors != null && (
          <span>
            <strong>{contributors}</strong> contributor{contributors === 1 ? '' : 's'}
          </span>
        )}
      </div>

      <section className="overview-block intelligence-block">
        <p className="intel-eyebrow">Repository intelligence</p>
        <div className="intelligence-carousel" onMouseLeave={() => setFocusedCard('structure')}>
          <IntelligenceCard id="tech" focused={focusedCard} onFocus={setFocusedCard} headerIcon={Layers} title="Tech stack">
            {languageBreakdown.length > 0 || frameworkGroups.length > 0 ? (
              <>
                {languageBreakdown.length > 0 && (
                  <div className="intel-lang-grid">
                    {languageBreakdown.map(({ language, percent }) => (
                      <div key={language} className="intel-lang-tile">
                        <TechIcon icon={getLanguageIcon(language)} size={22} color={getBrandColor(language)} />
                        <span className="intel-lang-name">{language}</span>
                        <span className="intel-lang-percent">{percent}%</span>
                      </div>
                    ))}
                  </div>
                )}

                {frameworkGroups.map(([category, names]) => (
                  <div key={category} className="intel-pill-section">
                    <p className="tech-group-label">{category}</p>
                    <div className="pill-row">
                      {names.map((name) => (
                        <span key={name} className="tech-pill">
                          <TechIcon icon={getFrameworkIcon(name)} size={14} color={getBrandColor(name)} />
                          {name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </>
            ) : (
              <p className="card-subtitle">No recognized languages or frameworks found.</p>
            )}
          </IntelligenceCard>

          <IntelligenceCard
            id="structure"
            focused={focusedCard}
            onFocus={setFocusedCard}
            headerIcon={FolderTree}
            title="Repository structure"
            footer={
              <button type="button" className="link-button intel-footer-link" onClick={onExploreStructure}>
                Explore structure →
              </button>
            }
          >
            {topFolders.length > 0 ? (
              <ul className="structure-tree">
                {topFolders.map(([name, count]) => (
                  <li key={name} className="structure-tree-row">
                    <Folder size={13} className="structure-tree-icon" />
                    <span className="structure-tree-name">{name === '(root)' ? name : `${name}/`}</span>
                    <span className="structure-tree-count">{count}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="card-subtitle">No files found.</p>
            )}
          </IntelligenceCard>

          <IntelligenceCard
            id="ai"
            focused={focusedCard}
            onFocus={setFocusedCard}
            headerIcon={Sparkles}
            title={summary.data && !summary.isFetching ? 'AI repository brief' : 'Understand this repository'}
          >
            {!summary.data && !summary.isFetching && (
              <div className="intel-ai-empty">
                <p className="card-subtitle">
                  Get an AI-generated explanation of the architecture, important modules, and how the major pieces
                  work together.
                </p>
                <button type="button" className="btn btn-outline mt-3" onClick={() => summary.refetch()}>
                  Generate AI brief →
                </button>
                {summary.isError && (
                  <p className="field-error mt-3">Could not generate a summary: {errorMessage(summary.error)}</p>
                )}
              </div>
            )}

            {summary.isFetching && <SummaryLoadingState />}

            {summary.data && !summary.isFetching && (
              <>
                <div className="mode-toggle">
                  <button
                    type="button"
                    className={summaryMode === 'beginner' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                    onClick={() => setSummaryMode('beginner')}
                  >
                    Beginner
                  </button>
                  <button
                    type="button"
                    className={summaryMode === 'developer' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                    onClick={() => setSummaryMode('developer')}
                  >
                    Developer
                  </button>
                </div>
                <p className="summary-text intel-summary-text">
                  {summaryMode === 'beginner' ? summary.data.beginner_summary : summary.data.developer_summary}
                </p>
                <button type="button" className="link-button mt-3" onClick={() => summary.refetch()}>
                  Regenerate
                </button>
              </>
            )}
          </IntelligenceCard>
        </div>
      </section>

      <section className="overview-block overview-block-tight">
        <h2>Engineering signals</h2>
        {insights.length > 0 ? (
          <ol className="insight-grid">
            {insights.map((insight, index) => (
              <li key={insight.title} className="insight-item">
                <span className="insight-index">{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <p className="insight-title">{insight.title}</p>
                  <p className="insight-body">{insight.body}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="card-subtitle">Nothing notable surfaced yet.</p>
        )}
      </section>
    </div>
  )
}
