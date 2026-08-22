// Builds the CodeMap export report entirely from data the UI has already
// fetched (passed in as arguments) -- no network calls happen here. This is
// what keeps Export/Share from re-running AI or rebuilding the graph: it
// only ever describes what's already in memory, and says so plainly when a
// section wasn't generated in this session rather than silently omitting it.

function formatDate(iso) {
  if (!iso) return 'unknown date'
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

const NOT_GENERATED = (what) => `_Not generated in this session. ${what}_`

export function buildMarkdownReport({
  repositoryAnalysis,
  codeIntelligence,
  health,
  gitSummary,
  beginnerSummary,
  developerSummary,
  lastImpact,
}) {
  const lines = []
  const push = (...args) => lines.push(...args)

  push('# CodeMap Repository Report', '')
  push(`Repository: ${repositoryAnalysis.repository_name}`)
  push(`Generated: ${new Date().toISOString()}`, '', '---', '')

  push('## Repository Overview', '')
  push(`- Total files: ${repositoryAnalysis.total_files}`)
  push(`- Total folders: ${repositoryAnalysis.total_folders}`)
  push(`- Total lines: ${repositoryAnalysis.statistics.total_lines}`)
  if (repositoryAnalysis.statistics.largest_file) {
    push(
      `- Largest file: ${repositoryAnalysis.statistics.largest_file.path} (${repositoryAnalysis.statistics.largest_file.lines} lines)`,
    )
  }
  push('')

  push('## Tech Stack', '')
  const languages = Object.entries(repositoryAnalysis.languages)
  push(
    languages.length
      ? `- Languages: ${languages.map(([lang, count]) => `${lang} (${count})`).join(', ')}`
      : '- No recognized languages detected.',
  )
  push(
    repositoryAnalysis.frameworks.length
      ? `- Frameworks: ${repositoryAnalysis.frameworks.join(', ')}`
      : '- No frameworks detected.',
  )
  push('')

  push('## Beginner Summary', '')
  push(beginnerSummary || NOT_GENERATED('Visit "Ask CodeMap" to generate it.'))
  push('')

  push('## Developer Summary', '')
  push(developerSummary || NOT_GENERATED('Visit "Ask CodeMap" to generate it.'))
  push('')

  push('## Architecture', '')
  if (codeIntelligence) {
    const functions = codeIntelligence.symbols.filter((s) => s.kind === 'function').length
    const classes = codeIntelligence.symbols.filter((s) => s.kind === 'class').length
    push(`- Functions: ${functions}`)
    push(`- Classes: ${classes}`)
    push(`- API routes detected: ${codeIntelligence.routes.length}`)
    if (codeIntelligence.routes.length > 0) {
      push('', '### API Routes', '')
      codeIntelligence.routes.slice(0, 30).forEach((route) => {
        push(`- ${route.method} ${route.path} -> ${route.handler} (${route.file})`)
      })
    } else {
      push('- No recognizable API routes were detected.')
    }
  } else {
    push(NOT_GENERATED('Visit the Architecture tab to generate it.'))
  }
  push('')

  push('## Dependencies', '')
  if (codeIntelligence) {
    const external = [...new Set(codeIntelligence.imports.filter((imp) => imp.is_external).map((imp) => imp.source))]
    push(external.length ? `- External dependencies detected: ${external.length}` : '- No external dependencies detected.')
    if (external.length > 0) push(`- ${external.slice(0, 40).join(', ')}`)
  } else {
    push(NOT_GENERATED('Visit the Architecture tab to generate it.'))
  }
  push('')

  push('## Repository Health', '')
  if (health) {
    push(`CodeMap Health Score: ${health.score}/100`, '')
    Object.entries(health.categories).forEach(([category, score]) => {
      push(`- ${category[0].toUpperCase()}${category.slice(1)}: ${score}`)
    })
    if (health.findings.length > 0) {
      push('', '### Findings', '')
      health.findings.forEach((finding) => {
        push(
          `- [${finding.severity.toUpperCase()}] (${finding.category}${finding.path ? `, ${finding.path}` : ''}) ${finding.reason} Recommendation: ${finding.recommendation}`,
        )
      })
    }
  } else {
    push('_Repository health has not been analyzed in this session. Visit the Health tab to generate it._')
  }
  push('')

  push('## Git Summary', '')
  if (gitSummary && gitSummary.has_git_history) {
    if (gitSummary.latest_commit) {
      push(
        `Latest commit: "${gitSummary.latest_commit.message}" by ${gitSummary.latest_commit.author} on ${formatDate(gitSummary.latest_commit.date)} (${gitSummary.latest_commit.short_hash})`,
        '',
      )
    }
    push(`- Commits analyzed: ${gitSummary.activity.total_commits}${gitSummary.activity.truncated ? '+' : ''}`)
    push(`- Contributors: ${gitSummary.activity.contributors}`)
    push(`- Commits in last 7 days: ${gitSummary.activity.commits_last_7_days}`)
    push(`- Commits in last 30 days: ${gitSummary.activity.commits_last_30_days}`)
    if (gitSummary.activity.most_modified_files.length > 0) {
      push('', 'Most modified files:', '')
      gitSummary.activity.most_modified_files.forEach((f) => push(`- ${f.path} (${f.commit_count} commits)`))
    }
  } else {
    push('_No Git history was found for this repository._')
  }
  push('')

  push('## Impact Analysis', '')
  if (lastImpact) {
    push(`Last impact analysis, for ${lastImpact.file}:`, '')
    push(`- Risk: ${lastImpact.risk.level.toUpperCase()} (${lastImpact.risk.score}/100)`)
    push(`- Direct dependents: ${lastImpact.direct_dependents.map((d) => d.path).join(', ') || 'none'}`)
    push(`- Indirect dependents: ${lastImpact.indirect_dependents.map((d) => d.path).join(', ') || 'none'}`)
    if (lastImpact.summary) push('', lastImpact.summary)
    push('')
  } else {
    push('_No impact analysis was run in this session. Visit the Architecture tab to generate one._', '')
  }

  push('---', '')
  push('_Report generated by CodeMap. AI-generated sections may be incomplete or inferred; verify against the actual repository before relying on them._')

  return lines.join('\n')
}

export function buildJsonExport({
  repositoryAnalysis,
  codeIntelligence,
  health,
  gitSummary,
  graph,
  beginnerSummary,
  developerSummary,
  lastImpact,
}) {
  return {
    generated_at: new Date().toISOString(),
    repository: {
      name: repositoryAnalysis.repository_name,
      total_files: repositoryAnalysis.total_files,
      total_folders: repositoryAnalysis.total_folders,
      languages: repositoryAnalysis.languages,
      frameworks: repositoryAnalysis.frameworks,
      statistics: repositoryAnalysis.statistics,
    },
    files: repositoryAnalysis.files,
    code_intelligence: codeIntelligence
      ? {
          symbols: codeIntelligence.symbols,
          imports: codeIntelligence.imports,
          exports: codeIntelligence.exports,
          relationships: codeIntelligence.relationships,
          routes: codeIntelligence.routes,
          stats: codeIntelligence.stats,
        }
      : null,
    graph: graph ?? null,
    health: health ?? null,
    git: gitSummary ?? null,
    ai_summaries: { beginner: beginnerSummary ?? null, developer: developerSummary ?? null },
    impact_analysis: lastImpact ?? null,
  }
}

export function downloadTextFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
