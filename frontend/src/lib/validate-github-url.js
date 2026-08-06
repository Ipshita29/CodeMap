const GITHUB_URL_PATTERN =
  /^https:\/\/github\.com\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?:\.git)?\/?$/

export function isValidGitHubUrl(url) {
  return GITHUB_URL_PATTERN.test(url.trim())
}
