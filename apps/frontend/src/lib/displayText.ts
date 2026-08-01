const NAMED_HTML_ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  lt: "<",
  quot: '"',
};

/**
 * Decode HTML entities that OCR/document parsers sometimes leave in plain text.
 *
 * This returns an ordinary string for React to render as a text node. It must not
 * be paired with dangerouslySetInnerHTML: contract text is untrusted content.
 */
export function displayText(value: string): string {
  return value.replace(
    /&(?:#(\d+)|#x([\da-f]+)|([a-z]+));/gi,
    (
      entity,
      decimal: string | undefined,
      hexadecimal: string | undefined,
      named: string | undefined,
    ) => {
      if (decimal !== undefined || hexadecimal !== undefined) {
        const codePoint = Number.parseInt(
          decimal ?? hexadecimal!,
          decimal === undefined ? 16 : 10,
        );
        if (!Number.isSafeInteger(codePoint) || codePoint < 0 || codePoint > 0x10ffff) {
          return entity;
        }
        try {
          return String.fromCodePoint(codePoint);
        } catch {
          return entity;
        }
      }

      return NAMED_HTML_ENTITIES[named?.toLowerCase() ?? ""] ?? entity;
    },
  );
}
