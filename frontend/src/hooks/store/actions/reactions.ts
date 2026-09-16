import type { ReactionValue, WorkflowState } from "../state";
import type { Actions } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;

export function reactionActions(set: Set): Pick<Actions, "toggleReaction"> {
  return {
    toggleReaction: (msgId, reaction: ReactionValue) => {
      set((s) => {
        const prev = s.messageReactions[msgId] ?? null;
        const next: ReactionValue = reaction === prev ? null : reaction;
        return { messageReactions: { ...s.messageReactions, [msgId]: next } };
      });
    },
  };
}