<script setup lang="ts">
/**
 * 小型、安全的消息 Markdown 渲染器。
 *
 * 不使用 v-html，也不执行任意 HTML；只覆盖对话输出需要的标题、段落、列表、
 * 引用、表格、代码围栏和常用行内语法。这样本地模型输出可以正常排版，同时不会把
 * 模型返回的 HTML 当成可信 DOM 注入。
 */
import { computed, defineComponent, Fragment, h, onBeforeUnmount, ref, watch } from "vue";
import { PhCopy } from "@phosphor-icons/vue";
import { copyAnswerText } from "../../agent/model/copyAnswerText";
import { parseWorkspaceFileTarget, type WorkspaceFileTarget } from "../model/outputFiles";

const props = defineProps<{
  content: string;
  copyControl?: "button" | "icon" | "none";
}>();
const emit = defineEmits<{ "open-file": [target: WorkspaceFileTarget] }>();

const copyState = ref<"idle" | "copied" | "failed">("idle");
const copying = ref(false);
let copyGeneration = 0;
const codeCopying = ref<number | null>(null);
const codeCopyState = ref<{ index: number; state: "copied" | "failed" } | null>(null);
let codeCopyGeneration = 0;
watch(() => props.content, () => { copyGeneration += 1; codeCopyGeneration += 1; copyState.value = "idle"; codeCopyState.value = null; });
onBeforeUnmount(() => { copyGeneration += 1; codeCopyGeneration += 1; });
async function copyCode(text: string, index: number) {
  if (codeCopying.value !== null) return;
  const generation = ++codeCopyGeneration;
  codeCopying.value = index;
  codeCopyState.value = null;
  try {
    const result = await copyAnswerText(text);
    if (generation === codeCopyGeneration) codeCopyState.value = { index, state: result === "ok" ? "copied" : "failed" };
  } catch {
    if (generation === codeCopyGeneration) codeCopyState.value = { index, state: "failed" };
  } finally { codeCopying.value = null; }
}
async function copyMarkdown() {
  if (copying.value) return;
  const generation = ++copyGeneration;
  copying.value = true;
  copyState.value = "idle";
  try {
    const result = await copyAnswerText(props.content);
    if (generation === copyGeneration) copyState.value = result === "ok" ? "copied" : "failed";
  } finally {
    copying.value = false;
  }
}

type TableAlignment = "left" | "center" | "right" | undefined;
const MAX_TABLE_COLUMNS = 32;
const MAX_TABLE_CELLS = 2048;

type MarkdownBlock =
  | { type: "code"; text: string; language: string | null }
  | { type: "heading"; text: string; level: number }
  | { type: "list"; items: string[]; ordered: boolean }
  | { type: "quote"; text: string }
  | { type: "table"; headers: string[]; alignments: TableAlignment[]; rows: string[][] }
  | { type: "rule" }
  | { type: "paragraph"; text: string };

type InlineToken = {
  type: "text" | "code" | "strong" | "emphasis" | "link" | "file";
  text: string;
  href?: string;
  target?: WorkspaceFileTarget;
};

function safeLink(href: string): string | null {
  const value = href.trim();
  if (value.startsWith("#")) return value;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function parseInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  // 下划线只在词边界作为强调标记，避免吞掉文件名和标识符中的字符。
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|(?<![\p{L}\p{N}_])__[^_\n]+__(?![\p{L}\p{N}_])|\*[^*\n]+\*|(?<![\p{L}\p{N}_])_([^_\n]+)_(?![\p{L}\p{N}_])|\[[^\]\n]+\]\((?:<[^<>\n]+>|[^\s)]+)\))/gu;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) tokens.push({ type: "text", text: text.slice(cursor, index) });
    const value = match[0];
    if (value.startsWith("`")) {
      tokens.push({ type: "code", text: value.slice(1, -1) });
    } else if (value.startsWith("**") || value.startsWith("__")) {
      tokens.push({ type: "strong", text: value.slice(2, -2) });
    } else if (value.startsWith("[")) {
      const link = /^\[([^\]]+)\]\((<[^<>\n]+>|[^)]+)\)$/.exec(value);
      const destination = link?.[2].replace(/^<|>$/g, "") ?? "";
      const href = link ? safeLink(destination) : null;
      const target = href ? null : parseWorkspaceFileTarget(destination);
      tokens.push(href && link
        ? { type: "link", text: link[1], href }
        : target && link ? { type: "file", text: link[1], target }
          : { type: "text", text: link?.[1] ?? value });
    } else {
      tokens.push({ type: "emphasis", text: value.slice(1, -1) });
    }
    cursor = index + value.length;
  }
  if (cursor < text.length) tokens.push({ type: "text", text: text.slice(cursor) });
  return tokens.length ? tokens : [{ type: "text", text }];
}

const MarkdownInline = defineComponent({
  name: "MarkdownInline",
  props: { text: { type: String, required: true } },
  setup(inlineProps) {
    return () =>
      h(
        Fragment,
        null,
        parseInline(inlineProps.text).map((token, index) => {
          const key = `${token.type}:${index}`;
          if (token.type === "code") return h("code", { key }, token.text);
          if (token.type === "strong") return h("strong", { key }, token.text);
          if (token.type === "emphasis") return h("em", { key }, token.text);
          if (token.type === "file" && token.target) {
            const target = token.target;
            return h("button", {
              key, type: "button", class: "md-file-link",
              title: `预览 ${target.path}${target.line ? `:${target.line}` : ""}`,
              onClick: () => emit("open-file", target),
            }, token.text);
          }
          if (token.type === "link") {
            return h(
              "a",
              { key, href: token.href, target: "_blank", rel: "noreferrer noopener" },
              token.text
            );
          }
          return token.text;
        })
      );
  },
});

function tableCells(line: string): string[] | null {
  const source = line.trim();
  const cells: string[] = [];
  let cell = "";
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (character === "\\" && index + 1 < source.length) {
      // 转义竖线属于单元格；成对反斜线不能把后面的列分隔符转义掉。
      const next = source[++index];
      cell += next === "|" ? "|" : `\\${next}`;
    } else if (character === "|") {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  if (!cells.length) return null;
  cells.push(cell.trim());
  if (source.startsWith("|")) cells.shift();
  if (cells[cells.length - 1] === "" && cell === "") cells.pop();
  return cells;
}

function tableHeader(lines: string[], index: number) {
  if (index + 1 >= lines.length) return null;
  const headers = tableCells(lines[index]);
  const delimiters = tableCells(lines[index + 1]);
  if (!headers?.length || headers.length > MAX_TABLE_COLUMNS || !delimiters || headers.length !== delimiters.length ||
      !delimiters.every(cell => /^:?-{3,}:?$/.test(cell))) return null;
  const alignments: TableAlignment[] = delimiters.map(cell =>
    cell.endsWith(":") ? (cell.startsWith(":") ? "center" : "right") : cell.startsWith(":") ? "left" : undefined
  );
  return { headers, alignments };
}

function parseBlocks(source: string): MarkdownBlock[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = /^\s*```([^\s`]*)\s*$/.exec(line);
    if (fence) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ type: "code", text: code.join("\n"), language: fence[1] || null });
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2] });
      index += 1;
      continue;
    }

    if (/^\s*(?:[-*_]\s*){3,}$/.test(line)) {
      blocks.push({ type: "rule" });
      index += 1;
      continue;
    }

    const unordered = /^\s*[-+*]\s+(.+)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      const isOrdered = Boolean(ordered);
      const items: string[] = [];
      while (index < lines.length) {
        const item = isOrdered
          ? /^\s*\d+[.)]\s+(.+)$/.exec(lines[index])
          : /^\s*[-+*]\s+(.+)$/.exec(lines[index]);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      blocks.push({ type: "list", items, ordered: isOrdered });
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "quote", text: quote.join("\n") });
      continue;
    }

    const table = tableHeader(lines, index);
    if (table) {
      const rows: string[][] = [];
      index += 2;
      // 防止稀疏的超大表格因补齐空单元格而成倍膨胀；余下行仍作为原文展示。
      while ((rows.length + 1) * table.headers.length <= MAX_TABLE_CELLS && index < lines.length && lines[index].trim() &&
             !/^\s*(?:```|#{1,6}\s|>\s?|[-+*]\s|\d+[.)]\s)/.test(lines[index])) {
        const cells = tableCells(lines[index]);
        if (!cells) break;
        rows.push(table.headers.map((_, column) => cells[column] ?? ""));
        index += 1;
      }
      blocks.push({ type: "table", ...table, rows });
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !tableHeader(lines, index) &&
      !/^\s*```/.test(lines[index]) &&
      !/^(#{1,6})\s+/.test(lines[index]) &&
      !/^\s*[-+*]\s+/.test(lines[index]) &&
      !/^\s*\d+[.)]\s+/.test(lines[index]) &&
      !/^\s*>\s?/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join("\n") });
  }
  return blocks;
}

const blocks = computed(() => parseBlocks(props.content ?? ""));
</script>

<template>
  <div class="markdown-content" data-testid="markdown-content">
    <template v-for="(block, index) in blocks" :key="`${block.type}:${index}`">
      <div v-if="block.type === 'code'" class="md-code-block">
        <div class="md-code-head">
          <span class="md-code-language" aria-hidden="true">{{ block.language ?? '代码' }}</span>
          <span v-if="codeCopyState?.index === index" role="status">{{ codeCopyState.state === 'copied' ? '已复制' : '复制失败，请手动选择文本' }}</span>
          <button type="button" class="pa-btn pa-btn--ghost md-code-copy" :disabled="codeCopying !== null" :aria-busy="codeCopying === index" aria-label="复制代码" @click="copyCode(block.text, index)"><PhCopy :size="14" aria-hidden="true" />复制代码</button>
        </div>
        <pre class="md-code"><code :data-language="block.language">{{ block.text }}</code></pre>
      </div>
      <component :is="`h${block.level}`" v-else-if="block.type === 'heading'" class="md-heading">
        <MarkdownInline :text="block.text" />
      </component>
      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.type === 'list'" class="md-list">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex"><MarkdownInline :text="item" /></li>
      </component>
      <blockquote v-else-if="block.type === 'quote'" class="md-quote"><MarkdownInline :text="block.text" /></blockquote>
      <hr v-else-if="block.type === 'rule'" class="md-rule" />
      <div v-else-if="block.type === 'table'" class="md-table-wrap" role="region" aria-label="表格" tabindex="0">
        <table class="md-table">
          <thead><tr>
            <th v-for="(header, column) in block.headers" :key="column" scope="col" :style="{ textAlign: block.alignments[column] }"><MarkdownInline :text="header" /></th>
          </tr></thead>
          <tbody><tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
            <td v-for="(cell, column) in row" :key="column" :style="{ textAlign: block.alignments[column] }"><MarkdownInline :text="cell" /></td>
          </tr></tbody>
        </table>
      </div>
      <p v-else class="md-paragraph"><MarkdownInline :text="block.text" /></p>
    </template>
    <slot name="after-content" />
    <div v-if="content.trim() && copyControl !== 'none'" class="md-copy-actions">
      <button type="button" class="pa-btn pa-btn--ghost md-copy-button" :class="{ 'md-copy-icon': copyControl === 'icon' }" :disabled="copying"
        :aria-busy="copying" aria-label="复制 Markdown" title="复制 Markdown" @click="copyMarkdown">
        <PhCopy v-if="copyControl === 'icon'" :size="18" aria-hidden="true" />
        <template v-else>{{ copying ? '复制中…' : '复制 Markdown' }}</template>
      </button>
      <span v-if="copyState === 'copied' || copyState === 'failed'" role="status">
        {{ copyState === 'copied' ? '已复制' : '复制失败，请手动选择文本' }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.markdown-content {
  min-width: 0;
  color: inherit;
  overflow-wrap: anywhere;
}
.md-paragraph,
.md-heading,
.md-list,
.md-quote,
.md-code-block,
.md-table-wrap {
  margin: 0 0 var(--space-2);
}
.markdown-content > :last-child {
  margin-bottom: 0;
}
.md-paragraph,
.md-quote {
  white-space: pre-wrap;
}
.md-heading {
  color: var(--color-fg);
  font-size: 1em;
  font-weight: 650;
  line-height: var(--leading-tight);
  margin-top: 1.2em;
}
.md-heading:first-child { margin-top: 0; }
h1.md-heading { font-size: 1.5em; }
h2.md-heading { font-size: 1.3em; }
h3.md-heading { font-size: 1.15em; }
h4.md-heading { font-size: 1.05em; }
.md-list {
  padding-left: 1.4rem;
}
.md-list li + li {
  margin-top: 2px;
}
.md-quote {
  padding-left: var(--space-3);
  border-left: 3px solid var(--color-border-strong, var(--color-border));
  color: var(--color-fg-muted);
}
.md-rule {
  margin: var(--space-3) 0;
  border: 0;
  border-top: 1px solid var(--color-border);
}
.md-code-block {
  position: relative;
  min-width: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  color: var(--color-fg);
  font-family: var(--font-mono);
  font-size: 0.92em;
}
.md-code {
  margin: 0;
  padding: var(--space-3);
  overflow-x: auto;
  font: inherit;
  line-height: 1.55;
  white-space: pre;
}
.md-code-language {
  display: block;
  flex: 1;
  color: var(--color-fg-subtle);
  font-family: inherit;
  font-size: var(--pa-text-meta);
  text-transform: lowercase;
  user-select: none;
}
.md-code-head { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-1) var(--space-3); font-size: var(--pa-text-meta); color: var(--color-fg-subtle); border-bottom: 1px solid var(--color-border); }
.md-code-copy { min-height: 26px; font-size: inherit; flex-shrink: 0; }
.md-copy-actions { display: flex; align-items: center; gap: var(--space-2); margin-top: var(--space-2); font-size: var(--pa-text-meta); color: var(--color-fg-subtle); }
.md-copy-button { font-size: inherit; min-height: 28px; }
.md-copy-icon { width: 28px; padding: 0; border-color: transparent; border-radius: var(--radius-sm); color: var(--color-fg-muted); }
.md-copy-icon:focus-visible { outline: var(--focus-ring); outline-offset: 2px; }
.md-table-wrap {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}
.md-table-wrap:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
.md-table {
  width: 100%;
  border-collapse: collapse;
  font-size: inherit;
}
.md-table th,
.md-table td {
  min-width: 6rem;
  padding: var(--space-2) var(--space-3);
  border-right: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}
.md-table th {
  background: var(--color-surface-muted);
  font-weight: 600;
}
.md-table tr > :last-child {
  border-right: 0;
}
.md-table tbody tr:last-child td {
  border-bottom: 0;
}
.markdown-content :deep(code:not(.md-code code)) {
  padding: 1px 5px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  font-family: var(--font-mono);
  font-size: 0.92em;
}
.markdown-content :deep(a) {
  color: var(--color-accent);
  text-decoration: none;
}
.markdown-content :deep(a:hover) {
  text-decoration: underline;
}
.markdown-content :deep(.md-file-link) { display: inline; padding: 0; border: 0; background: transparent; color: var(--color-accent); font: inherit; text-align: inherit; overflow-wrap: anywhere; cursor: pointer; }
.markdown-content :deep(.md-file-link:hover) { text-decoration: underline; }
.markdown-content :deep(.md-file-link:focus-visible) { outline: var(--focus-ring); outline-offset: 2px; }
</style>
