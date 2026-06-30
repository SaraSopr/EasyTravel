// Warnings we never surface to the user. Matched as a case-insensitive substring
// so frozen/stored eval payloads with slightly different wording are covered too.
const HIDDEN_WARNING_PATTERNS = [
  'could not be scheduled',
]

export function visibleWarnings(warnings: string[] | null | undefined): string[] {
  if (!warnings) return []
  return warnings.filter(
    (w) => !HIDDEN_WARNING_PATTERNS.some((p) => w.toLowerCase().includes(p)),
  )
}
