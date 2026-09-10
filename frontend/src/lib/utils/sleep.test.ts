import { describe, expect, it } from 'vitest';
import {
  classifySleepSource,
  filterSleepSessions,
  getSleepSourceFilterEmptyMessage,
} from './sleep';
import type { SleepSession } from '@/lib/api/types';

function makeSession(
  overrides: Partial<SleepSession> & {
    source?: Partial<SleepSession['source']>;
  } = {}
): SleepSession {
  const { source, ...rest } = overrides;
  return {
    id: 'session-1',
    start_time: '2026-06-25T22:00:00Z',
    end_time: '2026-06-26T06:00:00Z',
    source: {
      provider: 'unknown',
      device: null,
      ...source,
    },
    duration_seconds: 28_800,
    sleep_duration_seconds: 27_000,
    efficiency_percent: 90,
    stages: null,
    sleep_stage_intervals: null,
    is_nap: false,
    ...rest,
  };
}

describe('classifySleepSource', () => {
  it('classifies AutoSleep sessions', () => {
    expect(
      classifySleepSource(
        makeSession({ source: { provider: 'AutoSleep', device: null } })
      )
    ).toBe('autosleep');
  });

  it('classifies Apple Watch sessions by device model', () => {
    expect(
      classifySleepSource(
        makeSession({
          source: { provider: "Calvin's Apple Watch", device: 'Watch7,2' },
        })
      )
    ).toBe('apple_watch');
  });

  it('classifies other providers', () => {
    expect(
      classifySleepSource(
        makeSession({ source: { provider: 'garmin', device: 'Forerunner' } })
      )
    ).toBe('other');
  });
});

describe('filterSleepSessions', () => {
  const sessions = [
    makeSession({
      id: 'autosleep-1',
      source: { provider: 'AutoSleep', device: null },
    }),
    makeSession({
      id: 'watch-1',
      source: { provider: "Calvin's Apple Watch", device: 'Watch7,2' },
    }),
    makeSession({
      id: 'garmin-1',
      source: { provider: 'garmin', device: 'Forerunner' },
    }),
  ];

  it('returns all sessions when filter is all', () => {
    expect(filterSleepSessions(sessions, 'all')).toHaveLength(3);
  });

  it('filters to AutoSleep only', () => {
    const filtered = filterSleepSessions(sessions, 'autosleep');
    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.id).toBe('autosleep-1');
  });

  it('filters to Apple Watch only', () => {
    const filtered = filterSleepSessions(sessions, 'apple_watch');
    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.id).toBe('watch-1');
  });
});

describe('getSleepSourceFilterEmptyMessage', () => {
  it('returns default message for all', () => {
    expect(getSleepSourceFilterEmptyMessage('all')).toBe(
      'No sleep sessions available'
    );
  });

  it('returns filter-specific message for AutoSleep', () => {
    expect(getSleepSourceFilterEmptyMessage('autosleep')).toBe(
      'No AutoSleep sessions on this page'
    );
  });
});
