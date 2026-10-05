import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(cleanup);
if (typeof HTMLDialogElement !== "undefined") {
  HTMLDialogElement.prototype.showModal ||= function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ||= function () {
    this.removeAttribute("open");
  };
}
