import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { App } from "./App.tsx";

it("renders a button that counts clicks", () => {
  render(<App />);
  const button = screen.getByRole("button");
  expect(button).toHaveTextContent("Clicked 0 times");
  fireEvent.click(button);
  expect(button).toHaveTextContent("Clicked 1 times");
});
