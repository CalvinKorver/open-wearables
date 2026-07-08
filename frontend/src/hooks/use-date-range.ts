import { useMemo } from 'react';
import { addDays, subDays, startOfDay, getUnixTime } from 'date-fns';
import type { DateRangeValue } from '@/components/ui/date-range-selector';

interface DateRange {
  startDate: string;
  endDate: string;
}

interface DateRangeParams {
  start_date: string;
  end_date: string;
}

interface DateRangeDates {
  startDate: Date;
  endDate: Date;
}

/**
 * Hook to calculate date range from a DateRangeValue (number of days).
 * Returns ISO date strings for API calls.
 *
 * Uses half-open interval [start, end) where:
 * - start = beginning of the first day (N days ago) in local time
 * - end = beginning of tomorrow local (exclusive, so all of today is included)
 */
export function useDateRange(dateRange: DateRangeValue): DateRange {
  return useMemo(() => {
    const today = startOfDay(new Date());
    const end = addDays(today, 1);
    const start = subDays(today, dateRange);

    return {
      startDate: start.toISOString(),
      endDate: end.toISOString(),
    };
  }, [dateRange]);
}

/**
 * Hook to calculate date range from a DateRangeValue (number of days).
 * Returns Date objects for flexible formatting (local time).
 */
export function useDateRangeDates(dateRange: DateRangeValue): DateRangeDates {
  return useMemo(() => {
    const today = startOfDay(new Date());
    return {
      startDate: subDays(today, dateRange),
      endDate: today,
    };
  }, [dateRange]);
}

/**
 * Hook to get an "all time" date range for fetching complete data.
 * Returns a stable object with start_date and end_date for API params.
 *
 * Uses half-open interval [start, end) where end is start of tomorrow local.
 */
export function useAllTimeRange(): DateRangeParams {
  return useMemo(() => {
    const today = startOfDay(new Date());
    const start = new Date('2000-01-01T00:00:00.000Z');
    const end = addDays(today, 1);

    return {
      start_date: start.toISOString(),
      end_date: end.toISOString(),
    };
  }, []);
}

/**
 * Hook to get an "all time" date range as unix timestamps (seconds).
 * Used for APIs that expect unix timestamp format.
 *
 * Uses half-open interval [start, end) where end is start of tomorrow local.
 */
export function useAllTimeRangeTimestamp(): DateRangeParams {
  return useMemo(() => {
    const today = startOfDay(new Date());
    const start = new Date('2000-01-01T00:00:00.000Z');
    const end = addDays(today, 1);

    return {
      start_date: getUnixTime(start).toString(),
      end_date: getUnixTime(end).toString(),
    };
  }, []);
}
