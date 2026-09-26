"""End-to-end browser test for dist/index.html (Playwright, Chromium).

    python tests/e2e_test.py            # headless
    HEADED=1 python tests/e2e_test.py   # watch it run

Signs in, checks the limit panel and the demo ceiling, completes a HIGH-risk
payment through OK -> demo verification -> demo PIN, checks that a watchlisted
recipient is blocked, checks the phone layout, and fails on any page error.
The clock is fixed at 14:00 India time so the risk scores are reproducible.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "index.html"
SRC = ROOT / "src" / "index.html"
IST = timezone(timedelta(hours=5, minutes=30))
FIXED_NOW = datetime(2026, 9, 26, 14, 0, 0, tzinfo=IST)


def launch(p):
    headless = not os.environ.get("HEADED")
    try:
        return p.chromium.launch(headless=headless)
    except Exception:
        # Pre-installed Chromium (for example in CI containers) when the bundled one is absent
        for exe in ("/opt/pw-browsers/chromium", os.environ.get("CHROMIUM_PATH", "")):
            if exe and os.path.exists(exe):
                return p.chromium.launch(headless=headless, executable_path=exe)
        raise


def step(msg):
    print(f"  - {msg}", flush=True)


def new_page(browser, errors, **ctx):
    context = browser.new_context(timezone_id="Asia/Kolkata", locale="en-IN", **ctx)
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.clock.set_fixed_time(FIXED_NOW)
    return context, page


def sign_in(page, email="yogesh@demo.yogii", password="Password123!"):
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible(timeout=15000)
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name=re.compile(r"^Hello"))).to_be_visible(timeout=15000)


def start_payment(page, to):
    page.locator(".topnav").get_by_role("link", name="Send").click()
    page.get_by_label("UPI ID or mobile number").fill(to)
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="This is the right person").click()
    expect(page.get_by_role("heading", name="Enter amount")).to_be_visible()


def main():
    if not DIST.exists():
        print("FAIL dist/index.html is missing. Run: python scripts/build.py")
        return 1
    errors: list[str] = []
    with sync_playwright() as p:
        browser = launch(p)
        context, page = new_page(browser, errors, viewport={"width": 1280, "height": 900})
        page.goto(DIST.as_uri())

        step("simulation notice and sign-in")
        expect(page.locator(".sim-banner")).to_contain_text("Simulation")
        page.get_by_label("Email").fill("yogesh@demo.yogii")
        page.get_by_label("Password").fill("wrong-password")
        page.get_by_role("button", name="Sign in").click()
        expect(page.locator("#signin-error")).to_have_text("Email or password is incorrect.")
        sign_in(page)
        expect(page.locator(".stamp")).to_have_text("SIMULATED")
        expect(page.locator(".balance")).to_contain_text("3,00,000")

        step("limit panel shows and an amount over the ceiling is refused")
        start_payment(page, "techgadgets@merchant")
        limits = page.get_by_test_id("limits")
        expect(limits).to_be_visible()
        for label in ("No extra checks", "With demo verification", "With a strong warning"):
            expect(limits).to_contain_text(label)
        before = limits.inner_text()
        page.get_by_label("Pretend it’s 2 AM").check()
        expect(page.get_by_test_id("limits")).not_to_have_text(before)
        page.get_by_label("Pretend it’s 2 AM").uncheck()
        page.get_by_label("Amount (₹)").fill("150000")
        page.get_by_role("button", name="Check risk").click()
        expect(page.locator("#amt-err")).to_contain_text("demo ceiling")
        expect(page.get_by_role("heading", name="Enter amount")).to_be_visible()

        step("HIGH payment: OK -> demo verification -> demo PIN -> completed")
        page.get_by_label("Amount (₹)").fill("24500")
        page.get_by_role("button", name="Check risk").click()
        expect(page.get_by_role("heading", name="Risk check")).to_be_visible()
        expect(page.get_by_test_id("risk-score")).to_contain_text("High")
        expect(page.get_by_role("heading", name="Before you enter your PIN")).to_be_visible()
        expect(page.locator(".reasons")).to_contain_text("much higher than what you usually send")
        page.get_by_role("button", name="OK", exact=True).click()
        expect(page.get_by_role("heading", name="Demo verification")).to_be_visible()
        for box in page.locator("form[data-form=verify] input[type=checkbox]").all():
            box.check()
        page.get_by_label("Type the recipient’s UPI ID to confirm").fill("techgadgets@merchant")
        page.get_by_role("button", name="Verify").click()
        expect(page.get_by_role("heading", name="Enter demo PIN")).to_be_visible()
        expect(page.locator(".notice")).to_contain_text("This is not a UPI PIN")
        page.get_by_label("Demo PIN").fill("1234")
        page.get_by_role("button", name=re.compile(r"^Pay ")).click()
        expect(page.get_by_role("heading", name="Payment completed")).to_be_visible(timeout=10000)
        page.locator(".topnav").get_by_role("link", name="Home").click()
        expect(page.locator(".balance")).to_contain_text("2,75,500")

        step("watchlisted recipient: limit 0 and blocked")
        start_payment(page, "crypto_drain@unknown")
        expect(page.get_by_test_id("limits")).to_contain_text("Every amount to this recipient is blocked")
        page.get_by_label("Amount (₹)").fill("1000")
        page.get_by_role("button", name="Check risk").click()
        expect(page.locator("#amt-err")).to_contain_text("will block it")
        page.get_by_role("button", name="Check risk").click()
        expect(page.get_by_test_id("risk-score")).to_contain_text("Very high")
        expect(page.get_by_role("button", name="OK", exact=True)).to_be_disabled()
        expect(page.locator(".decision")).to_contain_text("blocked")
        page.get_by_role("button", name="Close").click()
        expect(page.get_by_role("heading", name="Payment blocked")).to_be_visible()
        page.locator(".topnav").get_by_role("link", name="Home").click()
        expect(page.locator(".balance")).to_contain_text("2,75,500")

        step("history filters and payment detail")
        page.locator(".topnav").get_by_role("link", name="History").click()
        page.get_by_label("Risk band").select_option("VERY_HIGH")
        expect(page.locator(".rows li")).to_have_count(1)
        page.locator(".rows li a").first.click()
        expect(page.get_by_role("heading", name="Timeline")).to_be_visible()
        page.get_by_text("Technical details").click()
        expect(page.locator(".tech")).to_contain_text("receiver")

        step("reset dialog is accessible and can be cancelled")
        page.locator(".topnav").get_by_role("link", name="Settings").click()
        page.get_by_role("button", name="Reset demo data").click()
        dialog = page.get_by_role("dialog", name="Reset demo data?")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        context.close()

        step("phone layout: bottom navigation, no horizontal scroll")
        context, page = new_page(browser, errors, viewport={"width": 375, "height": 740}, is_mobile=True, has_touch=True)
        page.goto(DIST.as_uri())
        sign_in(page)
        expect(page.locator(".bottomnav")).to_be_visible()
        expect(page.locator(".topnav")).to_be_hidden()
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, f"horizontal overflow of {overflow}px on phone width"
        context.close()

        step("missing model fails clearly (src page opened from file://, model cannot load)")
        model_errors: list[str] = []
        context, page = new_page(browser, model_errors)
        page.goto(SRC.as_uri())
        expect(page.get_by_role("heading", name="Risk model unavailable")).to_be_visible(timeout=10000)
        context.close()
        browser.close()

    real_errors = [e for e in errors if "favicon" not in e]
    if real_errors:
        print("FAIL page errors:\n  " + "\n  ".join(real_errors))
        return 1
    print("E2E OK: sign-in, limits, ceiling, verified payment, watchlist block, history, dialog, phone layout; no page errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
