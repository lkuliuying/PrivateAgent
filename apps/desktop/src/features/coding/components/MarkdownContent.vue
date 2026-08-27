<script setup lang="ts">
/**
 * 小型、安全的消息 Markdown 渲染器。
 *
 * 不使用 v-html，也不执行任意 HTML；只覆盖对话输出需要的标题、段落、列表、
 * 引用、代码围栏和常用行内语法。这样本地模型输出可以正常排版，同时不会把
 * 模型返回的 HTML 当成可信 DOM 注入。
 */
import { computed, defineComponent, Fragment, h } from "vue";

const props = defineProps<{
  content: string;
}>();

type MarkdownBlock =
  | { type: "code"; text: string; language: string | null }
  | { type: "heading"; text: string; level: number }
  | { type: "list"; items: string[]; ordered: boolean }
  | { type: "quote"; text: string }
  | { type: "rule" }
  | { type: "paragraph"; text: string };

type InlineToken = {
  type: "text" | "code" | "strong" | "emphasis" | "link";
  text: string;
  href?: string;
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
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_([^_\n]+)_|\[[^\]\n]+\]\([^\s)]+\))/g;
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
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(value);
      const href = link ? safeLink(link[2]) : null;
      tokens.push(href && link
        ? { type: "link", text: link[1], href }
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

    const paragraph = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
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
      <pre v-if="block.type === 'code'" class="md-code"><code :data-language="block.language"><span v-if="block.language" class="md-code-language">{{ block.language }}</span>{{ block.text }}</code></pre>
      <component :is="`h${block.level}`" v-else-if="block.type === 'heading'" class="md-heading">
        <MarkdownInline :text="block.text" />
      </component>
      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.type === 'list'" class="md-list">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex"><MarkdownInline :text="item" /></li>
      </component>
      <blockquote v-else-if="block.type === 'quote'" class="md-quote"><MarkdownInline :text="block.text" /></blockquote>
      <hr v-else-if="block.type === 'rule'" class="md-rule" />
      <p v-else class="md-paragraph"><MarkdownInline :text="block.text" /></p>
    </template>
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
.md-code {
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
  font-size: var(--text-sm);
  line-height: var(--leading-tight);
}
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
.md-code {
  position: relative;
  overflow-x: auto;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  color: var(--color-fg);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.55;
  white-space: pre;
}
.md-code-language {
  display: block;
  margin-bottom: var(--space-2);
  color: var(--color-fg-subtle);
  font-family: inherit;
  font-size: var(--pa-text-meta);
  text-transform: lowercase;
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
</style>
