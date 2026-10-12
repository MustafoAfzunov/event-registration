import { describe, expect, it } from "vitest";
import {
  capacityTier,
  countdown,
  formatPercent,
  fromLocalInput,
  initialsOf,
  percent,
  timeAgo,
  toLocalInput,
} from "./format";

describe("capacityTier", () => {
  it.each([
    [100, 100, "available"],
    [100, 21, "available"], // 79% taken
    [100, 20, "high"], // exactly 80% taken
    [100, 1, "high"],
    [100, 0, "full"],
    [5, 0, "full"],
    [0, 0, "full"],
  ])("capacity %i with %i seats left is %s", (capacity, left, tier) => {
    expect(capacityTier(capacity, left)).toBe(tier);
  });
});

describe("percent", () => {
  it("rounds to one decimal, caps at 100 and survives an empty total", () => {
    expect(percent(42, 186)).toBe(22.6);
    expect(percent(1, 3)).toBe(33.3);
    expect(percent(5, 3)).toBe(100);
    expect(percent(0, 0)).toBe(0);
    expect(formatPercent(50)).toBe("50%");
    expect(formatPercent(22.6)).toBe("22.6%");
  });
});

describe("countdown", () => {
  const start = "2099-01-10T12:00:00Z";
  const at = (offsetMinutes: number) => new Date(start).getTime() - offsetMinutes * 60_000;
  it("splits the remaining time into days, hours and minutes", () => {
    expect(countdown(start, at(2 * 1440 + 3 * 60 + 4))).toEqual({ started: false, days: 2, hours: 3, minutes: 4 });
    expect(countdown(start, at(59))).toEqual({ started: false, days: 0, hours: 0, minutes: 59 });
  });
  it("reports started at and after the start time", () => {
    expect(countdown(start, at(0)).started).toBe(true);
    expect(countdown(start, at(-5)).started).toBe(true);
  });
});

describe("timeAgo", () => {
  const now = Date.parse("2099-01-01T12:00:00Z");
  const ago = (seconds: number) => new Date(now - seconds * 1000).toISOString();
  it.each([
    [10, "just now"],
    [90, "2 min ago"],
    [3000, "50 min ago"],
    [7200, "2 h ago"],
    [200_000, "2 d ago"],
  ])("%is ago reads %s", (seconds, text) => {
    expect(timeAgo(ago(seconds), now)).toBe(text);
  });
});

describe("initialsOf", () => {
  it("uses two letters for titles and one for emails", () => {
    expect(initialsOf("PyCon Meetup")).toBe("PM");
    expect(initialsOf("Standup")).toBe("S");
    expect(initialsOf("alice.smith@example.com")).toBe("A");
    expect(initialsOf("")).toBe("?");
  });
});

describe("local time inputs", () => {
  it("round-trips an instant through datetime-local in the runtime's time zone", () => {
    const iso = "2099-06-15T09:30:00.000Z";
    expect(fromLocalInput(toLocalInput(iso))).toBe(iso);
  });
});
