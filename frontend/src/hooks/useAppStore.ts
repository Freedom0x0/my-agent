// Facade re-export so existing `import { useAppStore, bootstrapApp } from
// "../hooks/useAppStore"` keeps working after the store was split into
// hooks/store/* per the M1 architecture refactor.
export { useAppStore, bootstrapApp } from "./store";
