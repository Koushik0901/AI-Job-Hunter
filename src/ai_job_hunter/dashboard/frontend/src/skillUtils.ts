export function normalizeSkill(value: string, aliases: Record<string, string> = {}): string {
  const normalized = value.trim().toLowerCase();
  const parenthetical = [...normalized.matchAll(/\(([^)]{1,32})\)/g)].map((match) => match[1] ?? "");
  const stripped = normalized
    .replace(/[/_-]+/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .replace(/[^a-z0-9\s]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  for (const raw of parenthetical) {
    const key = raw.replace(/[^a-z0-9]+/g, "");
    if (aliases[key]) {
      return aliases[key];
    }
  }
  if (aliases[stripped]) {
    return aliases[stripped];
  }
  const tokens = stripped.split(" ").filter(Boolean);
  if (tokens.length >= 2) {
    const acronym = tokens.map((token) => token[0]).join("");
    if (aliases[acronym]) {
      return aliases[acronym];
    }
  }
  return stripped;
}

export function compactSkill(value: string, aliases: Record<string, string> = {}): string {
  return normalizeSkill(value, aliases).replace(/[^a-z0-9]+/g, "");
}

export function acronymSkill(value: string, aliases: Record<string, string> = {}): string {
  const tokens = normalizeSkill(value, aliases).split(" ").filter(Boolean);
  if (tokens.length < 2) return "";
  return tokens.map((token) => token[0]).join("");
}

export function tokenizeSkill(value: string, aliases: Record<string, string> = {}): Set<string> {
  return new Set(
    normalizeSkill(value, aliases)
      .split(/[^a-z0-9]+/g)
      .map((token) => token.trim())
      .filter(Boolean),
  );
}

export function fuzzySkillSimilarity(left: string, right: string, aliases: Record<string, string> = {}): number {
  const l = normalizeSkill(left, aliases);
  const r = normalizeSkill(right, aliases);
  if (!l || !r) return 0;
  if (l === r) return 1;

  const lCompact = compactSkill(l, aliases);
  const rCompact = compactSkill(r, aliases);
  if (lCompact && lCompact === rCompact) return 1;

  const lAcronym = acronymSkill(l, aliases);
  const rAcronym = acronymSkill(r, aliases);
  if ((lAcronym && lAcronym === rCompact) || (rAcronym && rAcronym === lCompact)) return 1;
  if (lAcronym && rAcronym && lAcronym === rAcronym) return 1;

  const minLength = Math.min(l.length, r.length);
  const containsRatio = minLength >= 4 && (l.includes(r) || r.includes(l))
    ? minLength / Math.max(l.length, r.length)
    : 0;

  const lTokens = tokenizeSkill(l, aliases);
  const rTokens = tokenizeSkill(r, aliases);
  const overlap = [...lTokens].filter((token) => rTokens.has(token)).length;
  const tokenRatio = lTokens.size > 0 && rTokens.size > 0
    ? overlap / Math.max(lTokens.size, rTokens.size)
    : 0;

  const longer = l.length >= r.length ? l : r;
  const shorter = l.length >= r.length ? r : l;
  let prefix = 0;
  while (prefix < shorter.length && shorter[prefix] === longer[prefix]) {
    prefix += 1;
  }
  const prefixRatio = shorter.length >= 4 ? prefix / shorter.length : 0;

  return Math.max(containsRatio, tokenRatio, prefixRatio);
}

export function fuzzySkillsMatch(left: string, right: string, aliases: Record<string, string> = {}, threshold = 0.8): boolean {
  return fuzzySkillSimilarity(left, right, aliases) >= threshold;
}
