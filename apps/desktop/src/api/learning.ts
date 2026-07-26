import { apiFetch, ensureApiBase } from "./http";
import type {
  GradeResult,
  LearningCard,
  LearningDashboard,
  LearningNode,
  LearningNote,
  LearningQuiz,
  LearningTopic,
  ReviewRating,
  ReviewResponse,
  WeakPoint,
  WeeklyReport,
  WrongAnswer,
} from "../types";

// ---- 学习系统（第三阶段 M0 骨架 / M3 实现）----
export async function listLearningTopics(): Promise<LearningTopic[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createLearningTopic(data: {
  title: string;
  goal?: string;
  level?: string;
  tags?: string[];
}): Promise<LearningTopic> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function updateLearningTopic(
  id: number,
  data: Partial<{
    title: string;
    goal: string;
    level: string;
    status: string;
    tags: string[];
  }>
): Promise<LearningTopic> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function generateLearningPlan(
  topicId: number,
  sourceDocIds?: number[]
): Promise<LearningNode[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_doc_ids: sourceDocIds }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listLearningNodes(topicId: number): Promise<LearningNode[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/nodes`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function saveLearningNote(data: {
  topic_id?: number;
  title: string;
  body_md: string;
  source_refs?: unknown[];
}): Promise<LearningNote> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listLearningNotes(
  topicId?: number
): Promise<LearningNote[]> {
  const base = await ensureApiBase();
  const qs = topicId ? `?topic_id=${topicId}` : "";
  const r = await apiFetch(`${base}/learning/notes${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function generateQuiz(
  topicId: number,
  sourceDocIds?: number[],
  count = 5
): Promise<LearningQuiz[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/quizzes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_doc_ids: sourceDocIds, count }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listQuizzes(topicId: number): Promise<LearningQuiz[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/quizzes`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function gradeQuizAnswer(
  quizId: number,
  userAnswer: string
): Promise<GradeResult> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/quiz-attempts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quiz_id: quizId, user_answer: userAnswer }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function generateCards(
  topicId: number,
  sourceDocIds?: number[],
  count = 5
): Promise<LearningCard[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/cards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_doc_ids: sourceDocIds, count }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function listCards(topicId: number): Promise<LearningCard[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/cards`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ---- 学习复习（第四阶段 M2）----
export async function listReviewsToday(
  topicId?: number
): Promise<LearningCard[]> {
  const base = await ensureApiBase();
  const qs = topicId != null ? `?topic_id=${topicId}` : "";
  const r = await apiFetch(`${base}/learning/reviews/today${qs}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function reviewCard(
  cardId: number,
  rating: ReviewRating
): Promise<ReviewResponse> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/cards/${cardId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function topicDashboard(
  topicId: number
): Promise<LearningDashboard> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/dashboard`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function weakPoints(topicId: number): Promise<WeakPoint[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/weak-points`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function wrongAnswers(topicId: number): Promise<WrongAnswer[]> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/wrong-answers`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function weeklyReport(topicId: number): Promise<WeeklyReport> {
  const base = await ensureApiBase();
  const r = await apiFetch(`${base}/learning/topics/${topicId}/weekly-report`, {
    method: "POST",
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.json();
}
