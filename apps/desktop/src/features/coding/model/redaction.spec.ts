import { describe, expect, it } from "vitest";
import { isSensitiveKey, redactCommandArgs, redactSecretText } from "./redaction";

describe("redaction（W6-R 呈现层脱敏）", () => {
  it("遮蔽 bearer 令牌与键值凭据（与后端 _redact_line 同语义）", () => {
    expect(redactSecretText("Authorization: Bearer abc.def.ghi")).toBe(
      "Authorization: Bearer [REDACTED]"
    );
    expect(redactSecretText("api_key=12345 other=ok")).toBe("api_key=[REDACTED] other=ok");
    expect(redactSecretText("password: hunter2, next")).toBe("password: [REDACTED], next");
    expect(redactSecretText("token=xyz")).toBe("token=[REDACTED]");
  });

  it("遮蔽 URL userinfo 中的密码", () => {
    expect(redactSecretText("clone https://user:hunter2@example.com/repo.git")).toBe(
      "clone https://user:[REDACTED]@example.com/repo.git"
    );
  });

  it("非敏感文本原样保留", () => {
    const text = "pytest tests -q --maxfail=1";
    expect(redactSecretText(text)).toBe(text);
  });

  it("命令参数：--token= 与 KEY= 形态遮蔽值、其余参数保留", () => {
    expect(redactCommandArgs(["pytest", "-q", "--token=sk-abc", "API_KEY=zzz"])).toBe(
      "pytest -q --token=[REDACTED] API_KEY=[REDACTED]"
    );
  });

  it("命令参数：普通参数与路径不被误伤", () => {
    expect(redactCommandArgs(["npm", "run", "build", "--out-dir=dist"])).toBe(
      "npm run build --out-dir=dist"
    );
  });

  it("isSensitiveKey 命中凭据族键名", () => {
    expect(isSensitiveKey("--token")).toBe(true);
    expect(isSensitiveKey("API_KEY")).toBe(true);
    expect(isSensitiveKey("password")).toBe(true);
    expect(isSensitiveKey("authorization")).toBe(true);
    expect(isSensitiveKey("--quiet")).toBe(false);
    expect(isSensitiveKey("path")).toBe(false);
  });
});
