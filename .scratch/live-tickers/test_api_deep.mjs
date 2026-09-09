// Test harness for frontend/lib/api.ts
// Tests actual timeout handler, delayed response body after headers,
// cancellation during body decoding, and reset valuation semantics.

import http from "node:http";
import assert from "node:assert/strict";

// We will point NEXT_PUBLIC_BACKEND_URL to our local test server
let testServerPort = 0;
let testServer = null;

// Track request logs
const serverLogs = [];

function startTestServer() {
  return new Promise((resolve) => {
    testServer = http.createServer((req, res) => {
      const url = new URL(req.url, `http://127.0.0.1:${testServerPort}`);
      serverLogs.push({ method: req.method, path: url.pathname, headers: req.headers });

      // Route 1: Slow headers (never responds or exceeds timeout)
      if (url.pathname === "/api/v1/valuation/SLOW_HEADER") {
        // Do not write head; keep socket open to trigger header timeout
        return;
      }

      // Route 2: Delayed response body after headers (headers sent immediately, body delayed)
      if (url.pathname === "/api/v1/valuation/SLOW_BODY") {
        res.writeHead(200, {
          "Content-Type": "application/json; charset=utf-8",
          "Transfer-Encoding": "chunked",
        });
        res.write('{"ticker":"SLOW_BODY","company_name":"Slow Body Corp",');
        // Do not finish; pause body to test stream timeout
        return;
      }

      // Route 3: Stream cancellation during body decoding
      if (url.pathname === "/api/v1/valuation/CANCEL_BODY") {
        res.writeHead(200, {
          "Content-Type": "application/json; charset=utf-8",
          "Transfer-Encoding": "chunked",
        });
        res.write('{"ticker":"CANCEL_BODY","chunk":');
        // Keep open so client can abort while decoding body
        return;
      }

      // Route 4: Reset endpoint - normal GET
      if (url.pathname === "/api/v1/valuation/RESET_OK") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
          ticker: "RESET_OK",
          company_name: "Reset Ok Corp",
          current_price: 100,
          currency: "USD",
          valuations: {
            forward_pe: { base: { price_per_share: "100.00" } },
          },
        }));
        return;
      }

      // Route 5: Reset endpoint - 429 Rate Limit
      if (url.pathname === "/api/v1/valuation/RESET_429") {
        res.writeHead(429, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: "Rate limit exceeded" }));
        return;
      }

      // Route 6: Reset endpoint - 503 Unavailable
      if (url.pathname === "/api/v1/valuation/RESET_503") {
        res.writeHead(503, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: "Upstream service unavailable" }));
        return;
      }

      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "Not found" }));
    });

    testServer.listen(0, "127.0.0.1", () => {
      testServerPort = testServer.address().port;
      resolve(testServerPort);
    });
  });
}

async function runTests() {
  console.log("=== STARTING API DEEP VERIFICATION TESTS ===");
  const port = await startTestServer();
  console.log(`Local test streaming server listening on http://127.0.0.1:${port}`);

  process.env.NEXT_PUBLIC_BACKEND_URL = `http://127.0.0.1:${port}`;

  // Dynamically import api.ts so it picks up the test server URL
  const {
    ApiError,
    requestValuation,
    fetchValuation,
    resetValuation,
  } = await import("../../frontend/lib/api.ts");

  let passed = 0;
  let failed = 0;

  // TEST 1: Header timeout deadline
  try {
    console.log("\n[TEST 1] Testing actual timeout handler on slow headers (deadline = 120ms)...");
    const startTime = Date.now();
    let errorCaught = null;
    try {
      await requestValuation("SLOW_HEADER", { timeoutMs: 120 });
    } catch (err) {
      errorCaught = err;
    }
    const elapsed = Date.now() - startTime;
    assert.ok(errorCaught, "Expected timeout error to be thrown");
    assert.ok(errorCaught instanceof ApiError, `Expected ApiError, got ${errorCaught}`);
    assert.equal(errorCaught.status, 0, `Expected status 0, got ${errorCaught.status}`);
    assert.equal(errorCaught.code, "TIMEOUT", `Expected code TIMEOUT, got ${errorCaught.code}`);
    assert.equal(errorCaught.actionableTitle, "请求超时", `Expected title 请求超时, got ${errorCaught.actionableTitle}`);
    assert.ok(errorCaught.message.includes("请求超时"), `Expected message to contain timeout notice, got ${errorCaught.message}`);
    assert.ok(elapsed >= 100, `Expected elapsed >= 100ms, was ${elapsed}ms`);
    console.log(`✓ PASS: Header timeout caught after ${elapsed}ms: code=TIMEOUT, title="${errorCaught.actionableTitle}"`);
    passed++;
  } catch (e) {
    console.error("✗ FAIL TEST 1:", e);
    failed++;
  }

  // TEST 2: Delayed response body after headers (cleanup bug reproduction & verification)
  try {
    console.log("\n[TEST 2] Testing delayed response body after headers (deadline = 120ms)...");
    const startTime = Date.now();
    let errorCaught = null;
    try {
      await requestValuation("SLOW_BODY", { timeoutMs: 120 });
    } catch (err) {
      errorCaught = err;
    }
    const elapsed = Date.now() - startTime;
    assert.ok(errorCaught, "Expected timeout error on delayed response body");
    assert.ok(errorCaught instanceof ApiError, `Expected ApiError, got ${errorCaught}`);
    assert.equal(errorCaught.status, 0, `Expected status 0, got ${errorCaught.status}`);
    assert.equal(errorCaught.code, "TIMEOUT", `Expected code TIMEOUT, got ${errorCaught.code}`);
    assert.equal(errorCaught.actionableTitle, "请求超时", `Expected title 请求超时, got ${errorCaught.actionableTitle}`);
    assert.ok(elapsed >= 100, `Expected elapsed >= 100ms, was ${elapsed}ms`);
    console.log(`✓ PASS: Body streaming timeout caught after ${elapsed}ms: code=TIMEOUT, title="${errorCaught.actionableTitle}"`);
    passed++;
  } catch (e) {
    console.error("✗ FAIL TEST 2:", e);
    failed++;
  }

  // TEST 3: Cancellation during body decoding
  try {
    console.log("\n[TEST 3] Testing caller cancellation while decoding response body...");
    const callerController = new AbortController();
    let errorCaught = null;

    // Trigger abort 50ms after starting, while body stream is stalled
    setTimeout(() => {
      callerController.abort("USER_EXPLICIT_ABORT");
    }, 50);

    try {
      await requestValuation("CANCEL_BODY", {
        signal: callerController.signal,
        timeoutMs: 5000,
      });
    } catch (err) {
      errorCaught = err;
    }

    assert.ok(errorCaught, "Expected abort error to be thrown");
    // Should NOT be an ApiError (it is an abort, not network error or timeout)
    assert.ok(
      (errorCaught instanceof DOMException && errorCaught.name === "AbortError") ||
      errorCaught.name === "AbortError" ||
      callerController.signal.aborted,
      `Expected AbortError or caller signal aborted, got ${errorCaught}`
    );
    assert.ok(
      !(errorCaught instanceof ApiError && errorCaught.code === "TIMEOUT"),
      "User cancellation must not be misclassified as TIMEOUT"
    );
    assert.ok(
      !(errorCaught instanceof ApiError && errorCaught.code === "NETWORK_ERROR"),
      "User cancellation must not be misclassified as NETWORK_ERROR"
    );
    assert.equal(callerController.signal.aborted, true, "Caller signal must be marked aborted");
    assert.equal(callerController.signal.reason, "USER_EXPLICIT_ABORT", "Caller reason must be preserved");
    console.log("✓ PASS: Cancellation during body decoding aborted cleanly without false TIMEOUT or NETWORK_ERROR");
    passed++;
  } catch (e) {
    console.error("✗ FAIL TEST 3:", e);
    failed++;
  }

  // TEST 4: Reset Valuation request structure
  try {
    console.log("\n[TEST 4] Testing resetValuation request format and URL (assert no /reset suffix)...");
    serverLogs.length = 0;
    const res = await resetValuation("RESET_OK");
    assert.equal(res.ticker, "RESET_OK");
    assert.equal(serverLogs.length, 1, `Expected exactly 1 request, got ${serverLogs.length}`);
    const req = serverLogs[0];
    assert.equal(req.method, "GET", `Expected GET method, got ${req.method}`);
    assert.equal(req.path, "/api/v1/valuation/RESET_OK", `Expected path without /reset suffix, got ${req.path}`);
    assert.ok(!req.path.includes("/reset"), `Path must NOT contain /reset: ${req.path}`);
    console.log("✓ PASS: resetValuation issued exactly 1 standard GET without /reset suffix and restored default data");
    passed++;
  } catch (e) {
    console.error("✗ FAIL TEST 4:", e);
    failed++;
  }

  // TEST 5: Reset with upstream 429 Rate Limit
  try {
    console.log("\n[TEST 5] Testing resetValuation with simulated 429 Rate Limit...");
    serverLogs.length = 0;
    let errorCaught = null;
    try {
      await resetValuation("RESET_429");
    } catch (err) {
      errorCaught = err;
    }
    assert.equal(serverLogs.length, 1, `Expected exactly 1 request without retry on 429, got ${serverLogs.length}`);
    assert.ok(errorCaught instanceof ApiError, `Expected ApiError, got ${errorCaught}`);
    assert.equal(errorCaught.status, 429, `Expected status 429, got ${errorCaught.status}`);
    assert.equal(errorCaught.code, "RATE_LIMITED", `Expected code RATE_LIMITED, got ${errorCaught.code}`);
    assert.equal(errorCaught.actionableTitle, "数据源请求频率超限 (Rate Limit)", `Expected title 数据源请求频率超限 (Rate Limit), got ${errorCaught.actionableTitle}`);
    console.log("✓ PASS: 429 on reset resulted in exactly 1 request and correctly structured RATE_LIMITED ApiError");
    passed++;
  } catch (e) {
    console.error("✗ FAIL TEST 5:", e);
    failed++;
  }

  // TEST 6: Reset with upstream 503 Unavailable
  try {
    console.log("\n[TEST 6] Testing resetValuation with simulated 503 Service Unavailable...");
    serverLogs.length = 0;
    let errorCaught = null;
    try {
      await resetValuation("RESET_503");
    } catch (err) {
      errorCaught = err;
    }
    assert.equal(serverLogs.length, 1, `Expected exactly 1 request without retry on 503, got ${serverLogs.length}`);
    assert.ok(errorCaught instanceof ApiError, `Expected ApiError, got ${errorCaught}`);
    assert.equal(errorCaught.status, 503, `Expected status 503, got ${errorCaught.status}`);
    assert.equal(errorCaught.code, "UPSTREAM_UNAVAILABLE", `Expected code UPSTREAM_UNAVAILABLE, got ${errorCaught.code}`);
    assert.equal(errorCaught.actionableTitle, "上游金融数据服务暂不可用", `Expected title 上游金融数据服务暂不可用, got ${errorCaught.actionableTitle}`);
    console.log("✓ PASS: 503 on reset resulted in exactly 1 request and correctly structured UPSTREAM_UNAVAILABLE ApiError");
    passed++;
  } catch (e) {
    console.error("✗ FAIL TEST 6:", e);
    failed++;
  }

  testServer.close();
  console.log(`\n=== API DEEP TEST SUMMARY: ${passed} PASSED, ${failed} FAILED ===`);
  if (failed > 0) {
    process.exit(1);
  }
}

runTests().catch((err) => {
  console.error("Unexpected test run failure:", err);
  if (testServer) testServer.close();
  process.exit(1);
});
