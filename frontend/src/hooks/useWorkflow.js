import { useReducer } from "react";
import { useExecution } from "./useExecution";
import { usePlan } from "./usePlan";
import { useUpload } from "./useUpload";
import { initialState, reduceWorkflow } from "../domain/workflow";
export function useWorkflow() {
    const [state, dispatch] = useReducer(reduceWorkflow, initialState);
    const onUploaded = (file) => dispatch({ type: "UPLOAD_SUCCESS", file });
    const onUploadError = (error) => dispatch({ type: "UPLOAD_FAIL", error });
    const onPlanned = (plan) => dispatch({ type: "PLAN_SUCCESS", plan });
    const onPlanError = (error) => dispatch({ type: "PLAN_FAIL", error });
    const onExecuted = (result) => dispatch({ type: "EXECUTE_SUCCESS", result });
    const onExecError = (error) => dispatch({ type: "EXECUTE_FAIL", error });
    const upload = useUpload(onUploaded, onUploadError);
    const plan = usePlan(onPlanned, onPlanError);
    const execute = useExecution(onExecuted, onExecError);
    return {
        state,
        dispatch,
        upload,
        plan,
        execute,
    };
}
