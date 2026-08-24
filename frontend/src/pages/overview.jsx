import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ChevronUp, Code2, Folder, FolderTree, Layers, Loader2, Sparkles, X } from 'lucide-react'
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
import { buildSuggestedQuestions, computeLanguageBreakdown, computeTopFolders } from '@/repository-intelligence'
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

// The single Ask CodeMap experience -- a compact command bar on Overview
// that expands inline on focus/Cmd+K rather than a permanently-open card.
// `prefill` (an object `{ question, key }`) is how other pages hand it a
// context-specific question: bump `key` to force the effect even if the
// question text repeats, since a plain string wouldn't re-trigger.
function AskCodeMapPanel({ data, prefill, sectionRef }) {
  const [question, setQuestion] = useState('')
  const [conversation, setConversation] = useState([])
  const [expanded, setExpanded] = useState(false)
  const chat = useMutation({ mutationFn: askRepositoryQuestion })
  const queryClient = useQueryClient()
  const inputRef = useRef(null)

  const codeIntelligence = queryClient.getQueryData(['code-intelligence'])
  const suggestions = buildSuggestedQuestions(data, codeIntelligence).slice(0, 5)

  useEffect(() => {
    if (!prefill) return
    setQuestion(prefill.question)
    setExpanded(true)
    inputRef.current?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.key])

  // Cmd/Ctrl+K opens and focuses the bar from anywhere on Overview -- a
  // standard command-palette shortcut, scoped to this one mounted instance.
  useEffect(() => {
    function handleKeydown(event) {
      if (event.key.toLowerCase() !== 'k' || !(event.metaKey || event.ctrlKey)) return
      event.preventDefault()
      setExpanded(true)
      inputRef.current?.focus()
    }
    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  }, [])

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
          setExpanded(true)
        },
        onError: (error) => toast.error('Could not get an answer', { description: errorMessage(error) }),
      },
    )
  }

  function pickSuggestion(suggested) {
    setQuestion(suggested)
    setExpanded(true)
    inputRef.current?.focus()
  }

  // Losing focus only collapses the bar back down when there's nothing to
  // preserve -- an in-progress question or an existing answer stays open;
  // the chevron in the header is the explicit way to close those.
  function handleBlur(event) {
    if (event.currentTarget.contains(event.relatedTarget)) return
    if (question.trim() === '' && conversation.length === 0 && !chat.isPending) setExpanded(false)
  }

  function handleKeyDown(event) {
    if (event.key === 'Escape') {
      event.currentTarget.blur()
      setExpanded(false)
    }
  }

  return (
    <section
      className={`ask-command-bar${expanded ? ' ask-command-bar-expanded' : ''}`}
      ref={sectionRef}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
    >
      <div className="ask-command-header">
        <span className="ask-command-title">
          <Sparkles size={15} />
          Ask CodeMap
        </span>
        {expanded ? (
          <button type="button" className="ask-command-collapse" onClick={() => setExpanded(false)} aria-label="Collapse">
            <ChevronUp size={15} />
          </button>
        ) : (
          <span className="ask-command-kbd">⌘K</span>
        )}
      </div>

      <form onSubmit={handleAsk} className="ask-command-form">
        <input
          ref={inputRef}
          className="ask-command-input"
          type="text"
          placeholder="Ask anything about this codebase…"
          value={question}
          disabled={chat.isPending}
          onChange={(event) => setQuestion(event.target.value)}
          onFocus={() => setExpanded(true)}
        />
        <button type="submit" className="ask-command-submit" disabled={chat.isPending || !question.trim()} aria-label="Ask">
          {chat.isPending ? <Loader2 className="spinner" size={15} /> : <ArrowRight size={15} />}
        </button>
      </form>

      {suggestions.length > 0 && (
        <div className="ask-command-suggestions">
          {suggestions.map((suggested, index) => (
            <span key={suggested} className="ask-command-suggestion-wrap">
              <button type="button" className="ask-command-suggestion" onClick={() => pickSuggestion(suggested)}>
                {suggested}
              </button>
              {index < suggestions.length - 1 && (
                <span className="ask-command-dot" aria-hidden="true">
                  ·
                </span>
              )}
            </span>
          ))}
        </div>
      )}

      {expanded && conversation.length > 0 && (
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
    </section>
  )
}

// Hover-driven flex-grow per card, keyed by which card currently has focus.
// Card order is ai, tech, structure -- tech is the default focus (center,
// slightly larger) -- hovering (or tab-focusing) a card reassigns focus to
// it; leaving the carousel entirely falls back to 'tech'. Values stay close
// together on purpose (0.85-1.3) so the three cards always read as one
// composition rather than one card ballooning over the other two.
const FOCUS_GROW = {
  ai: { ai: 1.3, tech: 0.9, structure: 0.85 },
  tech: { ai: 0.88, tech: 1.28, structure: 0.88 },
  structure: { ai: 0.85, tech: 0.9, structure: 1.3 },
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

// The AI Repository Brief carousel card is just an entry point -- the
// generated summary itself renders here, in a right-side drawer, so the
// carousel stays a compact scanning surface regardless of how long the
// generated text is. Reuses the exact same `summary` query/mutstate the
// card's button triggers; nothing here re-requests or duplicates it.
function RepositoryBriefDrawer({ open, onClose, repositoryName, summary, summaryMode, onSummaryModeChange }) {
  useEffect(() => {
    if (!open) return
    function handleKeydown(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  }, [open, onClose])

  return (
    <>
      <div className={`brief-drawer-backdrop${open ? ' brief-drawer-backdrop-open' : ''}`} onClick={onClose} aria-hidden="true" />
      <aside className={`brief-drawer${open ? ' brief-drawer-open' : ''}`} aria-hidden={!open}>
        <div className="brief-drawer-header">
          <div>
            <p className="brief-drawer-eyebrow">
              <Sparkles size={14} />
              AI Repository Brief
            </p>
            <h3 className="brief-drawer-title">{repositoryName}</h3>
            <p className="card-subtitle">Repository analysis</p>
          </div>
          <button type="button" className="brief-drawer-close" onClick={onClose}>
            <X size={15} />
            Close
          </button>
        </div>

        {summary.data && !summary.isFetching && (
          <div className="brief-drawer-toolbar">
            <div className="mode-toggle">
              <button
                type="button"
                className={summaryMode === 'beginner' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                onClick={() => onSummaryModeChange('beginner')}
              >
                Beginner
              </button>
              <button
                type="button"
                className={summaryMode === 'developer' ? 'mode-btn mode-btn-active' : 'mode-btn'}
                onClick={() => onSummaryModeChange('developer')}
              >
                Developer
              </button>
            </div>
            <button type="button" className="link-button" onClick={() => summary.refetch()}>
              Regenerate
            </button>
          </div>
        )}

        <div className="brief-drawer-body">
          {summary.isFetching && <SummaryLoadingState />}
          {summary.isError && !summary.isFetching && (
            <p className="field-error">Could not generate a summary: {errorMessage(summary.error)}</p>
          )}
          {summary.data && !summary.isFetching && (
            <p className="summary-text">
              {summaryMode === 'beginner' ? summary.data.beginner_summary : summary.data.developer_summary}
            </p>
          )}
        </div>
      </aside>
    </>
  )
}

export function RepositoryOverview({ data, onExploreStructure, askPrefill }) {
  const [summaryMode, setSummaryMode] = useState('beginner')
  const [focusedCard, setFocusedCard] = useState('tech')
  const [briefOpen, setBriefOpen] = useState(false)
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

  // Opens the drawer and, the first time, kicks off the same on-demand
  // generation the old inline "Generate Summary" button used -- once
  // summary.data exists, reopening just shows it again, no re-fetch.
  function openBrief() {
    setBriefOpen(true)
    if (!summary.data && !summary.isFetching) summary.refetch()
  }

  const { total_files, total_folders, frameworks, statistics } = data
  const topFolders = computeTopFolders(data.files)
  const languageBreakdown = computeLanguageBreakdown(data.files)
  const frameworkGroups = mergeFrameworkGroups(groupFrameworksByCategory(frameworks))
  // Repository-wide contributor count (full commit history), not the
  // recent-activity window Git History's own contributor stat is scoped to
  // -- see GitAnalyzer.repository_contributors for why these are kept
  // distinct instead of one ambiguous "contributors" number.
  const contributors = gitSummary.data?.has_git_history ? gitSummary.data.repository_contributors : null
  const contributorsTruncated = gitSummary.data?.repository_contributors_truncated ?? false

  return (
    <div className="overview">
      <section className="overview-identity">
        <h1>{data.repository_name}</h1>
        <p className="card-subtitle">Repository analysis</p>
      </section>

      <AskCodeMapPanel data={data} prefill={askPrefill} sectionRef={askSectionRef} />

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
            <strong>
              {contributors}
              {contributorsTruncated ? '+' : ''}
            </strong>{' '}
            contributor{contributors === 1 && !contributorsTruncated ? '' : 's'}
          </span>
        )}
      </div>

      <section className="overview-block intelligence-block">
        <p className="intel-eyebrow">Repository intelligence</p>
        <div className="intelligence-carousel" onMouseLeave={() => setFocusedCard('tech')}>
          <IntelligenceCard id="ai" focused={focusedCard} onFocus={setFocusedCard} headerIcon={Sparkles} title="AI repository brief">
            <div className="intel-ai-empty">
              <p className="card-subtitle">Understand this repository in plain language.</p>
              <button type="button" className="btn btn-outline mt-3" onClick={openBrief} disabled={summary.isFetching}>
                {summary.isFetching ? 'Generating…' : summary.data ? 'View AI brief →' : 'Generate AI brief →'}
              </button>
              {summary.isError && !summary.isFetching && (
                <p className="field-error mt-3">Could not generate a summary: {errorMessage(summary.error)}</p>
              )}
            </div>
          </IntelligenceCard>

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
        </div>
      </section>

      <RepositoryBriefDrawer
        open={briefOpen}
        onClose={() => setBriefOpen(false)}
        repositoryName={data.repository_name}
        summary={summary}
        summaryMode={summaryMode}
        onSummaryModeChange={setSummaryMode}
      />
    </div>
  )
}
