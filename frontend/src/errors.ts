import { ApiError } from "./api";

// API error `code` -> what a person should read. Codes are listed in docs/API.md.
const MESSAGES: Record<string, string> = {
  network_error: "Can't reach the server. Check your connection and try again.",
  invalid_email: "Please enter a valid email address.",
  validation_error: "Some fields are invalid. Please check your input.",
  event_not_found: "This event doesn't exist.",
  registration_closed: "Registration is closed: the event has already started.",
  event_cancelled: "This event has been cancelled.",
  event_started: "The event has already started.",
  registration_not_found: "This ticket link is not valid.",
  already_checked_in: "This ticket was already used for check-in.",
  invalid_credentials: "Wrong password.",
  unauthorized: "Please log in as organizer.",
  starts_in_past: "The date must be in the future.",
  capacity_below_taken: "Capacity can't be lower than the number of seats already taken.",
  ticket_not_found: "Unknown ticket code for this event.",
  invalid_code_format: "That's not a ticket code (8 letters/digits, e.g. ABCD-EFGH).",
  ticket_cancelled: "This ticket was cancelled.",
  ticket_waitlisted: "This person is on the waitlist and has no seat.",
};

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "capacity_below_taken" && typeof error.details.seats_taken === "number") {
      return `Capacity can't be lower than the ${error.details.seats_taken} seats already taken.`;
    }
    return MESSAGES[error.code] ?? error.message;
  }
  return "Something went wrong. Please try again.";
}

export function errorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.code : null;
}
