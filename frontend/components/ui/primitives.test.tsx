import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dropdown } from "./primitives";

describe("Dropdown", () => {
  it("uses sanitized stable option ids for option elements and aria-activedescendant", () => {
    const handleChange = vi.fn();

    render(
      <Dropdown
        ariaLabel="Surface"
        value={"jobs / detail"}
        onChange={handleChange}
        options={[
          { value: "jobs / detail", label: "Jobs Detail" },
          { value: "commerce:listing", label: "Commerce Listing" },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "Surface" }));

    const listbox = screen.getByRole("listbox");
    const activeDescendant = listbox.getAttribute("aria-activedescendant");
    const activeOption = screen.getByRole("option", { name: "Jobs Detail" });

    expect(activeOption.id).toMatch(/jobs-detail$/);
    expect(activeOption.id).not.toBe("jobs / detail");
    expect(activeOption.id).not.toContain(" ");
    expect(activeOption).toHaveAttribute("role", "option");
    expect(listbox).toHaveAttribute("aria-activedescendant", activeOption.id);
    expect(document.getElementById(activeDescendant ?? "")).toBe(activeOption);

    const otherOption = screen.getByRole("option", { name: "Commerce Listing" });
    expect(otherOption.id).toMatch(/commerce-listing$/);
    expect(otherOption.id).not.toContain(" ");
  });
});
