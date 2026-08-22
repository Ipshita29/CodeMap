import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Code2, Loader2, Sparkles } from 'lucide-react'

import { ApiError, fetchGitSummary, generateRepositorySummary } from '@/api'
import { AskCodeMapPanel } from '@/components/ai/AskCodeMapPanel'
import { getFrameworkIcon, getLanguageIcon } from '@/lib/tech-icons'
import {
  buildInsights,
  computeLanguageBreakdown,
  computeTopFolders,
} from '@/lib/repository-intelligence'

function errorMessage(error) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
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

function TechIcon({ icon: Icon }) {
  return Icon ? <Icon size={18} /> : <Code2 size={18} />
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

export function RepositoryOverview({ data, onExploreStructure, askPrefill }) {
  const [summaryMode, setSummaryMode] = useState('beginner')
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
  const frameworkGroups = groupFrameworksByCategory(frameworks)
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

      <section className="overview-block">
        <h2>Tech stack</h2>
        {languageBreakdown.length > 0 || frameworkGroups.length > 0 ? (
          <div className="tech-stack">
            {languageBreakdown.length > 0 && (
              <div className="tech-category">
                <p className="tech-category-label">Languages</p>
                <div className="tech-grid">
                  {languageBreakdown.map(({ language, percent }) => (
                    <div key={language} className="tech-chip">
                      <span className="tech-chip-icon">
                        <TechIcon icon={getLanguageIcon(language)} />
                      </span>
                      <span className="tech-chip-name">{language}</span>
                      <span className="tech-chip-meta">{percent}% of code</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {frameworkGroups.map(([category, names]) => (
              <div key={category} className="tech-category">
                <p className="tech-category-label">{category}</p>
                <div className="tech-grid">
                  {names.map((name) => (
                    <div key={name} className="tech-chip">
                      <span className="tech-chip-icon">
                        <TechIcon icon={getFrameworkIcon(name)} />
                      </span>
                      <span className="tech-chip-name">{name}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="card-subtitle">No recognized languages or frameworks found.</p>
        )}
      </section>

      <section className="overview-block">
        <h2>Repository structure</h2>
        {topFolders.length > 0 ? (
          <ul className="structure-summary-list">
            {topFolders.map(([name, count]) => (
              <li key={name} className="structure-summary-row">
                <span className="structure-summary-name">{name === '(root)' ? name : `${name}/`}</span>
                <span className="structure-summary-count">{count} files</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="card-subtitle">No files found.</p>
        )}
        <button type="button" className="link-button" onClick={onExploreStructure}>
          Explore structure →
        </button>
      </section>

      <section className="overview-block">
        <h2>Key insights</h2>
        {insights.length > 0 ? (
          <ol className="insight-list">
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

      <section className="overview-block summary-block">
        <h2>AI Repository Summary</h2>
        {!summary.data && !summary.isFetching && (
          <>
            <p className="card-subtitle">
              Generate a detailed explanation of this repository, including its purpose, architecture, important
              modules and how the major pieces work together.
            </p>
            <button type="button" className="btn btn-outline mt-3" onClick={() => summary.refetch()}>
              Generate Summary
            </button>
            {summary.isError && (
              <p className="field-error mt-3">Could not generate a summary: {errorMessage(summary.error)}</p>
            )}
          </>
        )}

        {summary.isFetching && <SummaryLoadingState />}

        {summary.data && !summary.isFetching && (
          <>
            <div className="mode-toggle mt-3">
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
            <p className="summary-text">
              {summaryMode === 'beginner' ? summary.data.beginner_summary : summary.data.developer_summary}
            </p>
            <button type="button" className="btn btn-outline mt-3" onClick={() => summary.refetch()}>
              Regenerate
            </button>
          </>
        )}
      </section>
    </div>
  )
}
