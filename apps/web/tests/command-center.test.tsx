import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import CommandCenterPage from "../app/page";

describe("command center placeholder", () => {
  it("clearly identifies the initial vertical and unfinished product surface", () => {
    render(createElement(CommandCenterPage));

    expect(
      screen.getByRole("heading", { name: "Facilities operations command center" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/foundation environment/i)).toBeInTheDocument();
    expect(screen.getByText(/work-order workflows are not implemented/i)).toBeInTheDocument();
  });
});
