/*
 * Behaviour tests for ui/js/bridge-client.js: native/mock resolution, late pywebviewready
 * upgrade, monotonic sequence ordering, in-flight deduplication, error handling, and mock deltas.
 */

import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { createDomEnvironment } from "./dom-harness.js";
import {
  createBrowserMockApi,
  getBackendApi,
  invokeApi,
  isMockBackend,
  resetBridgeStateForTests,
  resolveBackendApi,
  setBackendUpgradeHandler,
  setEnvelopeHandler
} from "../../ui/js/bridge-client.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("resolveBackendApi()", () => {
  let dom;

  beforeEach(() => {
    dom = createDomEnvironment({
      elementsById: {
        "status-banner": { tag: "div" },
        "toast-region": { tag: "div" }
      }
    });
    dom.install();
    resetBridgeStateForTests();
  });

  afterEach(() => {
    resetBridgeStateForTests();
  });

  test("resolves immediately when window.pywebview.api is already present", async () => {
    const nativeApi = { get_initial_state: async () => ({ ok: true }) };
    dom.window.pywebview = { api: nativeApi };

    const api = await resolveBackendApi({ timeoutMs: 20 });
    assert.equal(api, nativeApi);
    assert.equal(getBackendApi(), nativeApi);
    assert.equal(isMockBackend(), false);
  });

  test("resolves native api when pywebviewready fires before timeout", async () => {
    const nativeApi = { get_initial_state: async () => ({ ok: true }) };
    const promise = resolveBackendApi({ timeoutMs: 120 });

    setTimeout(() => {
      dom.window.pywebview = { api: nativeApi };
      dom.window.dispatchEvent("pywebviewready");
    }, 5);

    const api = await promise;
    assert.equal(api, nativeApi);
    assert.equal(isMockBackend(), false);
  });

  test("falls back to mock after timeout and upgrades seamlessly on late pywebviewready", async () => {
    const nativeApi = { get_initial_state: async () => ({ ok: true }) };
    const upgrades = [];
    setBackendUpgradeHandler((upgraded) => upgrades.push(upgraded));

    const fallbackApi = await resolveBackendApi({ timeoutMs: 10 });
    assert.equal(isMockBackend(), true);
    assert.equal(typeof fallbackApi.get_initial_state, "function");

    dom.window.pywebview = { api: nativeApi };
    dom.window.dispatchEvent("pywebviewready");

    assert.equal(isMockBackend(), false);
    assert.equal(getBackendApi(), nativeApi);
    assert.deepEqual(upgrades, [nativeApi]);
  });
});

describe("invokeApi()", () => {
  let dom;

  beforeEach(async () => {
    dom = createDomEnvironment({
      elementsById: {
        "status-banner": { tag: "div" },
        "toast-region": { tag: "div" }
      }
    });
    dom.install();
    resetBridgeStateForTests();
    dom.window.pywebview = { api: { ping: async () => ({ ok: true }) } };
    await resolveBackendApi();
  });

  afterEach(() => {
    resetBridgeStateForTests();
  });

  test("returns false when backendApi is not resolved", async () => {
    resetBridgeStateForTests();
    const ok = await invokeApi(() => Promise.resolve({ ok: true }));
    assert.equal(ok, false);
  });

  test("deduplicates concurrent in-flight requests sharing a dedupeKey", async () => {
    const d = deferred();
    let callCount = 0;
    const envelopes = [];
    setEnvelopeHandler((env) => envelopes.push(env));

    const p1 = invokeApi(
      () => {
        callCount += 1;
        return d.promise;
      },
      null,
      { silent: true, poll: true, dedupeKey: "poll:ambilight" }
    );
    const p2 = invokeApi(
      () => {
        callCount += 1;
        return Promise.resolve({ ok: true });
      },
      null,
      { silent: true, poll: true, dedupeKey: "poll:ambilight" }
    );

    assert.equal(await p2, false);
    assert.equal(callCount, 1);

    d.resolve({ ok: true, ambilight: { active: true } });
    assert.equal(await p1, true);
    assert.equal(envelopes.length, 1);

    const p3 = await invokeApi(
      () => {
        callCount += 1;
        return Promise.resolve({ ok: true, ambilight: { active: true } });
      },
      null,
      { silent: true, poll: true, dedupeKey: "poll:ambilight" }
    );
    assert.equal(p3, true);
    assert.equal(callCount, 2);
  });

  test("drops stale poll and stale mutation responses out of sequence order", async () => {
    const slowPoll = deferred();
    const slowMutation = deferred();
    const fastMutation = deferred();
    const applied = [];
    setEnvelopeHandler((env) => applied.push(env.tag));

    const pollPromise = invokeApi(() => slowPoll.promise, null, { silent: true, poll: true });
    const mut1Promise = invokeApi(() => slowMutation.promise, "m1");
    const mut2Promise = invokeApi(() => fastMutation.promise, "m2");

    fastMutation.resolve({ ok: true, tag: "mut2" });
    assert.equal(await mut2Promise, true);

    slowMutation.resolve({ ok: true, tag: "mut1" });
    assert.equal(await mut1Promise, false);

    slowPoll.resolve({ ok: true, tag: "poll" });
    assert.equal(await pollPromise, false);

    assert.deepEqual(applied, ["mut2"]);
  });

  test("shows error toast with working retry and ignores stale poll errors", async () => {
    const slowPoll = deferred();
    const fastMutation = deferred();

    const pollPromise = invokeApi(() => slowPoll.promise, null, { silent: true, poll: true });
    const mutPromise = invokeApi(() => fastMutation.promise, null, { silent: true });
    fastMutation.resolve({ ok: true });
    await mutPromise;

    slowPoll.reject(new Error("stale poll timeout"));
    assert.equal(await pollPromise, false);
    assert.equal(dom.getById("toast-region").children.length, 0);

    let attempts = 0;
    const failed = await invokeApi(() => {
      attempts += 1;
      if (attempts === 1) return Promise.reject(new Error("socket closed"));
      return Promise.resolve({ ok: true });
    });
    assert.equal(failed, false);
    assert.match(dom.getById("status-banner").textContent, /status\.commError/);
    const retryBtn = dom.getById("toast-region").querySelector(".toast-action");
    assert.ok(retryBtn);
    retryBtn.click();
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(attempts, 2);
  });
});

describe("createBrowserMockApi()", () => {
  test("returns delta payloads for status polls and mutates mock state", async () => {
    const api = createBrowserMockApi();
    const init = await api.get_initial_state();
    assert.equal(init.ok, true);
    assert.equal(init.bulbs.length, 1);

    await api.set_language("es");
    await api.set_theme("atmospheric-dark");
    await api.set_power(true, 70, null);
    await api.set_brightness(60, null);
    await api.set_color(10, 20, 30, 80, null);
    await api.set_temperature(3000, 90, null);
    await api.set_builtin_scene(1, 120, 75, null);
    await api.select_targets(["192.168.0.34"]);
    await api.add_manual_bulb("192.168.0.99", "Hall");
    await api.rename_bulb("192.168.0.99", "Corridor");
    await api.save_custom_scene("Evening");
    await api.update_custom_scene("preset01", "Warmth+", true);
    await api.set_custom_scene_favorite("preset02", true);
    await api.apply_custom_scene("preset01", null);
    await api.delete_custom_scene("preset02");
    await api.start_sleep_timer(5, null);
    await api.cancel_sleep_timer();

    await api.start_ambilight(1, "vibrant", true, 80, 0.4, null, 12);
    const ambiDelta = await api.get_ambilight_status();
    assert.equal(ambiDelta.ok, true);
    assert.equal(ambiDelta.ambilight.active, true);
    assert.equal(ambiDelta.bulbs, undefined);
    assert.equal(ambiDelta.scenes, undefined);
    await api.stop_ambilight();

    await api.start_music_sync("spectrum", 1.2, 0.5, true, 80, -1, null);
    const musicDelta = await api.get_music_sync_status();
    assert.equal(musicDelta.ok, true);
    assert.equal(musicDelta.music_sync.active, true);
    assert.equal(musicDelta.bulbs, undefined);
    assert.equal(musicDelta.scenes, undefined);
    await api.stop_music_sync();
  });
});
