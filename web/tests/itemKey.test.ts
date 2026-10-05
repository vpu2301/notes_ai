import { describe, expect, it } from "vitest";
import cases from "./fixtures/item-keys.json";
import { lineKey, sha256Hex } from "../src/lib/itemKey";

describe("a generated line's key (Summary Engine v2, Q5)", () => {
  it("is sha256", () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  it.each(cases as { line: string; key: string }[])("matches the server for %j", ({ line, key }) => {
    expect(lineKey(line)).toBe(key);
  });
});
