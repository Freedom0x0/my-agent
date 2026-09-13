import { useReducer } from "react";

import { useExecution } from "./useExecution";
import { usePlan } from "./usePlan";
import { useUpload } from "./useUpload";
import { initialState, reduceWorkflow, type WorkflowAction } from "../domain/workflow";
import type { ExecutionView, FileItem, PlanView } from "../domain/models";

export function useWorkflow() {
  const [state, dispatch] = useReducer(reduceWorkflow, initialState);

  const onUploaded = (file: FileItem) => dispatch({ type: "UPLOAD_SUCCESS", file });
  const onUploadError = (error: { errorCode: string; message: string }) =>
    dispatch({ type: "UPLOAD_FAIL", error });

  const onPlanned = (plan: PlanView) => dispatch({ type: "PLAN_SUCCESS", plan });
  const onPlanError = (error: { errorCode: string; message: string }) =>
    dispatch({ type: "PLAN_FAIL", error });

  const onExecuted = (result: ExecutionView) => dispatch({ type: "EXECUTE_SUCCESS", result });
  const onExecError = (error: { errorCode: string; message: string }) =>
    dispatch({ type: "EXECUTE_FAIL", error });

  const upload = useUpload(onUploaded, onUploadError);
  const plan = usePlan(onPlanned, onPlanError);
  const execute = useExecution(onExecuted, onExecError);

  return {
    state,
    dispatch,
    upload,
    plan,
    execute,
  } as const;
}

export type WorkflowController = ReturnType<typeof useWorkflow>;
export type Dispatch = (action: WorkflowAction) => void;