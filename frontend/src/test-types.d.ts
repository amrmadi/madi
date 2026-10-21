/**
 * Test type declarations for the application project.
 *
 * `@testing-library/jest-dom/vitest` augments the `vitest` module rather than
 * shipping ambient globals, so listing it in `compilerOptions.types` is not
 * enough: the augmentation only applies to files that actually reference it.
 * This file does that for the whole `src` project, which is why the tests can
 * call `toBeInTheDocument()`, `toHaveTextContent()` and friends and still pass
 * `tsc -b`.
 */

/// <reference types="@testing-library/jest-dom" />
import '@testing-library/jest-dom/vitest'
