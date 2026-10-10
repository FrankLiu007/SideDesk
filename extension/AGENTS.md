# marketing-desk extension

These instructions apply to `marketing-desk/extension`.

## Internationalization

User-visible copy in this extension goes through i18n. Do not hardcode Chinese or English strings in components.

- Use `svelte-i18n`, the same library as `website/frontend`.
- Maintain at least two locales: `zh` (Chinese) and `en` (English).
- When adding or changing UI copy, update both locale catalogs together.
- Keep catalogs inside the extension (for example `src/lib/i18n/`). Use stable English key paths; do not use full Chinese sentences as keys.
