import { join } from "node:path";

import { generateRouteTypes } from "./verify-upgrade";

await generateRouteTypes(join(import.meta.dir, ".."));
