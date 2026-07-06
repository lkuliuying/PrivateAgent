<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import {
  PhGraduationCap,
  PhPlus,
  PhSparkle,
  PhNotePencil,
  PhQuestion,
  PhCards,
  PhTreeStructure,
  PhX,
} from "@phosphor-icons/vue";
import {
  listLearningTopics,
  createLearningTopic,
  updateLearningTopic,
  generateLearningPlan,
  listLearningNodes,
  saveLearningNote,
  listLearningNotes,
  generateQuiz,
  listQuizzes,
  gradeQuizAnswer,
  generateCards,
  listCards,
} from "../api";
import type {
  LearningTopic,
  LearningNode,
  LearningNote,
  LearningQuiz,
  LearningCard,
  GradeResult,
} from "../types";

/**
 * 学习工作区 · 第三阶段 M3。
 * 左：学习主题列表 + 新建；右：四标签（路线/笔记/练习/卡片）。
 * 生成类基于知识库资料（无指定文档时按主题目标检索）。
 */
const topics = ref<LearningTopic[]>([]);
const currentId = ref<number | null>(null);
const tab = ref<"path" | "notes" | "quiz" | "cards">("path");

const nodes = ref<LearningNode[]>([]);
const notes = ref<LearningNote[]>([]);
const quizzes = ref<LearningQuiz[]>([]);
const cards = ref<LearningCard[]>([]);
const loadingGen = ref(false);
const genError = ref("");

// 新建主题
const newOpen = ref(false);
const newTitle = ref("");
const newGoal = ref("");
const newLevel = ref("");

// 新建笔记
const noteTitle = ref("");
const noteBody = ref("");

// 答题
const quizAnswers = ref<Record<number, string>>({});
const quizResults = ref<Record<number, GradeResult | undefined>>({});

// 卡片翻转
const flipped = ref<Set<number>>(new Set());

const currentTopic = computed(
  () => topics.value.find((t) => t.id === currentId.value) ?? null
);

onMounted(load);

async function load() {
  try {
    topics.value = await listLearningTopics();
    if (topics.value.length > 0 && currentId.value === null) {
      await selectTopic(topics.value[0].id);
    }
  } catch {
    topics.value = [];
  }
}

async function selectTopic(id: number) {
  currentId.value = id;
  tab.value = "path";
  quizAnswers.value = {};
  quizResults.value = {};
  await loadAll();
}

async function loadAll() {
  if (!currentId.value) return;
  const id = currentId.value;
  try {
    const [n, ns, qs, cs] = await Promise.all([
      listLearningNodes(id),
      listLearningNotes(id),
      listQuizzes(id),
      listCards(id),
    ]);
    nodes.value = n;
    notes.value = ns;
    quizzes.value = qs;
    cards.value = cs;
  } catch {
    // ignore
  }
}

// ============ 主题 ============

function openNew() {
  newOpen.value = true;
  newTitle.value = "";
  newGoal.value = "";
  newLevel.value = "";
}

async function submitNew() {
  if (!newTitle.value.trim()) return;
  try {
    const t = await createLearningTopic({
      title: newTitle.value.trim(),
      goal: newGoal.value.trim() || undefined,
      level: newLevel.value.trim() || undefined,
    });
    topics.value.unshift(t);
    newOpen.value = false;
    await selectTopic(t.id);
  } catch (e) {
    alert("创建失败：" + String(e));
  }
}

async function archiveTopic() {
  if (!currentTopic.value) return;
  try {
    const updated = await updateLearningTopic(currentTopic.value.id, {
      status: "archived",
    });
    Object.assign(currentTopic.value, updated);
  } catch (e) {
    alert("归档失败：" + String(e));
  }
}

// ============ 生成 ============

async function genPlan() {
  if (!currentId.value) return;
  loadingGen.value = true;
  genError.value = "";
  try {
    await generateLearningPlan(currentId.value);
    nodes.value = await listLearningNodes(currentId.value);
  } catch (e) {
    genError.value = String(e);
  } finally {
    loadingGen.value = false;
  }
}

async function genQuiz() {
  if (!currentId.value) return;
  loadingGen.value = true;
  genError.value = "";
  try {
    await generateQuiz(currentId.value, undefined, 5);
    quizzes.value = await listQuizzes(currentId.value);
    quizAnswers.value = {};
    quizResults.value = {};
  } catch (e) {
    genError.value = String(e);
  } finally {
    loadingGen.value = false;
  }
}

async function genCards() {
  if (!currentId.value) return;
  loadingGen.value = true;
  genError.value = "";
  try {
    await generateCards(currentId.value, undefined, 5);
    cards.value = await listCards(currentId.value);
  } catch (e) {
    genError.value = String(e);
  } finally {
    loadingGen.value = false;
  }
}

// ============ 笔记 ============

async function submitNote() {
  if (!noteTitle.value.trim() || !noteBody.value.trim() || !currentId.value) return;
  try {
    await saveLearningNote({
      topic_id: currentId.value,
      title: noteTitle.value.trim(),
      body_md: noteBody.value,
    });
    noteTitle.value = "";
    noteBody.value = "";
    notes.value = await listLearningNotes(currentId.value);
  } catch (e) {
    alert("保存失败：" + String(e));
  }
}

// ============ 答题 ============

async function submitAnswer(qid: number) {
  const ans = quizAnswers.value[qid] || "";
  if (!ans.trim()) return;
  try {
    const grade = await gradeQuizAnswer(qid, ans);
    quizResults.value[qid] = grade;
  } catch (e) {
    alert("批改失败：" + String(e));
  }
}

function flip(id: number) {
  if (flipped.value.has(id)) flipped.value.delete(id);
  else flipped.value.add(id);
  flipped.value = new Set(flipped.value);
}

const MASTERY = [
  { v: "mastered", label: "掌握", cls: "ok" },
  { v: "vague", label: "模糊", cls: "warn" },
  { v: "unknown", label: "不会", cls: "bad" },
];
function masteryClass(node: LearningNode): string {
  const m = MASTERY.find((x) => x.v === node.mastery_level);
  return m?.cls || "muted";
}

const RESULT_TEXT: Record<string, string> = {
  correct: "正确",
  partial: "部分正确",
  wrong: "错误",
};
const RESULT_CLASS: Record<string, string> = {
  correct: "ok",
  partial: "warn",
  wrong: "bad",
};
</script>

<template>
  <section class="lw">
    <!-- 左：主题列表 -->
    <aside class="lw-topics">
      <div class="pane-head">
        <span>学习主题</span>
        <button class="pa-btn pa-btn--primary pa-btn--icon" title="新建主题" @click="openNew">
          <PhPlus :size="14" />
        </button>
      </div>
      <div class="topic-list">
        <button
          v-for="t in topics"
          :key="t.id"
          class="topic-item"
          :class="{ active: t.id === currentId, archived: t.status === 'archived' }"
          @click="selectTopic(t.id)"
        >
          <div class="topic-title pa-ellipsis">{{ t.title }}</div>
          <div class="topic-sub">
            <span v-if="t.level">{{ t.level }}</span>
            <span v-if="t.status !== 'active'">· {{ t.status }}</span>
          </div>
        </button>
        <div v-if="topics.length === 0" class="pane-empty">
          尚无学习主题
        </div>
      </div>
    </aside>

    <!-- 右：详情 -->
    <div class="lw-detail">
      <div v-if="!currentTopic" class="empty">
        <PhGraduationCap :size="40" weight="duotone" />
        <p>选择或创建一个学习主题</p>
        <p class="hint">助手将基于知识库资料生成学习路线、练习与卡片</p>
      </div>
      <template v-else>
        <header class="detail-head">
          <div class="head-main">
            <h2>{{ currentTopic.title }}</h2>
            <p v-if="currentTopic.goal" class="head-goal">{{ currentTopic.goal }}</p>
            <div class="head-meta">
              <span v-if="currentTopic.level" class="chip">{{ currentTopic.level }}</span>
              <span
                v-for="t in currentTopic.tags_json || []"
                :key="t"
                class="chip tag"
              >#{{ t }}</span>
            </div>
          </div>
          <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="archiveTopic">归档</button>
        </header>

        <nav class="tabs">
          <button :class="{ active: tab === 'path' }" @click="tab = 'path'">
            <PhTreeStructure :size="14" /> 路线
          </button>
          <button :class="{ active: tab === 'notes' }" @click="tab = 'notes'">
            <PhNotePencil :size="14" /> 笔记
          </button>
          <button :class="{ active: tab === 'quiz' }" @click="tab = 'quiz'">
            <PhQuestion :size="14" /> 练习
          </button>
          <button :class="{ active: tab === 'cards' }" @click="tab = 'cards'">
            <PhCards :size="14" /> 卡片
          </button>
        </nav>

        <div class="tab-body">
          <p v-if="genError" class="err">{{ genError }}</p>

          <!-- 路线 -->
          <div v-if="tab === 'path'" class="path-tab">
            <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="loadingGen" @click="genPlan">
              <PhSparkle :size="14" />
              {{ loadingGen ? "生成中…" : "生成学习路线" }}
            </button>
            <div v-if="nodes.length === 0" class="tab-empty">尚无学习路线，点击上方生成</div>
            <ol class="node-list">
              <li v-for="n in nodes" :key="n.id" class="node-item">
                <span class="node-idx">{{ n.order_index + 1 }}</span>
                <div class="node-main">
                  <div class="node-title">{{ n.title }}</div>
                  <div v-if="n.summary" class="node-summary">{{ n.summary }}</div>
                </div>
                <span class="mastery" :class="masteryClass(n)">
                  {{ MASTERY.find((x) => x.v === n.mastery_level)?.label || "未评" }}
                </span>
              </li>
            </ol>
          </div>

          <!-- 笔记 -->
          <div v-if="tab === 'notes'" class="notes-tab">
            <div class="note-editor">
              <input v-model="noteTitle" class="pa-input" placeholder="笔记标题" />
              <textarea
                v-model="noteBody"
                class="pa-input note-body"
                placeholder="Markdown 正文…"
                rows="4"
              ></textarea>
              <button
                class="pa-btn pa-btn--primary pa-btn--sm"
                :disabled="!noteTitle.trim() || !noteBody.trim()"
                @click="submitNote"
              >保存笔记</button>
            </div>
            <div v-if="notes.length === 0" class="tab-empty">尚无笔记</div>
            <div class="note-list">
              <div v-for="n in notes" :key="n.id" class="note-card">
                <div class="note-title">{{ n.title }}</div>
                <pre class="note-body-view">{{ n.body_md }}</pre>
              </div>
            </div>
          </div>

          <!-- 练习 -->
          <div v-if="tab === 'quiz'" class="quiz-tab">
            <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="loadingGen" @click="genQuiz">
              <PhSparkle :size="14" />
              {{ loadingGen ? "生成中…" : "生成 5 道练习题" }}
            </button>
            <div v-if="quizzes.length === 0" class="tab-empty">尚无练习题</div>
            <div class="quiz-list">
              <div v-for="q in quizzes" :key="q.id" class="quiz-card">
                <div class="quiz-q">{{ q.question }}</div>
                <textarea
                  v-model="quizAnswers[q.id]"
                  class="pa-input quiz-ans"
                  placeholder="输入你的答案…"
                  rows="2"
                ></textarea>
                <div class="quiz-foot">
                  <button
                    class="pa-btn pa-btn--subtle pa-btn--sm"
                    :disabled="!(quizAnswers[q.id] || '').trim()"
                    @click="submitAnswer(q.id)"
                  >提交批改</button>
                  <span
                    v-if="quizResults[q.id]"
                    class="quiz-result"
                    :class="RESULT_CLASS[quizResults[q.id]!.result]"
                  >
                    {{ RESULT_TEXT[quizResults[q.id]!.result] }}
                  </span>
                </div>
                <div v-if="quizResults[q.id]?.explanation" class="quiz-explain">
                  {{ quizResults[q.id]!.explanation }}
                </div>
              </div>
            </div>
          </div>

          <!-- 卡片 -->
          <div v-if="tab === 'cards'" class="cards-tab">
            <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="loadingGen" @click="genCards">
              <PhSparkle :size="14" />
              {{ loadingGen ? "生成中…" : "生成 5 张复习卡片" }}
            </button>
            <div v-if="cards.length === 0" class="tab-empty">尚无复习卡片</div>
            <div class="card-grid">
              <div
                v-for="c in cards"
                :key="c.id"
                class="flash-card"
                :class="{ flipped: flipped.has(c.id) }"
                @click="flip(c.id)"
              >
                <div class="flash-inner">
                  <div class="flash-face front">
                    <span class="flash-label">问题</span>
                    <p>{{ c.front }}</p>
                  </div>
                  <div class="flash-face back">
                    <span class="flash-label">答案</span>
                    <p>{{ c.back }}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- 新建主题浮层 -->
    <div v-if="newOpen" class="modal-overlay" @click.self="newOpen = false">
      <div class="modal-card">
        <div class="modal-head">
          <span>新建学习主题</span>
          <button class="pa-btn pa-btn--ghost pa-btn--icon" @click="newOpen = false">
            <PhX :size="14" />
          </button>
        </div>
        <label class="modal-label">标题</label>
        <input v-model="newTitle" class="pa-input" placeholder="如：操作系统" />
        <label class="modal-label">目标</label>
        <textarea v-model="newGoal" class="pa-input" rows="2" placeholder="想掌握什么"></textarea>
        <label class="modal-label">阶段</label>
        <input v-model="newLevel" class="pa-input" placeholder="入门 / 中级 / 进阶" />
        <div class="modal-actions">
          <button class="pa-btn pa-btn--subtle pa-btn--sm" @click="newOpen = false">取消</button>
          <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="!newTitle.trim()" @click="submitNew">创建</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.lw {
  display: flex;
  flex: 1;
  min-height: 0;
}
.lw-topics {
  flex-shrink: 0;
  width: 260px;
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
}
.pane-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg-muted);
}
.topic-list {
  flex: 1;
  overflow: auto;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.topic-item {
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.topic-item:hover {
  background: var(--color-surface-sunken);
}
.topic-item.active {
  background: var(--color-accent-soft);
}
.topic-item.archived {
  opacity: 0.5;
}
.topic-title {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg);
}
.topic-item.active .topic-title {
  color: var(--color-accent-soft-fg);
}
.topic-sub {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.pane-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  text-align: center;
  padding: var(--space-4);
}

/* 详情 */
.lw-detail {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
}
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-fg-faint);
  gap: var(--space-2);
}
.empty p {
  margin: 0;
  font-size: var(--text-base);
}
.empty .hint {
  font-size: var(--text-sm);
  max-width: 320px;
  text-align: center;
}
.detail-head {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}
.detail-head h2 {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
}
.head-goal {
  margin: 4px 0 0;
  color: var(--color-fg-subtle);
  font-size: var(--text-sm);
}
.head-meta {
  display: flex;
  gap: 4px;
  margin-top: var(--space-1);
  flex-wrap: wrap;
}
.chip {
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  background: var(--color-surface-sunken);
  padding: 1px 6px;
  border-radius: var(--radius-full);
}
.chip.tag {
  color: var(--color-accent-soft-fg);
  background: var(--color-accent-soft);
}
.tabs {
  flex-shrink: 0;
  display: flex;
  gap: 2px;
  padding: 0 var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.tabs button {
  display: flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--color-fg-muted);
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  border-bottom: 2px solid transparent;
}
.tabs button:hover {
  color: var(--color-fg);
}
.tabs button.active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}
.tab-body {
  flex: 1;
  overflow: auto;
  padding: var(--space-4) var(--space-5);
}
.err {
  color: var(--color-danger-fg);
  font-size: var(--text-sm);
  margin-bottom: var(--space-2);
}
.tab-empty {
  color: var(--color-fg-faint);
  font-size: var(--text-sm);
  text-align: center;
  padding: var(--space-6);
}

/* 路线 */
.node-list {
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.node-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
}
.node-idx {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full);
  background: var(--color-accent-soft);
  color: var(--color-accent-soft-fg);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  display: flex;
  align-items: center;
  justify-content: center;
}
.node-main {
  flex: 1;
  min-width: 0;
}
.node-title {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
}
.node-summary {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin-top: 2px;
}
.mastery {
  flex-shrink: 0;
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: var(--radius-full);
}
.mastery.ok {
  color: var(--color-success-fg);
  background: var(--color-success-soft);
}
.mastery.warn {
  color: var(--color-warning-fg);
  background: var(--color-warning-soft);
}
.mastery.bad {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
}
.mastery.muted {
  color: var(--color-fg-faint);
  background: var(--color-surface-sunken);
}

/* 笔记 */
.note-editor {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.note-body {
  resize: vertical;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}
.note-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.note-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.note-title {
  font-weight: var(--font-medium);
  font-size: var(--text-sm);
  margin-bottom: var(--space-1);
}
.note-body-view {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-word;
}

/* 练习 */
.quiz-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-top: var(--space-3);
}
.quiz-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.quiz-q {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  margin-bottom: var(--space-2);
}
.quiz-ans {
  resize: vertical;
  font-size: var(--text-sm);
}
.quiz-foot {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.quiz-result {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  padding: 2px 8px;
  border-radius: var(--radius-full);
}
.quiz-result.ok {
  color: var(--color-success-fg);
  background: var(--color-success-soft);
}
.quiz-result.warn {
  color: var(--color-warning-fg);
  background: var(--color-warning-soft);
}
.quiz-result.bad {
  color: var(--color-danger-fg);
  background: var(--color-danger-soft);
}
.quiz-explain {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-fg-subtle);
  background: var(--color-surface-sunken);
  padding: var(--space-2);
  border-radius: var(--radius);
}

/* 卡片 */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-3);
}
.flash-card {
  height: 140px;
  perspective: 600px;
  cursor: pointer;
}
.flash-inner {
  position: relative;
  width: 100%;
  height: 100%;
  transition: transform 0.4s;
  transform-style: preserve-3d;
}
.flash-card.flipped .flash-inner {
  transform: rotateY(180deg);
}
.flash-face {
  position: absolute;
  inset: 0;
  backface-visibility: hidden;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.flash-face.back {
  transform: rotateY(180deg);
  background: var(--color-accent-soft);
}
.flash-label {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  text-transform: uppercase;
}
.flash-face p {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-fg);
}

/* 浮层 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal-card {
  width: 420px;
  max-width: 90vw;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  margin-bottom: var(--space-2);
}
.modal-label {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  margin-top: var(--space-2);
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
</style>
