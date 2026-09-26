import { useCallback, useReducer } from "react";
import { storyReducer, type StoryAction, type StoryDraft } from "@/lib/story";

interface DraftState {
  base: StoryDraft;
  draft: StoryDraft;
}

function reducer(state: DraftState, action: StoryAction | { type: "reset" }): DraftState {
  if (action.type === "reset") return { ...state, draft: state.base };
  const draft = storyReducer(state.draft, action);
  return draft === state.draft ? state : { ...state, draft };
}

/** The studio's working copy of a story, seeded once from `base`. */
export function useStoryDraft(base: StoryDraft) {
  const [state, dispatch] = useReducer(reducer, { base, draft: base });
  const reset = useCallback(() => dispatch({ type: "reset" }), []);
  return {
    base: state.base,
    draft: state.draft,
    dirty: state.draft !== state.base,
    dispatch: dispatch as (action: StoryAction) => void,
    reset,
  };
}
