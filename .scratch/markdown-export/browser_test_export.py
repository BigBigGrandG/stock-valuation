import re
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:3000"
EVIDENCE_DIR = Path("D:/workshop/stock-valuation/.scratch/markdown-export/evidence")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

def run_tests():
    print("=== Starting Comprehensive Playwright Browser Markdown Export Acceptance Tests ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # ---------------------------------------------------------------------
        # Test 1: NVDA Baseline Flow, Exact Numerical Assertions & Zero Extra Requests
        # ---------------------------------------------------------------------
        print("\n[Test 1] NVDA Complete Valuation Page & Exact Baseline Numerical Assertions")
        page.goto(f"{BASE_URL}/valuation/NVDA")
        page.wait_for_selector(".hero-card h1", timeout=30000)
        
        h1_text = page.locator(".hero-card h1").inner_text()
        print(f"  Loaded page heading: {h1_text}")
        assert "NVIDIA" in h1_text

        export_btn = page.locator("button.export-button")
        assert export_btn.is_visible(), "Export button should be visible"
        assert export_btn.is_enabled(), "Export button should be enabled"
        btn_text = export_btn.inner_text()
        print(f"  Found button text: '{btn_text}'")
        assert "导出 Markdown" in btn_text

        page.screenshot(path=str(EVIDENCE_DIR / "01_nvda_page.png"))

        # Monitor network requests to assert EXACTLY ZERO requests on export click
        network_calls = []
        def track_call(req):
            network_calls.append(req.url)

        page.on("request", track_call)

        with page.expect_download() as download_info:
            export_btn.click()
        
        download = download_info.value
        page.remove_listener("request", track_call)

        filename_1 = download.suggested_filename
        print(f"  Downloaded file: {filename_1}")
        assert re.match(r"^NVDA_valuation_\d{8}_\d{6}\.md$", filename_1)
        assert len(network_calls) == 0, f"Expected 0 network calls during export, got: {network_calls}"

        path_1 = EVIDENCE_DIR / filename_1
        download.save_as(str(path_1))
        content_1 = path_1.read_text(encoding="utf-8")

        # Exact baseline numerical assertions
        print("  Verifying exact baseline numerical values in exported Markdown...")
        assert "# NVIDIA Corporation (NVDA) 估值分析报告" in content_1
        assert "- **股票代码**：NVDA" in content_1
        assert "- **报价币种**：USD" in content_1
        assert "- **数据模式**：LIVE 真实市场与财务数据" in content_1
        assert "- **报告导出时间**：" in content_1

        # Check assumptions table with applied status
        assert "| 前瞻市盈率 (P/E Multiple) | 18.00x | **20.00x** | 22.00x | 系统默认基准 |" in content_1
        assert "| EV / EBITDA 倍数 | 18.00x | **22.00x** | 26.00x | 系统默认基准 |" in content_1

        # Check exact scenario values for Forward P/E (EPS 9.31 * 20 = 186.20)
        assert "| **基准 (Base)** | **$186.20** |" in content_1
        assert "前瞻 EPS: 9.31 · 目标 P/E: 20.00x" in content_1

        # Check EV/EBITDA scenario intermediates
        assert "EV: $4.45T" in content_1
        assert "净负债: $-51.52B" in content_1
        assert "股权价值: $4.50T" in content_1

        # Check DCF 3 scenarios
        assert "##### 【悲观情景】" in content_1
        assert "##### 【基准情景】" in content_1
        assert "##### 【乐观情景】" in content_1
        assert "| 企业价值 (Enterprise Value, EV) | **$4.76T** |" in content_1
        assert "| **每股公允价值** | **$199.10** |" in content_1

        print("  ✓ Test 1 passed: Exact baseline values verified with 0 extra network calls!")

        # ---------------------------------------------------------------------
        # Test 2: Unsaved Form Edit Safety (Unsaved inputs are NOT exported)
        # ---------------------------------------------------------------------
        print("\n[Test 2] Unsaved Form Edit Safety Proof")
        # User types 99.5 into P/E override input, but DOES NOT submit
        pe_input = page.locator(".override-form input").first
        pe_input.fill("99.5")
        print("  Filled P/E override input with unsaved '99.5' (no submit clicked)")

        network_calls_unsaved = []
        page.on("request", lambda r: network_calls_unsaved.append(r.url))

        with page.expect_download() as dl_unsaved_info:
            export_btn.click()

        dl_unsaved = dl_unsaved_info.value
        filename_unsaved = dl_unsaved.suggested_filename
        path_unsaved = EVIDENCE_DIR / filename_unsaved
        dl_unsaved.save_as(str(path_unsaved))
        content_unsaved = path_unsaved.read_text(encoding="utf-8")

        assert len(network_calls_unsaved) == 0, f"Expected 0 requests, got: {network_calls_unsaved}"

        # Proof: unsaved 99.5 is NOT exported, old applied baseline is strictly preserved
        assert "99.5" not in content_unsaved, "Unsaved form edit must NEVER appear in exported markdown!"
        assert "| 前瞻市盈率 (P/E Multiple) | 18.00x | **20.00x** | 22.00x | 系统默认基准 |" in content_unsaved
        assert "| **基准 (Base)** | **$186.20** |" in content_unsaved
        print("  ✓ Test 2 passed: Unsaved edit '99.5' was correctly ignored; active result preserved!")

        # ---------------------------------------------------------------------
        # Test 3: Applied Override Propagates Exact Changed Numbers
        # ---------------------------------------------------------------------
        print("\n[Test 3] Applied Override: Exact Changed Numbers in Export")
        pe_input.fill("25")
        submit_btn = page.locator(".override-form button[type='submit']")
        
        # Click submit and wait for override POST response
        with page.expect_response(lambda r: "/valuation/" in r.url and r.request.method == "POST") as resp_info:
            submit_btn.click()
        
        override_resp = resp_info.value
        assert override_resp.status == 200, f"Expected 200 on override, got {override_resp.status}"
        print("  Override applied successfully.")

        network_calls_override = []
        page.on("request", lambda r: network_calls_override.append(r.url))

        with page.expect_download() as dl_override_info:
            export_btn.click()

        dl_override = dl_override_info.value
        filename_override = dl_override.suggested_filename
        path_override = EVIDENCE_DIR / filename_override
        dl_override.save_as(str(path_override))
        content_override = path_override.read_text(encoding="utf-8")

        assert len(network_calls_override) == 0, f"Expected 0 requests, got: {network_calls_override}"

        # Exact changed numerical assertions:
        # EPS 9.31 * 25.00 = 232.75
        print("  Verifying exact changed numbers after applied P/E override (25)...")
        assert "| 前瞻市盈率 (P/E Multiple) | 22.50x | **25.00x** | 27.50x | 用户覆盖生效 | User override |" in content_override
        assert "| **基准 (Base)** | **$232.75** |" in content_override
        assert "前瞻 EPS: 9.31 · 目标 P/E: 25.00x" in content_override
        print("  ✓ Test 3 passed: Exact changed target $232.75 and '用户覆盖生效' verified!")

        # ---------------------------------------------------------------------
        # Test 4: Reset Restores Exact Baseline Defaults
        # ---------------------------------------------------------------------
        print("\n[Test 4] Reset Restores Exact Baseline Defaults")
        reset_btn = page.locator("button:has-text('↺ 重置默认')")
        
        with page.expect_response(lambda r: "/valuation/" in r.url and r.request.method == "GET") as reset_resp_info:
            reset_btn.click()
        
        reset_resp = reset_resp_info.value
        assert reset_resp.status == 200, f"Expected 200 on reset, got {reset_resp.status}"
        print("  Reset applied successfully.")

        network_calls_reset = []
        page.on("request", lambda r: network_calls_reset.append(r.url))

        with page.expect_download() as dl_reset_info:
            export_btn.click()

        dl_reset = dl_reset_info.value
        filename_reset = dl_reset.suggested_filename
        path_reset = EVIDENCE_DIR / filename_reset
        dl_reset.save_as(str(path_reset))
        content_reset = path_reset.read_text(encoding="utf-8")

        assert len(network_calls_reset) == 0, f"Expected 0 requests, got: {network_calls_reset}"

        # Exact restored values
        assert "| 前瞻市盈率 (P/E Multiple) | 18.00x | **20.00x** | 22.00x | 系统默认基准 |" in content_reset
        assert "| **基准 (Base)** | **$186.20** |" in content_reset
        print("  ✓ Test 4 passed: Reset restored exact baseline $186.20 and '系统默认基准'!")

        # ---------------------------------------------------------------------
        # Test 5: Ticker Switch to AAPL (No Stale NVDA Data)
        # ---------------------------------------------------------------------
        print("\n[Test 5] Ticker Switch to AAPL: Transition Safety & Correct Company Export")
        # Click quick tag AAPL
        aapl_tag = page.locator("button.quick-tag:has-text('AAPL')")
        aapl_tag.click()

        # Wait for AAPL page to finish loading
        page.wait_for_selector(".hero-card h1:has-text('Apple')", timeout=30000)
        print("  AAPL page loaded.")

        export_btn_aapl = page.locator("button.export-button")
        assert export_btn_aapl.is_enabled()

        network_calls_aapl = []
        page.on("request", lambda r: network_calls_aapl.append(r.url))

        with page.expect_download() as dl_aapl_info:
            export_btn_aapl.click()

        dl_aapl = dl_aapl_info.value
        filename_aapl = dl_aapl.suggested_filename
        print(f"  AAPL downloaded filename: {filename_aapl}")
        assert re.match(r"^AAPL_valuation_\d{8}_\d{6}\.md$", filename_aapl)
        assert len(network_calls_aapl) == 0, f"Expected 0 requests, got: {network_calls_aapl}"

        path_aapl = EVIDENCE_DIR / filename_aapl
        dl_aapl.save_as(str(path_aapl))
        content_aapl = path_aapl.read_text(encoding="utf-8")

        # Verify correct AAPL company, no stale NVDA data
        assert "# Apple Inc. (AAPL) 估值分析报告" in content_aapl
        assert "- **股票代码**：AAPL" in content_aapl
        assert "NVIDIA Corporation" not in content_aapl
        assert "NVDA" not in content_aapl
        print("  ✓ Test 5 passed: AAPL exported cleanly with no stale NVDA data!")

        # ---------------------------------------------------------------------
        # Test 6: TSM ADR Foreign Currency Isolation & Unavailable Reason Preservation
        # ---------------------------------------------------------------------
        print("\n[Test 6] TSM ADR Foreign Stock: Preserves Exact Unavailable Isolation Reason")
        page.goto(f"{BASE_URL}/valuation/TSM")
        page.wait_for_selector(".hero-card h1", timeout=30000)
        page.screenshot(path=str(EVIDENCE_DIR / "02_tsm_page.png"))

        export_btn_tsm = page.locator("button.export-button")
        assert export_btn_tsm.is_enabled()

        network_calls_tsm = []
        page.on("request", lambda r: network_calls_tsm.append(r.url))

        with page.expect_download() as dl_tsm_info:
            export_btn_tsm.click()

        dl_tsm = dl_tsm_info.value
        filename_tsm = dl_tsm.suggested_filename
        print(f"  TSM downloaded filename: {filename_tsm}")
        assert re.match(r"^TSM_valuation_\d{8}_\d{6}\.md$", filename_tsm)
        assert len(network_calls_tsm) == 0, f"Expected 0 requests, got: {network_calls_tsm}"

        path_tsm = EVIDENCE_DIR / filename_tsm
        dl_tsm.save_as(str(path_tsm))
        content_tsm = path_tsm.read_text(encoding="utf-8")

        assert "(TSM) 估值分析报告" in content_tsm
        assert "### 3.1 市盈率估值 (forward_pe)" in content_tsm
        assert "✅ 可用" in content_tsm
        assert "### 3.2 EV / EBITDA 估值 (ev_ebitda)" in content_tsm
        assert "❌ 不可用" in content_tsm
        assert "Currency mismatch: quote currency (USD) differs from statement reporting currency (TWD)" in content_tsm
        assert "Currency mismatch: quote currency is USD while financial statements are reported in TWD" in content_tsm
        assert "> **不可用原因**：Currency mismatch: quote currency (USD) differs from statement reporting currency (TWD)" in content_tsm
        print("  ✓ Test 6 passed: TSM ADR currency isolation reasons and warnings preserved!")

        # ---------------------------------------------------------------------
        # Test 7: Error State Safety (No Bogus Data Export Possible)
        # ---------------------------------------------------------------------
        print("\n[Test 7] Error State Safety: Export Button is NOT Present on Errored Pages")
        page.goto(f"{BASE_URL}/valuation/INVALIDXYZ999")
        page.wait_for_selector(".error-panel", timeout=30000)
        page.screenshot(path=str(EVIDENCE_DIR / "03_error_page.png"))

        export_count = page.locator("button.export-button").count()
        assert export_count == 0, f"Export button must not exist during error state, found {export_count}"
        print("  ✓ Test 7 passed: Export button correctly absent on error state!")

        browser.close()

    print("\n=== All 7 Comprehensive Playwright Browser Tests Passed Successfully! ===")

if __name__ == "__main__":
    run_tests()
