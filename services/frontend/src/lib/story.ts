// The Revision Studio's draft: a normalized Story plus the pure reducer every edit goes
// through. Every edit returns a new object, so `draft !== base` is the dirty check and a
// reset simply restores `base`.

import type { Brief, Character, Scene, Shot, Story } from "@/api/client";

type WithRequired<T, K extends keyof T> = T & Required<Pick<T, K>>;

export type StoryEntity = WithRequired<Character, "reference_image_ids">;
export type StoryShot = WithRequired<Shot, "duration_s" | "subject_ids">;
export type EntityKind = "character" | "location";

export interface StoryDraft {
  brief: WithRequired<Brief, "target_duration_s" | "style" | "narration_voice_id">;
  world: { characters: StoryEntity[]; locations: StoryEntity[] };
  script: { title: string; logline: string; scenes: Scene[] };
  shots: StoryShot[];
}

export const SHOT_TYPES = ["establishing", "wide", "aerial", "medium", "close-up", "detail"];
export const MAX_DESCRIPTION_CHARS = 500;

/** Fill every field the generated types leave optional. */
export function normalizeStory(story: Story): StoryDraft {
  const entity = (e: Character): StoryEntity => ({
    ...e,
    reference_image_ids: e.reference_image_ids ?? [],
  });
  return {
    brief: {
      premise: story.brief.premise,
      target_duration_s: story.brief.target_duration_s ?? 90,
      style: story.brief.style ?? null,
      narration_voice_id: story.brief.narration_voice_id ?? null,
    },
    world: {
      characters: (story.world.characters ?? []).map(entity),
      locations: (story.world.locations ?? []).map(entity),
    },
    script: {
      title: story.script.title,
      logline: story.script.logline,
      scenes: story.script.scenes ?? [],
    },
    shots: (story.shots ?? []).map((shot) => ({
      ...shot,
      duration_s: shot.duration_s ?? 3,
      subject_ids: shot.subject_ids ?? [],
    })),
  };
}

// ---------------------------------------------------------------------------
// Ids and lookups
// ---------------------------------------------------------------------------

function slug(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "new"
  );
}

function allEntityIds(story: StoryDraft): Set<string> {
  return new Set([...story.world.characters, ...story.world.locations].map((e) => e.id));
}

export function newEntityId(story: StoryDraft, kind: EntityKind, name: string): string {
  const prefix = kind === "character" ? "char_" : "loc_";
  const taken = allEntityIds(story);
  const base = `${prefix}${slug(name)}`;
  let candidate = base;
  for (let n = 2; taken.has(candidate); n += 1) candidate = `${base}_${n}`;
  return candidate;
}

export function nextSceneId(story: StoryDraft): string {
  const numbers = story.script.scenes
    .map((scene) => /^scene_(\d+)$/.exec(scene.id)?.[1])
    .filter((n): n is string => n !== undefined)
    .map(Number);
  return `scene_${String(Math.max(0, ...numbers) + 1).padStart(2, "0")}`;
}

export function newShotId(story: StoryDraft): string {
  const taken = new Set(story.shots.map((shot) => shot.id));
  let n = 1;
  while (taken.has(`new_${n}`)) n += 1;
  return `new_${n}`;
}

export function shotsOfScene(story: StoryDraft, sceneId: string): StoryShot[] {
  return story.shots.filter((shot) => shot.scene_id === sceneId);
}

/** entity id -> the shots it appears in (as the location or a subject). */
export function entityUsage(story: StoryDraft): Map<string, string[]> {
  const usage = new Map<string, string[]>();
  const add = (id: string, shotId: string) => {
    const bucket = usage.get(id);
    if (bucket) bucket.push(shotId);
    else usage.set(id, [shotId]);
  };
  for (const shot of story.shots) {
    add(shot.location_id, shot.id);
    for (const subject of shot.subject_ids) add(subject, shot.id);
  }
  return usage;
}

/** The world location a scene's free-text `location` names, if any. */
export function locationForScene(story: StoryDraft, scene: Scene): string {
  const wanted = scene.location.trim().toLowerCase();
  const named = story.world.locations.find((l) => l.name.trim().toLowerCase() === wanted);
  return named?.id ?? story.world.locations[0]?.id ?? "";
}

// ---------------------------------------------------------------------------
// The reducer
// ---------------------------------------------------------------------------

type BriefField = "premise" | "target_duration_s" | "style" | "narration_voice_id";
type EntityPatch = Partial<Pick<StoryEntity, "name" | "canonical_description">>;
type ScenePatch = Partial<Omit<Scene, "id">>;
type ShotPatch = Partial<Omit<StoryShot, "id">>;

export type StoryAction =
  | { type: "setBrief"; field: BriefField; value: string | number | null }
  | { type: "setScript"; field: "title" | "logline"; value: string }
  | { type: "addEntity"; kind: EntityKind; entity: StoryEntity }
  | { type: "updateEntity"; id: string; patch: EntityPatch }
  | { type: "removeEntity"; id: string }
  | { type: "addScene"; afterId: string | null; scene: Scene }
  | { type: "updateScene"; id: string; patch: ScenePatch }
  | { type: "moveScene"; id: string; delta: number }
  | { type: "removeScene"; id: string }
  | { type: "addShot"; shot: StoryShot }
  | { type: "updateShot"; id: string; patch: ShotPatch }
  | { type: "moveShot"; id: string; delta: number }
  | { type: "removeShot"; id: string }
  | { type: "replace"; story: StoryDraft };

function move<T>(items: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (index < 0 || target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** Keep shots grouped by scene, in scene order: playback order is scene order. */
function grouped(story: StoryDraft): StoryDraft {
  const order = new Map(story.script.scenes.map((scene, index) => [scene.id, index]));
  const indexed = story.shots.map((shot, index) => ({ shot, index }));
  indexed.sort(
    (a, b) =>
      (order.get(a.shot.scene_id) ?? order.size) - (order.get(b.shot.scene_id) ?? order.size) ||
      a.index - b.index,
  );
  return { ...story, shots: indexed.map((entry) => entry.shot) };
}

function mapEntities(
  story: StoryDraft,
  fn: (entity: StoryEntity) => StoryEntity,
): StoryDraft["world"] {
  return {
    characters: story.world.characters.map(fn),
    locations: story.world.locations.map(fn),
  };
}

export function storyReducer(story: StoryDraft, action: StoryAction): StoryDraft {
  switch (action.type) {
    case "setBrief":
      return { ...story, brief: { ...story.brief, [action.field]: action.value } };
    case "setScript":
      return { ...story, script: { ...story.script, [action.field]: action.value } };
    case "addEntity": {
      const key = action.kind === "character" ? "characters" : "locations";
      return { ...story, world: { ...story.world, [key]: [...story.world[key], action.entity] } };
    }
    case "updateEntity":
      return {
        ...story,
        world: mapEntities(story, (e) => (e.id === action.id ? { ...e, ...action.patch } : e)),
      };
    case "removeEntity": {
      if (story.world.locations.some((l) => l.id === action.id)) {
        if (story.shots.some((shot) => shot.location_id === action.id)) return story;
        return {
          ...story,
          world: {
            ...story.world,
            locations: story.world.locations.filter((l) => l.id !== action.id),
          },
        };
      }
      return {
        ...story,
        world: {
          ...story.world,
          characters: story.world.characters.filter((c) => c.id !== action.id),
        },
        shots: story.shots.map((shot) =>
          shot.subject_ids.includes(action.id)
            ? { ...shot, subject_ids: shot.subject_ids.filter((s) => s !== action.id) }
            : shot,
        ),
      };
    }
    case "addScene": {
      const scenes = [...story.script.scenes];
      const at =
        action.afterId === null
          ? scenes.length
          : scenes.findIndex((s) => s.id === action.afterId) + 1;
      scenes.splice(at, 0, action.scene);
      return { ...story, script: { ...story.script, scenes } };
    }
    case "updateScene":
      return {
        ...story,
        script: {
          ...story.script,
          scenes: story.script.scenes.map((s) =>
            s.id === action.id ? { ...s, ...action.patch } : s,
          ),
        },
      };
    case "moveScene": {
      const index = story.script.scenes.findIndex((s) => s.id === action.id);
      const scenes = move(story.script.scenes, index, action.delta);
      if (scenes === story.script.scenes) return story;
      return grouped({ ...story, script: { ...story.script, scenes } });
    }
    case "removeScene":
      return {
        ...story,
        script: { ...story.script, scenes: story.script.scenes.filter((s) => s.id !== action.id) },
        shots: story.shots.filter((shot) => shot.scene_id !== action.id),
      };
    case "addShot":
      return grouped({ ...story, shots: [...story.shots, action.shot] });
    case "updateShot":
      return grouped({
        ...story,
        shots: story.shots.map((shot) =>
          shot.id === action.id ? { ...shot, ...action.patch } : shot,
        ),
      });
    case "moveShot": {
      const shot = story.shots.find((s) => s.id === action.id);
      if (!shot) return story;
      const sceneShots = shotsOfScene(story, shot.scene_id);
      const moved = move(sceneShots, sceneShots.indexOf(shot), action.delta);
      if (moved === sceneShots) return story;
      let cursor = 0;
      return {
        ...story,
        shots: story.shots.map((s) => (s.scene_id === shot.scene_id ? moved[cursor++] : s)),
      };
    }
    case "removeShot":
      return { ...story, shots: story.shots.filter((shot) => shot.id !== action.id) };
    case "replace":
      return action.story;
  }
}
