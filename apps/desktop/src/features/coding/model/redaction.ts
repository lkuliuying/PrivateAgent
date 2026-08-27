/**
 * v0.8.0 W6-R · 呈现层脱敏（命令/参数/输出文本）
 *
 * 后端流式输出行已经过 `_redact_line` 脱敏（command_workflow.py）；命令参数
 * （execution.output.args）为持久化公开事实，呈现前再做一次同语义脱敏，
 * 确保命令卡/工具卡不展示凭据（计划 §10 零容忍、W6-R 退出条件）。
 * 模式与后端 _SECRET_TEXT_PATTERNS 保持一致，另覆盖 URL userinfo
 * （scheme://user:pass@host）这一命令参数常见凭据形态。
 * 本模块为纯函数（无 Vue 依赖），不改变任何持久化数据。
 */

const REDACTED = "[REDACTED]";

const SECRET_TEXT_PATTERNS: ReadonlyArray<RegExp> = [
  /(bearer\s+)[^\s,;]+/gi,
  /((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+/gi,
];

/** URL userinfo 形态：https://user:pass@host → https://user:[REDACTED]@host */
const URL_USERINFO_PATTERN = /(\b[a-z][a-z0-9+.-]*:\/\/[^:/@\s]+:)([^@\s]+)(@)/gi;

/** 对任意展示文本做凭据脱敏（不改变非敏感内容）。 */
export function redactSecretText(text: string): string {
  let redacted = text;
  for (const pattern of SECRET_TEXT_PATTERNS) {
    redacted = redacted.replace(pattern, `$1${REDACTED}`);
  }
  redacted = redacted.replace(URL_USERINFO_PATTERN, `$1${REDACTED}$3`);
  return redacted;
}

/**
 * 把命令参数数组渲染为脱敏后的命令文本。
 * `--token=xxx`/`-token=xxx`/`KEY=value` 形态的键值参数整体遮蔽值部分，
 * 与后端敏感键语义一致；其余参数按原样以空格连接。
 */
export function redactCommandArgs(args: ReadonlyArray<string>): string {
  const parts = args.map((arg) => {
    const dashMatch = /^(-{1,2}[A-Za-z][\w.-]*)([=:])(.+)$/.exec(arg);
    if (dashMatch && isSensitiveKey(dashMatch[1])) {
      return `${dashMatch[1]}${dashMatch[2]}${REDACTED}`;
    }
    const envMatch = /^([A-Za-z_][\w.-]*)(=)(.+)$/.exec(arg);
    if (envMatch && isSensitiveKey(envMatch[1])) {
      return `${envMatch[1]}${envMatch[2]}${REDACTED}`;
    }
    return redactSecretText(arg);
  });
  return parts.join(" ");
}

const SENSITIVE_KEY_PATTERN = /(api[_-]?key|auth|credential|pass(?:word)?|secret|token)/i;

/** 键名是否属于凭据类（与后端 _ENV_REJECT_PATTERN 同族）。 */
export function isSensitiveKey(key: string): boolean {
  return SENSITIVE_KEY_PATTERN.test(key.replace(/^-+/, ""));
}
