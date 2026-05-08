/**
 * Helpers for rendering Hevy workout snapshots from `provider_extensions.hevy`.
 */

const KG_TO_LB = 2.2046226218;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Nearest whole pound (no fractions). */
export function kgToLbRounded(kg: number): number {
  return Math.round(kg * KG_TO_LB);
}

export function isWarmupSet(set: Record<string, unknown>): boolean {
  const t = set.type ?? set.set_type;
  return typeof t === 'string' && t.toLowerCase() === 'warmup';
}

/** 1-based set label within an exercise (Hevy uses 0-based `index`). */
export function displaySetNumber(
  set: Record<string, unknown>,
  rowIndex: number
): number {
  if (typeof set.index === 'number' && Number.isFinite(set.index)) {
    return set.index + 1;
  }
  return rowIndex + 1;
}

/**
 * One line for WEIGHT & REPS: integer lbs × reps, or duration/distance fallback.
 */
export function formatWeightRepsLine(set: Record<string, unknown>): string {
  const weightRaw = set.weight_kg ?? set.weightKg ?? set.weight;
  const repsRaw = set.reps;

  const weightKg =
    typeof weightRaw === 'number'
      ? weightRaw
      : typeof weightRaw === 'string'
        ? parseFloat(weightRaw)
        : NaN;
  const reps =
    typeof repsRaw === 'number'
      ? repsRaw
      : typeof repsRaw === 'string'
        ? parseInt(repsRaw, 10)
        : NaN;

  if (Number.isFinite(weightKg) && Number.isFinite(reps) && reps >= 0) {
    const lb = kgToLbRounded(weightKg);
    return `${lb} lbs × ${reps} reps`;
  }

  const durRaw =
    set.duration_seconds ?? set.durationSeconds ?? set.duration ?? null;
  const dur =
    typeof durRaw === 'number'
      ? durRaw
      : typeof durRaw === 'string'
        ? parseInt(durRaw, 10)
        : NaN;
  if (Number.isFinite(dur) && dur > 0) {
    return `${Math.round(dur)}s`;
  }

  const distRaw =
    set.distance_meters ?? set.distanceMeters ?? set.distance ?? null;
  const dist =
    typeof distRaw === 'number'
      ? distRaw
      : typeof distRaw === 'string'
        ? parseFloat(distRaw)
        : NaN;
  if (Number.isFinite(dist) && dist > 0) {
    return dist >= 1000
      ? `${(dist / 1000).toFixed(2)} km`
      : `${Math.round(dist)} m`;
  }

  return '—';
}

/** Prefer API total on workout; else sum(reps × weight_kg) → rounded lb. */
export function computeSessionVolumeLb(
  data: Record<string, unknown>
): number | null {
  const directLb = [
    data.total_volume_lb,
    data.volume_lb,
    data.total_volume_lbs,
  ];
  for (const v of directLb) {
    if (typeof v === 'number' && Number.isFinite(v) && v >= 0) {
      return Math.round(v);
    }
  }

  const directKg = [data.total_volume_kg, data.volume_kg];
  for (const v of directKg) {
    if (typeof v === 'number' && Number.isFinite(v) && v >= 0) {
      return kgToLbRounded(v);
    }
  }

  let sumKg = 0;
  const exercisesRaw = data.exercises;
  if (!Array.isArray(exercisesRaw)) return null;

  for (const ex of exercisesRaw) {
    if (!isRecord(ex)) continue;
    const setsRaw = ex.sets;
    if (!Array.isArray(setsRaw)) continue;
    for (const s of setsRaw) {
      if (!isRecord(s)) continue;
      const wRaw = s.weight_kg ?? s.weightKg ?? s.weight;
      const rRaw = s.reps;
      const w =
        typeof wRaw === 'number'
          ? wRaw
          : typeof wRaw === 'string'
            ? parseFloat(wRaw)
            : NaN;
      const r =
        typeof rRaw === 'number'
          ? rRaw
          : typeof rRaw === 'string'
            ? parseInt(rRaw, 10)
            : NaN;
      if (Number.isFinite(w) && Number.isFinite(r) && w > 0 && r > 0) {
        sumKg += w * r;
      }
    }
  }

  if (sumKg <= 0) return null;
  return kgToLbRounded(sumKg);
}

/** Return a count when the snapshot exposes one; else null (caller shows "—"). */
export function extractRecordsCount(
  data: Record<string, unknown>
): number | null {
  const keys = [
    'personal_records_count',
    'pr_count',
    'records_count',
    'records_broken',
  ];
  for (const k of keys) {
    const v = data[k];
    if (typeof v === 'number' && Number.isFinite(v) && v >= 0) {
      return Math.round(v);
    }
  }

  const prArr = data.personal_records;
  if (Array.isArray(prArr)) {
    return prArr.length;
  }

  return null;
}

export function parseDurationSecondsFromHevySnapshot(
  data: Record<string, unknown>
): number | null {
  const start = data.start_time;
  const end = data.end_time;
  if (typeof start !== 'string' || typeof end !== 'string') return null;
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  if (Number.isNaN(s) || Number.isNaN(e) || e <= s) return null;
  return Math.round((e - s) / 1000);
}

export function sessionTitleFromHevy(data: Record<string, unknown>): string {
  const t = data.title;
  return typeof t === 'string' && t.trim() ? t.trim() : 'Hevy workout';
}
