# -*- coding: utf-8 -*-
import json
import os
import sys
import time
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = r"D:\workshop\stock-valuation\.scratch\live-tickers\screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

SCRATCH_DIR = r"D:\workshop\stock-valuation\.scratch\live-tickers"

def run_acceptance():
    results = {}
    print("=== STARTING FRONTEND ACCEPTANCE VERIFICATION ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # =========================================================================
        # STEP 1: Homepage & Delayed Market Data Disclosure
        # =========================================================================
        print("\n=== STEP 1: Homepage & Delayed Market Data Disclosure ===")
        page.goto("http://127.0.0.1:3000", wait_until="networkidle")
        title = page.title()
        print("Page title:", title)
        assert "美股估值分析" in title or "Stock Valuation" in title, f"Unexpected title: {title}"

        page_text = page.content()
        assert "演示数据为固定测试数据" not in page_text, "Found stale demo-only claim on homepage"
        assert "不保证实时价格" in page_text or "可能存在延迟" in page_text, "Homepage should clarify delayed market data"

        for ticker in ["NVDA", "AAPL", "MSFT", "AVGO"]:
            assert ticker in page_text, f"Missing {ticker} example on homepage"
        
        screenshot_01 = os.path.join(SCREENSHOT_DIR, "01_homepage.png")
        page.screenshot(path=screenshot_01)
        print(f"PASS STEP 1: Homepage branding and disclaimers verified. Screenshot: {screenshot_01}")
        results["homepage"] = "PASS"

        # =========================================================================
        # STEP 2: NVDA Live Search & Delayed Market Data Labelling
        # =========================================================================
        print("\n=== STEP 2: NVDA Live Search & Baseline Response Capture ===")
        nvda_responses = []

        def handle_nvda_response(response):
            if "/api/v1/valuation/NVDA" in response.url and response.request.method == "GET":
                try:
                    nvda_responses.append(response.json())
                except Exception:
                    pass

        page.on("response", handle_nvda_response)

        page.click('button:has-text("NVDA")')
        page.wait_for_url("**/valuation/NVDA")
        page.wait_for_selector("text=NVIDIA Corporation", timeout=30000)
        page.wait_for_selector("text=LIVE 市场数据（可能延迟）", timeout=10000)

        content = page.content()
        assert "DEMO 演示数据" not in content, "Found unexpected DEMO banner on live NVDA"
        assert "NVIDIA Corporation" in content, "Missing NVIDIA Corporation"
        assert "LIVE 市场数据（可能延迟）" in content, "Banner should explicitly label possibly delayed"
        assert "非实时保证" in content or "可能存在延迟" in content, "Should state non-guaranteed real-time"
        assert "财报基准日" in content, "Statement date should be clearly labeled"
        assert "报价日期" in content or "行情日期" in content, "Price quote date should be clearly labeled"

        # Verify baseline response captured
        assert len(nvda_responses) >= 1, "Failed to capture initial NVDA response"
        default_nvda = nvda_responses[0]
        with open(os.path.join(SCRATCH_DIR, "NVDA-verification-response.json"), "w", encoding="utf-8") as f:
            json.dump(default_nvda, f, indent=2, ensure_ascii=False)

        default_pe_base_str = default_nvda.get("valuations", {}).get("forward_pe", {}).get("base", {}).get("price_per_share")
        assert default_pe_base_str is not None, "Missing forward_pe base price in default NVDA response"
        default_pe_base = float(default_pe_base_str)
        print(f"Captured NVDA default forward PE base price: ${default_pe_base:.2f}")

        # Check DCF table
        assert "五年 FCFF 预测与折现" in content, "Missing 5-year DCF table"
        screenshot_02 = os.path.join(SCREENSHOT_DIR, "02_nvda_live.png")
        page.screenshot(path=screenshot_02)
        print(f"PASS STEP 2: Live NVDA verified with NVIDIA Corporation and clear date labelling. Screenshot: {screenshot_02}")
        results["nvda_live"] = "PASS"

        # =========================================================================
        # STEP 3: Override & Reset Controls on NVDA (Gap 1)
        # =========================================================================
        print("\n=== STEP 3: Override & Reset Verification (Assert Values, Counts & Statuses) ===")
        
        # 3A: Submit Override with PE=35
        override_requests = []
        override_responses = []

        def handle_override_req(request):
            if "/api/v1/valuation/NVDA" in request.url and request.method == "POST":
                override_requests.append(request)

        def handle_override_res(response):
            if "/api/v1/valuation/NVDA" in response.url and response.request.method == "POST":
                try:
                    override_responses.append(response.json())
                except Exception:
                    pass

        page.on("request", handle_override_req)
        page.on("response", handle_override_res)

        pe_input = page.locator('label:has-text("P/E 基准") input')
        pe_input.fill("35")
        page.click('button:has-text("应用覆盖并计算")')

        # Wait for recalculation
        page.wait_for_function('() => !document.querySelector(".refresh-indicator")', timeout=10000)
        time.sleep(1)

        assert len(override_requests) == 1, f"Expected exactly 1 POST override request, got {len(override_requests)}"
        post_body = json.loads(override_requests[0].post_data or "{}")
        assert post_body == {"forward_pe": {"base": 35}}, f"Unexpected POST body: {post_body}"
        print(f"POST body verified: {post_body}")

        assert len(override_responses) >= 1, "Failed to capture override response"
        overridden_nvda = override_responses[-1]
        overridden_pe_base_str = overridden_nvda.get("valuations", {}).get("forward_pe", {}).get("base", {}).get("price_per_share")
        assert overridden_pe_base_str is not None, "Missing forward_pe in overridden response"
        overridden_pe_base = float(overridden_pe_base_str)
        print(f"Overridden forward PE base price: ${overridden_pe_base:.2f} (original was ${default_pe_base:.2f})")
        assert overridden_pe_base != default_pe_base, f"Overridden PE base price did not change: {overridden_pe_base} == {default_pe_base}"

        # Assert DOM displays updated PE base price
        pe_card_text = page.locator('.model-card:has-text("市盈率估值")').inner_text()
        assert f"${overridden_pe_base:.2f}" in pe_card_text or f"{overridden_pe_base:.2f}" in pe_card_text, \
            f"DOM PE model card does not display ${overridden_pe_base:.2f}"
        assert pe_input.input_value() == "35", "Input should still display 35"

        screenshot_03 = os.path.join(SCREENSHOT_DIR, "03_nvda_override.png")
        page.screenshot(path=screenshot_03)
        print(f"PASS STEP 3A: Override applied: POST body verified, PE base price changed to ${overridden_pe_base:.2f}. Screenshot: {screenshot_03}")

        # 3B: Simulate 429 on Reset
        print("\n--- Testing simulated 429 on Reset ---")
        count_429 = []
        def route_429(route):
            count_429.append(route.request)
            route.fulfill(
                status=429,
                headers={"Content-Type": "application/json"},
                body=json.dumps({"detail": "Rate limit exceeded"}),
            )

        page.route("**/api/v1/valuation/NVDA*", route_429)
        page.click('button:has-text("重置默认")')
        page.wait_for_selector(".error-panel", timeout=10000)

        assert len(count_429) == 1, f"Expected exactly 1 request on 429 reset, got {len(count_429)}"
        error_panel = page.locator(".error-panel").inner_text()
        assert "HTTP 429" in error_panel, f"Missing HTTP 429 in error panel: {error_panel}"
        assert "数据源请求频率超限" in error_panel, f"Missing rate limit title in error panel: {error_panel}"
        print(f"PASS STEP 3B: 429 on reset yielded exactly 1 request and visible HTTP 429 rate limit panel.")
        screenshot_04_429 = os.path.join(SCREENSHOT_DIR, "04_nvda_reset_429.png")
        page.screenshot(path=screenshot_04_429)
        page.unroute("**/api/v1/valuation/NVDA*")

        # 3C: Simulate 503 on Reset
        print("\n--- Testing simulated 503 on Reset ---")
        count_503 = []
        def route_503(route):
            count_503.append(route.request)
            route.fulfill(
                status=503,
                headers={"Content-Type": "application/json"},
                body=json.dumps({"detail": "Upstream service temporarily unavailable"}),
            )

        page.route("**/api/v1/valuation/NVDA*", route_503)
        page.click('button:has-text("重置默认")')
        page.wait_for_selector(".error-panel", timeout=10000)

        assert len(count_503) == 1, f"Expected exactly 1 request on 503 reset, got {len(count_503)}"
        error_panel_503 = page.locator(".error-panel").inner_text()
        assert "HTTP 503" in error_panel_503, f"Missing HTTP 503 in error panel: {error_panel_503}"
        assert "上游金融数据服务暂不可用" in error_panel_503, f"Missing 503 title in error panel: {error_panel_503}"
        print(f"PASS STEP 3C: 503 on reset yielded exactly 1 request and visible HTTP 503 unavailable panel.")
        screenshot_04_503 = os.path.join(SCREENSHOT_DIR, "04_nvda_reset_503.png")
        page.screenshot(path=screenshot_04_503)
        page.unroute("**/api/v1/valuation/NVDA*")

        # 3D: Successful Live Reset
        print("\n--- Testing live successful Reset ---")
        reset_requests = []
        reset_responses = []

        def handle_reset_req(request):
            if "/api/v1/valuation/NVDA" in request.url and request.method == "GET":
                reset_requests.append(request)

        def handle_reset_res(response):
            if "/api/v1/valuation/NVDA" in response.url and response.request.method == "GET":
                try:
                    reset_responses.append(response.json())
                except Exception:
                    pass

        page.on("request", handle_reset_req)
        page.on("response", handle_reset_res)

        page.click('button:has-text("重置默认")')
        page.wait_for_function('() => !document.querySelector(".error-panel")', timeout=10000)
        page.wait_for_function('() => !document.querySelector(".refresh-indicator")', timeout=10000)
        time.sleep(1)

        # Assert exactly 1 GET request without /reset suffix
        assert len(reset_requests) == 1, f"Expected exactly 1 GET reset request, got {len(reset_requests)}"
        reset_url = reset_requests[0].url
        assert reset_url.endswith("/api/v1/valuation/NVDA"), f"Expected URL without /reset suffix, got {reset_url}"
        assert not reset_url.endswith("/reset"), f"URL must NOT contain /reset: {reset_url}"
        print(f"Verified reset request URL: {reset_url} (no /reset suffix)")

        # Assert all 6 override inputs are cleared
        inputs = page.locator(".override-form input").all()
        assert len(inputs) == 6, f"Expected 6 override inputs, found {len(inputs)}"
        for idx, inp in enumerate(inputs):
            val = inp.input_value()
            assert val == "", f"Override input {idx} was not cleared! Value: '{val}'"
        print("All 6 override inputs are completely cleared.")

        # Assert restored forward PE base price
        pe_card_restored = page.locator('.model-card:has-text("市盈率估值")').inner_text()
        assert f"${default_pe_base:.2f}" in pe_card_restored or f"{default_pe_base:.2f}" in pe_card_restored, \
            f"DOM PE model card does not restore default base price ${default_pe_base:.2f}"
        print(f"Default forward PE base price restored: ${default_pe_base:.2f}")

        screenshot_04 = os.path.join(SCREENSHOT_DIR, "04_nvda_reset.png")
        page.screenshot(path=screenshot_04)
        print(f"PASS STEP 3D: Reset restored default valuation via standard GET without /reset suffix. Screenshot: {screenshot_04}")
        results["nvda_override_reset"] = "PASS"

        # =========================================================================
        # STEP 4: Live AAPL Query (Gap 4)
        # =========================================================================
        print("\n=== STEP 4: Live AAPL Query & Company Identity Evidence ===")
        aapl_responses = []

        def handle_aapl_res(response):
            if "/api/v1/valuation/AAPL" in response.url and response.request.method == "GET":
                try:
                    aapl_responses.append(response.json())
                except Exception:
                    pass

        page.on("response", handle_aapl_res)

        page.fill("header.topbar input", "AAPL")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/AAPL")
        page.wait_for_selector("text=Apple Inc.", timeout=30000)
        page.wait_for_selector("text=LIVE 市场数据（可能延迟）", timeout=10000)

        aapl_content = page.content()
        assert "Apple Inc." in aapl_content, "Missing Apple Inc."
        assert "LIVE 市场数据（可能延迟）" in aapl_content
        assert "财报基准日" in aapl_content
        assert "报价日期" in aapl_content

        assert len(aapl_responses) >= 1, "Failed to capture live AAPL response"
        aapl_data = aapl_responses[0]
        assert aapl_data.get("company_name") == "Apple Inc.", f"Unexpected company name: {aapl_data.get('company_name')}"
        assert aapl_data.get("ticker") == "AAPL"
        with open(os.path.join(SCRATCH_DIR, "AAPL-verification-response.json"), "w", encoding="utf-8") as f:
            json.dump(aapl_data, f, indent=2, ensure_ascii=False)

        screenshot_05 = os.path.join(SCREENSHOT_DIR, "05_aapl_live.png")
        page.screenshot(path=screenshot_05)
        print(f"PASS STEP 4: Live AAPL query verified with Apple Inc. and delayed market labels. Screenshot: {screenshot_05}")
        results["aapl_live"] = "PASS"

        # =========================================================================
        # STEP 5: Live MSFT Query (Gap 4)
        # =========================================================================
        print("\n=== STEP 5: Live MSFT Query & Company Identity Evidence ===")
        msft_responses = []

        def handle_msft_res(response):
            if "/api/v1/valuation/MSFT" in response.url and response.request.method == "GET":
                try:
                    msft_responses.append(response.json())
                except Exception:
                    pass

        page.on("response", handle_msft_res)

        page.fill("header.topbar input", "MSFT")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/MSFT")
        page.wait_for_selector("text=Microsoft Corporation", timeout=30000)
        page.wait_for_selector("text=LIVE 市场数据（可能延迟）", timeout=10000)

        msft_content = page.content()
        assert "Microsoft Corporation" in msft_content, "Missing Microsoft Corporation"
        assert "LIVE 市场数据（可能延迟）" in msft_content
        assert "财报基准日" in msft_content
        assert "报价日期" in msft_content

        assert len(msft_responses) >= 1, "Failed to capture live MSFT response"
        msft_data = msft_responses[0]
        assert msft_data.get("company_name") == "Microsoft Corporation", f"Unexpected company name: {msft_data.get('company_name')}"
        assert msft_data.get("ticker") == "MSFT"
        with open(os.path.join(SCRATCH_DIR, "MSFT-verification-response.json"), "w", encoding="utf-8") as f:
            json.dump(msft_data, f, indent=2, ensure_ascii=False)

        screenshot_06 = os.path.join(SCREENSHOT_DIR, "06_msft_live.png")
        page.screenshot(path=screenshot_06)
        print(f"PASS STEP 5: Live MSFT query verified with Microsoft Corporation and delayed market labels. Screenshot: {screenshot_06}")
        results["msft_live"] = "PASS"

        # =========================================================================
        # STEP 5B: Live AVGO Query & Company Identity Evidence
        # =========================================================================
        print("\n=== STEP 5B: Live AVGO Query & Company Identity Evidence ===")
        avgo_responses = []

        def handle_avgo_res(response):
            if "/api/v1/valuation/AVGO" in response.url and response.request.method == "GET":
                try:
                    avgo_responses.append(response.json())
                except Exception:
                    pass

        page.on("response", handle_avgo_res)

        page.fill("header.topbar input", "AVGO")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/AVGO")
        page.wait_for_selector("text=Broadcom Inc.", timeout=30000)
        page.wait_for_selector("text=LIVE 市场数据（可能延迟）", timeout=10000)

        avgo_content = page.content()
        assert "Broadcom Inc." in avgo_content, "Missing Broadcom Inc."
        assert "LIVE 市场数据（可能延迟）" in avgo_content
        assert "财报基准日" in avgo_content
        assert "报价日期" in avgo_content

        assert len(avgo_responses) >= 1, "Failed to capture live AVGO response"
        avgo_data = avgo_responses[0]
        assert avgo_data.get("company_name") == "Broadcom Inc.", f"Unexpected company name: {avgo_data.get('company_name')}"
        assert avgo_data.get("ticker") == "AVGO"
        with open(os.path.join(SCRATCH_DIR, "AVGO-verification-response.json"), "w", encoding="utf-8") as f:
            json.dump(avgo_data, f, indent=2, ensure_ascii=False)

        screenshot_avgo = os.path.join(SCREENSHOT_DIR, "02_avgo_live.png")
        page.screenshot(path=screenshot_avgo)
        print(f"PASS STEP 5B: Live AVGO query verified with Broadcom Inc. Screenshot: {screenshot_avgo}")
        results["avgo_live"] = "PASS"

        # =========================================================================
        # STEP 5C: Live KO Query & Company Identity Evidence
        # =========================================================================
        print("\n=== STEP 5C: Live KO Query & Company Identity Evidence ===")
        ko_responses = []

        def handle_ko_res(response):
            if "/api/v1/valuation/KO" in response.url and response.request.method == "GET":
                try:
                    ko_responses.append(response.json())
                except Exception:
                    pass

        page.on("response", handle_ko_res)

        page.fill("header.topbar input", "KO")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/KO")
        page.wait_for_selector("text=Coca-Cola", timeout=30000)
        page.wait_for_selector("text=LIVE 市场数据（可能延迟）", timeout=10000)

        ko_content = page.content()
        assert "Coca-Cola" in ko_content, "Missing Coca-Cola"
        assert "LIVE 市场数据（可能延迟）" in ko_content
        assert "财报基准日" in ko_content
        assert "报价日期" in ko_content

        assert len(ko_responses) >= 1, "Failed to capture live KO response"
        ko_data = ko_responses[0]
        assert "Coca-Cola" in ko_data.get("company_name", ""), f"Unexpected company name: {ko_data.get('company_name')}"
        assert ko_data.get("ticker") == "KO"
        with open(os.path.join(SCRATCH_DIR, "KO-verification-response.json"), "w", encoding="utf-8") as f:
            json.dump(ko_data, f, indent=2, ensure_ascii=False)

        screenshot_ko = os.path.join(SCREENSHOT_DIR, "02_ko_live.png")
        page.screenshot(path=screenshot_ko)
        print(f"PASS STEP 5C: Live KO query verified with Coca-Cola. Screenshot: {screenshot_ko}")
        results["ko_live"] = "PASS"

        # =========================================================================
        # STEP 6: Delayed old ticker resolved/rejected after switching to new ticker (Gap 3)
        # =========================================================================
        print("\n=== STEP 6: Race Condition Handling (Delayed Stale Requests on Ticker Switch) ===")
        
        # 6A: Delayed old ticker resolves AFTER switching to NVDA
        print("--- Testing delayed old ticker resolved after switching to NVDA ---")
        delayed_route_resolve = []

        def handle_slow_resolve(route):
            delayed_route_resolve.append(route)

        page.route("**/api/v1/valuation/SLOWRESOLVE*", handle_slow_resolve)

        # Trigger navigation to SLOWRESOLVE
        page.fill("header.topbar input", "SLOWRESOLVE")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/SLOWRESOLVE")
        page.wait_for_selector(".loading-panel", timeout=5000)

        # Now switch to NVDA while SLOWRESOLVE is in-flight
        page.fill("header.topbar input", "NVDA")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/NVDA")

        # Now fulfill the slow old ticker with phantom data
        for r in delayed_route_resolve:
            try:
                r.fulfill(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=json.dumps({
                        "ticker": "SLOWRESOLVE",
                        "company_name": "PHANTOM RESOLVED OLD CORP",
                        "current_price": 999.99,
                        "currency": "USD",
                        "data_quality": "HIGH",
                    }),
                )
            except Exception:
                pass

        # Wait for NVDA to load
        page.wait_for_selector("text=NVIDIA Corporation", timeout=30000)
        time.sleep(1)

        # Assert NVDA is displayed, phantom data is NOT present, spinner is terminated
        content_after_resolve = page.content()
        assert "NVIDIA Corporation" in content_after_resolve, "Current ticker NVDA should be visible"
        assert "PHANTOM RESOLVED OLD CORP" not in content_after_resolve, "Stale resolved ticker overwrote current view!"
        assert page.locator(".loading-panel").count() == 0, "Loading spinner should be terminated"
        print("PASS STEP 6A: Stale resolved request did NOT overwrite current ticker, spinner terminated.")
        screenshot_13 = os.path.join(SCREENSHOT_DIR, "13_delayed_resolve_switch.png")
        page.screenshot(path=screenshot_13)
        page.unroute("**/api/v1/valuation/SLOWRESOLVE*")

        # 6B: Delayed old ticker rejects with 500 AFTER switching to AAPL
        print("--- Testing delayed old ticker rejected after switching to AAPL ---")
        delayed_route_reject = []

        def handle_slow_reject(route):
            delayed_route_reject.append(route)

        page.route("**/api/v1/valuation/SLOWREJECT*", handle_slow_reject)

        # Trigger navigation to SLOWREJECT
        page.fill("header.topbar input", "SLOWREJECT")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/SLOWREJECT")
        page.wait_for_selector(".loading-panel", timeout=5000)

        # Now switch to AAPL while SLOWREJECT is in-flight
        page.fill("header.topbar input", "AAPL")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/AAPL")

        # Now fulfill the slow old ticker with a 500 error
        for r in delayed_route_reject:
            try:
                r.fulfill(
                    status=500,
                    headers={"Content-Type": "application/json"},
                    body=json.dumps({"detail": "Stale 500 error from old ticker"}),
                )
            except Exception:
                pass

        # Wait for AAPL to load
        page.wait_for_selector("text=Apple Inc.", timeout=30000)
        time.sleep(1)

        # Assert AAPL is displayed, error panel is NOT visible, spinner is terminated
        content_after_reject = page.content()
        assert "Apple Inc." in content_after_reject, "Current ticker AAPL should be visible"
        assert page.locator(".error-panel").count() == 0, "Stale rejection displayed false error on current ticker!"
        assert page.locator(".loading-panel").count() == 0, "Loading spinner should be terminated"
        print("PASS STEP 6B: Stale rejected request did NOT display false error on current ticker, spinner terminated.")
        screenshot_14 = os.path.join(SCREENSHOT_DIR, "14_delayed_reject_switch.png")
        page.screenshot(path=screenshot_14)
        page.unroute("**/api/v1/valuation/SLOWREJECT*")
        results["delayed_ticker_switch"] = "PASS"

        # =========================================================================
        # STEP 7: Share-class Tickers (BRK.B and BRK-B)
        # =========================================================================
        print("\n=== STEP 7: Share-class Ticker Verification (BRK.B and BRK-B) ===")
        page.fill("header.topbar input", "BRK.B")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/BRK.B")
        page.wait_for_selector("text=Berkshire Hathaway", timeout=30000)
        page.wait_for_selector("text=LIVE 市场数据（可能延迟）", timeout=10000)
        brk_content = page.content()
        assert "Berkshire Hathaway" in brk_content
        assert "DEMO 演示数据" not in brk_content
        # Financial institution adjustments
        assert "不适用" in brk_content or "not applicable" in brk_content.lower()

        screenshot_09 = os.path.join(SCREENSHOT_DIR, "09_brkb_share_class.png")
        page.screenshot(path=screenshot_09)
        print(f"PASS STEP 7A: BRK.B loaded cleanly with Berkshire Hathaway. Screenshot: {screenshot_09}")

        page.fill("header.topbar input", "BRK-B")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/BRK-B")
        page.wait_for_selector("text=Berkshire Hathaway", timeout=30000)
        print("PASS STEP 7B: BRK-B loaded cleanly.")
        results["share_class_brk"] = "PASS"

        # =========================================================================
        # STEP 7C: TSM ADR Outcome & Accurate Model Availability / Currency Explanation
        # =========================================================================
        print("\n=== STEP 7C: TSM ADR Outcome & Currency Explanation ===")
        tsm_responses = []

        def handle_tsm_res(response):
            if "/api/v1/valuation/TSM" in response.url:
                try:
                    tsm_responses.append({"status": response.status, "body": response.json()})
                except Exception:
                    pass

        page.on("response", handle_tsm_res)

        page.fill("header.topbar input", "TSM")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/TSM")

        # Wait for either hero card or error panel
        page.wait_for_selector(".hero-card, .error-panel", timeout=35000)
        time.sleep(1)
        tsm_content = page.content()

        assert len(tsm_responses) >= 1, "Failed to capture TSM response"
        tsm_res_record = tsm_responses[-1]
        tsm_status = tsm_res_record["status"]
        tsm_body = tsm_res_record["body"]
        with open(os.path.join(SCRATCH_DIR, "TSM-verification-response.json"), "w", encoding="utf-8") as f:
            json.dump(tsm_body, f, indent=2, ensure_ascii=False)

        if tsm_status == 200:
            print("TSM returned HTTP 200 with supported ADR valuation.")
            assert "Taiwan Semiconductor" in tsm_content or "TSM" in tsm_content
            # Check model availability and unavailable reasons
            valuations = tsm_body.get("valuations", {})
            for m_key, m_val in valuations.items():
                if not m_val.get("available"):
                    print(f"TSM model {m_key} unavailable reason: {m_val.get('unavailable_reason')}")
        else:
            print(f"TSM returned HTTP {tsm_status}: {tsm_body}")
            assert "交易所交易基金" not in tsm_content, "TSM ADR must not be misattributed as ETF"
            assert "仅支持稳定正向现金流" not in tsm_content, "TSM must not be misattributed as loss maker"

        screenshot_tsm = os.path.join(SCREENSHOT_DIR, "15_tsm_adr.png")
        page.screenshot(path=screenshot_tsm)
        print(f"PASS STEP 7C: TSM ADR outcome recorded and verified. Screenshot: {screenshot_tsm}")
        results["tsm_adr"] = "PASS"

        # =========================================================================
        # STEP 8: Unsupported Non-Equity / ETF Verification (SPY)
        # =========================================================================
        print("\n=== STEP 8: Unsupported Non-Equity / ETF Verification (SPY) ===")
        page.fill("header.topbar input", "SPY")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/SPY")
        page.wait_for_selector("text=不支持非普通股标的", timeout=25000)
        spy_content = page.content()
        assert "HTTP 422" in spy_content
        assert "交易所交易基金（ETF）" in spy_content or "ETF" in spy_content
        assert "非普通股" in spy_content
        assert "仅支持稳定正向现金流" not in spy_content, "Must not blanket blame cash flow/losses for an ETF"

        screenshot_10 = os.path.join(SCREENSHOT_DIR, "10_spy_unsupported_etf.png")
        page.screenshot(path=screenshot_10)
        print(f"PASS STEP 8: SPY accurately identified as unsupported ETF without false loss-maker excuse. Screenshot: {screenshot_10}")
        results["unsupported_etf"] = "PASS"

        # =========================================================================
        # STEP 9: Request Cancellation Verification
        # =========================================================================
        print("\n=== STEP 9: Request Cancellation Verification ===")
        pending_cancel_routes = []
        page.route("**/api/v1/valuation/TESTCANCEL*", lambda route: pending_cancel_routes.append(route))
        page.fill("header.topbar input", "TESTCANCEL")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/TESTCANCEL")
        cancel_btn = page.locator('button.cancel-button:has-text("取消")')
        cancel_btn.wait_for(timeout=8000)
        cancel_btn.click()
        page.wait_for_selector("text=已取消查询", timeout=5000)
        cancel_content = page.content()
        assert "已取消对 TESTCANCEL 的估值查询" in cancel_content

        screenshot_11 = os.path.join(SCREENSHOT_DIR, "11_cancellation.png")
        page.screenshot(path=screenshot_11)
        for r in pending_cancel_routes:
            try:
                r.abort()
            except Exception:
                pass
        page.unroute("**/api/v1/valuation/TESTCANCEL*")
        print(f"PASS STEP 9: Request cancellation displayed cancellation banner. Screenshot: {screenshot_11}")
        results["cancellation"] = "PASS"

        # =========================================================================
        # STEP 10: Unknown Ticker Error Handling (HTTP 404) & Quick Switch
        # =========================================================================
        print("\n=== STEP 10: Unknown Ticker Error Handling (HTTP 404) ===")
        page.fill("header.topbar input", "ZZZZZ")
        page.click('header.topbar button[type="submit"]')
        page.wait_for_url("**/valuation/ZZZZZ")
        page.wait_for_selector("text=未找到股票标的或暂无财务覆盖", timeout=15000)
        err_content = page.content()
        assert "HTTP 404" in err_content
        assert "重新查询" in err_content
        assert "尝试其他标的" in err_content

        screenshot_07 = os.path.join(SCREENSHOT_DIR, "07_unknown_error.png")
        page.screenshot(path=screenshot_07)
        print(f"PASS STEP 10: Unknown ticker ZZZZZ displayed actionable 404 panel with recovery options. Screenshot: {screenshot_07}")
        results["unknown_error"] = "PASS"

        # =========================================================================
        # STEP 11: Error Recovery back to NVDA
        # =========================================================================
        print("\n=== STEP 11: Error Recovery to NVDA ===")
        page.click('.error-panel button:has-text("NVDA")')
        page.wait_for_url("**/valuation/NVDA")
        page.wait_for_selector("text=NVIDIA Corporation", timeout=30000)
        page.wait_for_selector("text=LIVE 市场数据（可能延迟）", timeout=10000)
        final_content = page.content()
        assert "NVIDIA Corporation" in final_content
        assert "未找到股票标的" not in final_content

        screenshot_08 = os.path.join(SCREENSHOT_DIR, "08_final_nvda_received.png")
        page.screenshot(path=screenshot_08)
        print(f"PASS STEP 11: Smooth recovery back to NVDA. Screenshot: {screenshot_08}")
        results["error_recovery"] = "PASS"

        browser.close()

    print("\n=== ALL FRONTEND ACCEPTANCE VERIFICATION CHECKS PASSED ===")
    for k, v in results.items():
        print(f"  - {k}: {v}")
    return results

if __name__ == "__main__":
    run_acceptance()
