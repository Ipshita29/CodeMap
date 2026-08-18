// Maps the exact language/framework names the backend returns (see
// backend/app/analyzer/constants.py LANGUAGE_EXTENSIONS and
// app/analyzer/tech_stack_detector.py) to a real Simple Icons brand icon.
// Every key here was verified to exist in the installed react-icons/si
// package before being added -- an unmapped name just falls back to a
// generic icon rather than crashing on an undefined component.
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

export const LANGUAGE_ICONS = {
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

export const FRAMEWORK_ICONS = {
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

export function getLanguageIcon(name) {
  return LANGUAGE_ICONS[name] ?? null
}

export function getFrameworkIcon(name) {
  return FRAMEWORK_ICONS[name] ?? null
}
