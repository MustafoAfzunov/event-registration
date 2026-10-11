import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { AppRoutes } from "../App";

export const HEALTH = { "GET /api/health": { body: { status: "ok", db: "ok" } } };

/** Render the real route table at `path` (the same components the browser gets). */
export function renderAt(path: string) {
  const user = userEvent.setup();
  const utils = render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
  return { user, ...utils };
}
