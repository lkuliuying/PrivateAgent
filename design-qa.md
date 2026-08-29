# Run transcript design QA

## Comparison target

- Process source of truth: `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-edf9351d-8230-487b-84da-14074db94998.png`
- Result source of truth: `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-e66636c9-54ab-4940-87c1-036586b06d1e.png`
- Expanded-process implementation: `F:\Program\Agent\design-qa-run-process.jpg`
- Collapsed-result implementation: `F:\Program\Agent\design-qa-run-result.jpg`
- Local route: `http://127.0.0.1:1420/?ui=v2&coding=1&coding-preview=ready&coding-run-preview=completed`
- State: light theme, completed Coding run, process expanded and collapsed result variants.
- Process comparison density: source and implementation are both 1160 × 920 physical pixels.
- Result comparison density: source is an 845 × 934 focused reference crop; implementation is a 1160 × 920 full desktop shell capture, so transcript structure and content density were compared independently from the existing shell chrome.

## Findings

- No actionable P0/P1/P2 differences remain.
- The old technical event list and bordered `输出总结` card were removed from the primary presentation.
- Completed runs now default to a standalone result document. Clicking the Chinese duration row expands or collapses the public execution process.
- Process narration uses public durable decision summaries, plan state, tool activity, approvals, file changes and verification facts. It does not expose hidden chain-of-thought.
- Resolved approvals are compact activity rows; only pending approvals remain actionable cards.
- Final Markdown output is rendered without a status-card border, followed by distinct file-change and artifact result cards.
- Duration, activity and state labels use Chinese wording while exact tool identifiers remain secondary audit details.

## Comparison history

1. Baseline showed dense telemetry rows, a bordered terminal summary card and result content nested inside the audit panel.
2. First pass introduced a document-style duration header, natural-language process messages, lightweight activity rows and standalone result content.
3. Final pass compacted resolved approvals, hid the preview-only tag, preserved patch file counts and added result artifact cards.
4. Post-fix captures were compared side-by-side with both supplied references at the dimensions above.

## Primary interactions tested

- Opened the completed preview directly from its URL and verified it selects the sample task.
- Expanded and collapsed the process through the `用时 38 分钟 58 秒` control.
- Opened and closed the plan detail panel.
- Verified the collapsed state retains the final Markdown and result cards only.
- Verified no browser console warnings or errors were emitted.

## Follow-up polish

- P3: the implementation retains the product's existing desktop header, composer and status bar around the transcript; the supplied references show focused content from a different shell.

final result: passed
