import assert from "node:assert/strict";
import test from "node:test";
import * as jose from "jose";
import { mintLiveKitToken, presignUrl, signThumbnail, verifyThumbnail } from "../src/media.js";

const OSC = {
  endpoint: "http://127.0.0.1:9000",
  bucket: "phone-proctor",
  region: "us-east-1",
  accessKey: "testkey",
  secretKey: "testsecret",
};

test("sigv4 presign produces a signed URL", () => {
  const url = presignUrl(OSC, "PUT", "org/sess/asset", { expiresS: 300 });
  assert.match(url, /^http:\/\/127\.0\.0\.1:9000\/phone-proctor\/org\/sess\/asset\?/);
  assert.match(url, /X-Amz-Algorithm=AWS4-HMAC-SHA256/);
  assert.match(url, /X-Amz-Expires=300/);
  assert.match(url, /X-Amz-Signature=[0-9a-f]{64}/);
});

test("sigv4 presign rejects unconfigured store", () => {
  assert.throws(() =>
    presignUrl({ ...OSC, accessKey: undefined, secretKey: undefined }, "PUT", "k"),
  );
});

test("thumbnail token roundtrip and tamper rejection", () => {
  const exp = Date.now() + 60_000;
  const sig = signThumbnail("secret", "asset-1", exp);
  assert.equal(verifyThumbnail("secret", "asset-1", exp, sig), true);
  assert.equal(verifyThumbnail("secret", "asset-1", exp, sig + "x"), false);
  assert.equal(verifyThumbnail("wrong", "asset-1", exp, sig), false);
  assert.equal(verifyThumbnail("secret", "asset-1", Date.now() - 1000, signThumbnail("secret", "asset-1", Date.now() - 1000)), false);
});

test("livekit token verifies with grants", async () => {
  const token = await mintLiveKitToken(
    { apiKey: "key123", apiSecret: "supersecretvalue" },
    { room: "session-abc", identity: "staff-1", canPublish: false, canSubscribe: true },
  );
  const { payload } = await jose.jwtVerify(token, new TextEncoder().encode("supersecretvalue"), { issuer: "key123" });
  assert.equal(payload.sub, "staff-1");
  assert.deepEqual(payload.video, { roomJoin: true, room: "session-abc", canPublish: false, canSubscribe: true });
});

test("livekit token requires configuration", async () => {
  await assert.rejects(() =>
    mintLiveKitToken({}, { room: "r", identity: "i", canPublish: false, canSubscribe: true }),
  );
});
