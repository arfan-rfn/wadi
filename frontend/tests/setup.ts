import "@testing-library/jest-dom/vitest"

import { cleanup } from "@testing-library/react"
import { afterEach } from "vitest"

// Testing Library only auto-cleans when vitest runs with `globals: true`, and
// this project does not. Without this every rendered tree stayed mounted for
// the whole file, which fails in two directions: a `screen` query can match
// markup from an EARLIER test (an assertion that passes about the wrong
// render), and React work still scheduled against a torn-down jsdom throws
// "window is not defined" as the file ends.
afterEach(cleanup)
