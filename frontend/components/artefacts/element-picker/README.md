# Dr.XAS element picker

A controlled React element picker with all 118 elements and the purple-to-peach
periodic-table palette used by Dr.XAS Database. The same source is used in
XAScraft's structure search and its live artefact demo.

## Use in another app

Copy this folder into an app with React 18 or newer, React DOM, TypeScript, and a
bundler that supports CSS Modules, such as Vite or Next.js. Import the component
from the folder's `index.ts`; no XAScraft aliases or Next.js modules are required.
The native modal dialog requires a modern browser with `HTMLDialogElement.showModal`.
This is React source, not a plain HTML widget or a compiled npm package.

```tsx
"use client"

import { useState } from "react"
import { ElementPicker } from "./element-picker"

export function StructureFilter() {
  const [element, setElement] = useState<string | null>(null)

  return <ElementPicker value={element} onChange={setElement} />
}
```

`example.tsx` includes a complete host component. In Next.js, use the picker
inside a client component so that its callback stays on the client. The included
`element-picker.module.css.d.ts` supplies the stylesheet's TypeScript declaration.

## API

| Prop | Type | Behavior |
| --- | --- | --- |
| `value` | `string \| null` | Selected chemical symbol; `null` means no filter. |
| `onChange` | `(symbol: string \| null) => void` | Selection callback; clearing emits `null`. |
| `disabled` | `boolean` | Disables the trigger. |
| `triggerLabel` | `string` | Trigger text; defaults to `Pick element`. |
| `className` | `string` | Additional class on the trigger button. |
| `style` | `CSSProperties` with `--ep-*` custom properties | Applied to the trigger and portalled dialog. |

The host owns the selected value, validation, network requests, and persistence.
Selecting an element does not search structures or change scientific data. The
picker has no API, local-storage, icon-package, or application-context dependency.

Search by symbol, element name, or atomic number. Arrow keys navigate the table
spatially; Home and End move to the first and last matching elements in atomic
number order. Enter selects a focused element. Escape dismisses the dialog
without changing the value, and selection returns focus to the trigger.

## Theme

Pass CSS variables through `style` to reach both the trigger and the dialog,
which is portalled into `document.body`:

```tsx
<ElementPicker
  value={element}
  onChange={setElement}
  style={{ "--ep-accent": "#6d28d9", "--ep-surface": "#ffffff" }}
/>
```

Available tokens are `--ep-background`, `--ep-surface`, `--ep-ink`, `--ep-muted`,
`--ep-border`, `--ep-accent`, `--ep-font`, and `--ep-backdrop`. The component has
self-contained light defaults; the host can pass its own light or dark theme.
No web fonts or external assets are downloaded.

The default font stack matches the Dr.XAS Database periodic table: Avenir Next,
Avenir, then the platform system fonts. Element symbols use weight 650; atomic
numbers and names use 400. Their responsive font sizes, line heights and 80%
rendered text scale also match the reference. The scale applies only to text,
preserving the picker's button targets; names remain available on narrow screens.
Set `--ep-font` only when intentionally overriding this typography.

## Contents

- `index.ts`: public exports.
- `elements.ts`: the 118 elements, names, atomic numbers, families, and positions.
- `element-picker.tsx`: trigger, modal dialog, and selection behavior.
- `element-picker.module.css`: scoped styles and the Dr.XAS palette.
- `element-picker.module.css.d.ts`: stylesheet type declaration.
- `example.tsx`: controlled usage example.
- `LICENSE`: the source repository's MIT notice, retained verbatim.

## Source and export

The visual and periodic-layout references are in `DrXAS_database`:

- `frontend/src/domain/elements.ts`
- `frontend/src/widgets/PeriodicTable.tsx`
- `xasdata/web/static/css/app.css` (periodic-table styles and column palette)

The palette sweeps from dark purple at the left to peach and gold at the right;
lanthanides and actinides have separate lavender and rose colors. These colors
follow table columns rather than representing chemical-family categories.

In the XAScraft checkout, this folder is the canonical source. Rebuild the
download after changing any of its distributed files:

```sh
python3 scripts/export-element-picker.py
python3 scripts/export-element-picker.py --check
```

The deterministic archive is written to
`frontend/public/artefacts/drxas-element-picker.zip`. It contains only the explicit
source-file list above and this README. `--check` exits unsuccessfully if the
archive is missing or differs from the current source. The demo is available at
`/artefacts/element-picker`, below the configured app base path when mounted.
