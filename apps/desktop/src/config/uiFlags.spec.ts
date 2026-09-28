import { expect, it } from "vitest";
import { isCodingWorkspaceEnabled } from "./uiFlags";
it("客户端只使用 Coding 工作台", () => { expect(isCodingWorkspaceEnabled()).toBe(true); });
