export const initialState = {
    status: "idle",
    files: [],
    selectedFileIds: [],
    requestText: "",
    plan: null,
    result: null,
    error: null,
};
export function reduceWorkflow(state, action) {
    switch (action.type) {
        case "UPLOAD_START":
            return { ...state, status: "uploading", error: null };
        case "UPLOAD_SUCCESS":
            return {
                ...state,
                status: "inspected",
                files: [...state.files, action.file],
                selectedFileIds: [...state.selectedFileIds, action.file.id],
                error: null,
            };
        case "UPLOAD_FAIL":
            return { ...state, status: "error", error: action.error };
        case "PLAN_START":
            return { ...state, status: "planning", error: null };
        case "PLAN_SUCCESS":
            return { ...state, status: "plan_ready", plan: action.plan };
        case "PLAN_FAIL":
            return { ...state, status: "error", error: action.error };
        case "EXECUTE_START":
            return { ...state, status: "executing", error: null };
        case "EXECUTE_SUCCESS":
            return { ...state, status: "completed", result: action.result };
        case "EXECUTE_FAIL":
            return { ...state, status: "error", error: action.error };
        case "SET_REQUEST":
            return { ...state, requestText: action.request };
        case "CLEAR_ERROR":
            return { ...state, error: null };
        case "RESET":
            return initialState;
        default:
            return state;
    }
}
