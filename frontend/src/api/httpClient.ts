// Facade re-export so existing `import { api } from "../api/httpClient"` and
// `import { ApiError } from "../api/httpClient"` keep working after the
// client was split into api/{http,files,chat,sessions,index}.ts per the M1
// architecture refactor.
export { api } from "./index";
export { ApiError } from "./http";
