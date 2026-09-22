import { codingFetchJson, codingJsonInit } from "./codingHttp";
import type { ControlRequest } from "./recovery";

export interface PlanningReceipt {
  request_id: string;
  kind: "answer" | "implement";
  status: "applied";
  result_run_id: string;
}

export interface PlanAnswerRequest extends ControlRequest {
  input_id: string;
  answers: Record<string, string>;
}

export interface PlanImplementRequest extends ControlRequest {
  expected_plan_version: number;
}

export const answerPlanQuestion = (runId: string, data: PlanAnswerRequest): Promise<PlanningReceipt> =>
  codingFetchJson(`/agent-runs/${encodeURIComponent(runId)}/answer`, codingJsonInit("POST", data));

export const implementRunPlan = (runId: string, data: PlanImplementRequest): Promise<PlanningReceipt> =>
  codingFetchJson(`/agent-runs/${encodeURIComponent(runId)}/implement-plan`, codingJsonInit("POST", data));
