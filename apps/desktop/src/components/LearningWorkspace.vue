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
  PhChartBar,
  PhWarningCircle,
  PhFileText,
  PhClock,
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
  listReviewsToday,
  reviewCard,
  topicDashboard,
  weakPoints,
  wrongAnswers,
  weeklyReport,
} from "../api";
import type {
  LearningTopic,
  LearningNode,
  LearningNote,
  LearningQuiz,
  LearningCard,
  GradeResult,
  LearningDashboard,
  WeakPoint,
  WrongAnswer,
  ReviewRating,
} from "../types";

/**
 * 学习工作区 · 第三阶段 M3 + 第四阶段 M2。
 * 左：学习主题列表 + 新建；右：五标签（概览/路线/笔记/练习/卡片）。
 * 概览：仪表盘统计 + 薄弱点 + 错题本 + 周报。
 * 卡片：间隔重复评分（SM-2），due_at 内联更新。
 */
const topics = ref<LearningTopic[]>([]);
const currentId = ref<number | null>(null);
const tab = ref<"overview" | "path" | "notes" | "quiz" | "cards">("overview");

const nodes = ref<LearningNode[]>([]);
const notes = ref<LearningNote[]>([]);
const quizzes = ref<LearningQuiz[]>([]);
const cards = ref<LearningCard[]>([]);
const loadingGen = ref(false);
const genError = ref("");

// 概览（M2）
const dashboard = ref<LearningDashboard | null>(null);
const weak = ref<WeakPoint[]>([]);
const wrong = ref<WrongAnswer[]>([]);
const reportMd = ref("");
const reportBusy = ref(false);
const dueByTopic = ref<Record<number, number>>({});

// 卡片复习（M2）
const onlyDue = ref(false);
const ratingBusy = ref<Set<number>>(new Set());

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
    await refreshDueByTopic();
    if (topics.value.length > 0 && currentId.value === null) {
      await selectTopic(topics.value[0].id);
    }
  } catch {
    topics.value = [];
  }
}

async function refreshDueByTopic() {
  try {
    const due = await listReviewsToday();
    const counts: Record<number, number> = {};
    for (const c of due) {
      counts[c.topic_id] = (counts[c.topic_id] || 0) + 1;
    }
    dueByTopic.value = counts;
  } catch {
    dueByTopic.value = {};
  }
}

async function selectTopic(id: number) {
  currentId.value = id;
  tab.value = "overview";
  quizAnswers.value = {};
  quizResults.value = {};
  onlyDue.value = false;
  reportMd.value = "";
  await loadAll();
}

async function loadAll() {
  if (!currentId.value) return;
  const id = currentId.value;
  try {
    const [n, ns, qs, cs, db, wp, wa] = await Promise.all([
      listLearningNodes(id),
      listLearningNotes(id),
      listQuizzes(id),
      listCards(id),
      topicDashboard(id).catch(() => null),
      weakPoints(id).catch(() => []),
      wrongAnswers(id).catch(() => []),
    ]);
    nodes.value = n;
    notes.value = ns;
    quizzes.value = qs;
    cards.value = cs;
    dashboard.value = db;
    weak.value = wp;
    wrong.value = wa;
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
    // 新卡 due_at=now 立即到期，刷新主题 due 徽标。
    await refreshDueByTopic();
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

// ============ 卡片复习评分（M2）============

const RATINGS: { v: ReviewRating; label: string; cls: string }[] = [
  { v: "again", label: "忘记", cls: "bad" },
  { v: "hard", label: "模糊", cls: "warn" },
  { v: "good", label: "记得", cls: "ok" },
  { v: "easy", label: "熟练", cls: "great" },
];

function parseDue(s: string): number {
  // 后端 due_at 为 naive UTC（与 created_at 同基准），补 "Z" 当 UTC 解析。
  return new Date(s + "Z").getTime();
}

function dueLabel(card: LearningCard): string {
  if (!card.due_at) return "未排期";
  const due = parseDue(card.due_at);
  const now = Date.now();
  if (due <= now) return "今日到期";
  const diff = due - now;
  if (diff < 86400000) return `${Math.max(1, Math.round(diff / 3600000))} 小时后`;
  return `${Math.ceil(diff / 86400000)} 天后`;
}

function isDue(card: LearningCard): boolean {
  if (!card.due_at) return true;
  return parseDue(card.due_at) <= Date.now();
}

const cardsFiltered = computed(() =>
  onlyDue.value ? cards.value.filter((c) => isDue(c)) : cards.value
);

async function rateCard(cardId: number, r: ReviewRating) {
  ratingBusy.value = new Set(ratingBusy.value).add(cardId);
  try {
    const idx = cards.value.findIndex((c) => c.id === cardId);
    // 评分前是否到期：仅到期卡评分后不再到期才扣减 due 徽标，避免给未到期卡评分误减。
    const wasDue = idx >= 0 ? isDue(cards.value[idx]) : false;
    const res = await reviewCard(cardId, r);
    if (idx >= 0) {
      cards.value[idx] = { ...cards.value[idx], ...res.card };
    }
    if (wasDue && !isDue(res.card) && currentId.value != null) {
      const cur = dueByTopic.value[currentId.value] || 0;
      dueByTopic.value = {
        ...dueByTopic.value,
        [currentId.value]: Math.max(0, cur - 1),
      };
    }
  } catch (e) {
    alert("评分失败：" + String(e));
  } finally {
    const s = new Set(ratingBusy.value);
    s.delete(cardId);
    ratingBusy.value = s;
  }
}

// ============ 周报（M2）============

async function genWeeklyReport() {
  if (!currentId.value) return;
  reportBusy.value = true;
  try {
    const r = await weeklyReport(currentId.value);
    reportMd.value = r.report_md;
  } catch (e) {
    alert("周报生成失败：" + String(e));
  } finally {
    reportBusy.value = false;
  }
}

async function saveReportAsNote() {
  if (!currentId.value || !reportMd.value) return;
  try {
    await saveLearningNote({
      topic_id: currentId.value,
      title: `${currentTopic.value?.title || "学习"} 学习周报`,
      body_md: reportMd.value,
    });
    notes.value = await listLearningNotes(currentId.value);
    alert("已保存为学习笔记");
  } catch (e) {
    alert("保存失败：" + String(e));
  }
}

function exportReport() {
  if (!reportMd.value) return;
  const blob = new Blob([reportMd.value], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${currentTopic.value?.title || "学习"}-周报.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
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
            <span v-if="dueByTopic[t.id]" class="due-badge">{{ dueByTopic[t.id] }} 待复习</span>
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
          <button :class="{ active: tab === 'overview' }" @click="tab = 'overview'">
            <PhChartBar :size="14" /> 概览
          </button>
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

          <!-- 概览 -->
          <div v-if="tab === 'overview'" class="overview-tab">
            <div v-if="dashboard" class="stats-grid">
              <div class="stat">
                <span class="stat-num">{{ dashboard.due_today }}</span>
                <span class="stat-label">今日待复习</span>
              </div>
              <div class="stat">
                <span class="stat-num">{{ dashboard.total_cards }}</span>
                <span class="stat-label">卡片总数</span>
              </div>
              <div class="stat">
                <span class="stat-num">{{ dashboard.reviewed_cards }}</span>
                <span class="stat-label">已复习</span>
              </div>
              <div class="stat">
                <span class="stat-num">{{ dashboard.mastered_nodes }}/{{ dashboard.total_nodes }}</span>
                <span class="stat-label">掌握节点</span>
              </div>
              <div class="stat">
                <span class="stat-num">{{ dashboard.reviews_7d }}</span>
                <span class="stat-label">近 7 天复习</span>
              </div>
              <div class="stat">
                <span class="stat-num">{{ dashboard.total_lapses }}</span>
                <span class="stat-label">遗忘次数</span>
              </div>
              <div class="stat">
                <span class="stat-num">{{ quizzes.length }}</span>
                <span class="stat-label">练习题</span>
              </div>
            </div>
            <div v-else class="tab-empty">暂无统计数据</div>

            <div class="overview-section">
              <div class="ov-head"><PhWarningCircle :size="14" /> 薄弱点</div>
              <div v-if="weak.length === 0" class="tab-empty">暂无薄弱点，继续保持</div>
              <div v-else class="weak-list">
                <div v-for="w in weak" :key="`${w.kind}-${w.id}`" class="weak-item">
                  <span class="weak-kind" :class="w.kind">{{ w.kind === 'node' ? '节点' : '卡片' }}</span>
                  <span class="weak-title pa-ellipsis">{{ w.title }}</span>
                  <span v-if="w.lapse_count" class="weak-meta">遗忘 {{ w.lapse_count }} 次</span>
                </div>
              </div>
            </div>

            <div class="overview-section">
              <div class="ov-head"><PhQuestion :size="14" /> 错题本</div>
              <div v-if="wrong.length === 0" class="tab-empty">暂无错题</div>
              <div v-else class="wrong-list">
                <div v-for="w in wrong" :key="w.attempt_id" class="wrong-item">
                  <div class="wrong-q">{{ w.question }}</div>
                  <div class="wrong-ans">你的答案：{{ w.user_answer || '（空）' }}</div>
                  <div class="wrong-ref">参考：{{ w.reference_answer }}</div>
                </div>
              </div>
            </div>

            <div class="overview-section">
              <div class="ov-head">
                <span><PhFileText :size="14" /> 学习周报</span>
                <div class="ov-actions">
                  <button
                    v-if="reportMd"
                    class="pa-btn pa-btn--subtle pa-btn--sm"
                    @click="saveReportAsNote"
                  >保存为笔记</button>
                  <button
                    v-if="reportMd"
                    class="pa-btn pa-btn--subtle pa-btn--sm"
                    @click="exportReport"
                  >导出 Markdown</button>
                  <button
                    class="pa-btn pa-btn--primary pa-btn--sm"
                    :disabled="reportBusy"
                    @click="genWeeklyReport"
                  >
                    {{ reportBusy ? "生成中…" : "生成周报" }}
                  </button>
                </div>
              </div>
              <pre v-if="reportMd" class="report-md">{{ reportMd }}</pre>
              <div v-else class="tab-empty">点击「生成周报」生成本周学习报告</div>
            </div>
          </div>

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
            <div class="cards-head">
              <button class="pa-btn pa-btn--primary pa-btn--sm" :disabled="loadingGen" @click="genCards">
                <PhSparkle :size="14" />
                {{ loadingGen ? "生成中…" : "生成 5 张复习卡片" }}
              </button>
              <label class="due-toggle">
                <input type="checkbox" v-model="onlyDue" /> 仅看今日到期
              </label>
            </div>
            <div v-if="cards.length === 0" class="tab-empty">尚无复习卡片</div>
            <div v-else-if="cardsFiltered.length === 0" class="tab-empty">今日无到期卡片 🎉</div>
            <div class="card-grid">
              <div v-for="c in cardsFiltered" :key="c.id" class="card-cell">
                <div
                  class="flash-card"
                  :class="{ flipped: flipped.has(c.id) }"
                  @click="flip(c.id)"
                >
                  <div class="flash-inner">
                    <div class="flash-face front">
                      <span class="flash-label">问题</span>
                      <p>{{ c.front }}</p>
                      <span class="card-due" :class="{ due: isDue(c) }">
                        <PhClock :size="11" /> {{ dueLabel(c) }}
                      </span>
                    </div>
                    <div class="flash-face back">
                      <span class="flash-label">答案</span>
                      <p>{{ c.back }}</p>
                    </div>
                  </div>
                </div>
                <div class="card-actions" @click.stop>
                  <button
                    v-for="r in RATINGS"
                    :key="r.v"
                    class="rate-btn"
                    :class="r.cls"
                    :disabled="ratingBusy.has(c.id)"
                    @click="rateCard(c.id, r.v)"
                  >{{ r.label }}</button>
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

/* 主题 due 徽标 */
.due-badge {
  color: var(--color-warning-fg);
  background: var(--color-warning-soft);
  padding: 0 6px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  margin-left: 4px;
}

/* 概览（M2） */
.overview-tab {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--space-2);
}
.stat {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-num {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  color: var(--color-fg);
}
.stat-label {
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
}
.overview-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.ov-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--color-fg-muted);
}
.ov-head > span {
  display: flex;
  align-items: center;
  gap: 4px;
}
.ov-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.weak-list,
.wrong-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.weak-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
}
.weak-kind {
  flex-shrink: 0;
  font-size: var(--text-xs);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  color: var(--color-fg-faint);
  background: var(--color-surface-sunken);
}
.weak-kind.card {
  color: var(--color-warning-fg);
  background: var(--color-warning-soft);
}
.weak-title {
  flex: 1;
  min-width: 0;
}
.weak-meta {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--color-danger-fg);
}
.wrong-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
}
.wrong-q {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  margin-bottom: var(--space-1);
}
.wrong-ans {
  font-size: var(--text-xs);
  color: var(--color-danger-fg);
  margin-bottom: 2px;
}
.wrong-ref {
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
}
.report-md {
  margin: 0;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-fg-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 360px;
  overflow: auto;
}

/* 卡片复习（M2） */
.cards-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}
.due-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  color: var(--color-fg-muted);
  cursor: pointer;
}
.card-cell {
  display: flex;
  flex-direction: column;
}
.card-due {
  margin-top: auto;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: var(--text-xs);
  color: var(--color-fg-faint);
  align-self: flex-start;
}
.card-due.due {
  color: var(--color-warning-fg);
}
.card-actions {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
  padding: var(--space-2) 0 0;
}
.rate-btn {
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-fg-muted);
  font-size: var(--text-xs);
  padding: var(--space-1) 0;
  border-radius: var(--radius);
  cursor: pointer;
}
.rate-btn:hover:not(:disabled) {
  background: var(--color-surface-sunken);
}
.rate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.rate-btn.bad {
  color: var(--color-danger-fg);
  border-color: var(--color-danger-soft);
}
.rate-btn.warn {
  color: var(--color-warning-fg);
  border-color: var(--color-warning-soft);
}
.rate-btn.ok {
  color: var(--color-success-fg);
  border-color: var(--color-success-soft);
}
.rate-btn.great {
  color: var(--color-accent);
  border-color: var(--color-accent-soft);
}
</style>
