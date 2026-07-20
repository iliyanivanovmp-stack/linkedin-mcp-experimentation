from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .models import FormField, FunnelCandidate, SubmissionDecision


CTA_PATTERN = re.compile(
    r"(free|download|report|audit|guide|newsletter|subscribe|contact|book|demo)",
    re.I,
)
SUCCESS_PATTERN = re.compile(
    r"thank\s+you|thanks\s+for|successfully\s+(?:submitted|sent|registered)|"
    r"submission\s+(?:received|confirmed)|check\s+your\s+(?:email|inbox)|"
    r"we(?:'|’)ll\s+be\s+in\s+touch|your\s+(?:request|message)\s+has\s+been\s+(?:sent|received)",
    re.I,
)
ERROR_PATTERN = re.compile(
    r"required\s+field|please\s+(?:complete|enter|provide|select)|invalid\s+email|"
    r"something\s+went\s+wrong|submission\s+failed|try\s+again|captcha",
    re.I,
)


def _fingerprint(fields: list[FormField], offer_text: str) -> str:
    signature = "|".join(
        f"{field.name.casefold()}:{field.label.casefold()}:{field.field_type}"
        for field in fields
    )
    return hashlib.sha256(f"{signature}|{offer_text[:500]}".encode()).hexdigest()[:16]


async def _fields(page: Page, scope_selector: str) -> list[FormField]:
    return [
        FormField.model_validate(field)
        for field in await page.locator(f"{scope_selector} input, {scope_selector} textarea, {scope_selector} select").evaluate_all(
            """
            els => els.map((el, i) => ({
              selector: el.id ? `#${CSS.escape(el.id)}` :
                el.name ? `[name="${CSS.escape(el.name)}"]` :
                `${el.tagName.toLowerCase()}:nth-of-type(${i + 1})`,
              name: el.name || "",
              label: el.labels?.[0]?.innerText || el.placeholder || el.getAttribute("aria-label") || "",
              field_type: el.type || el.tagName.toLowerCase(),
              required: !!el.required,
              options: el.tagName === "SELECT" ? [...el.options].map(o => o.text) : []
            }))
            """
        )
    ]


async def _scan(page: Page, screenshot_path: str) -> list[FunnelCandidate]:
    candidates: list[FunnelCandidate] = []
    forms = await page.locator("form").all()
    for index, form in enumerate(forms):
        if not await form.is_visible():
            continue
        text = (await form.inner_text())[:2000]
        fields = await _fields_for_locator(form)
        candidates.append(
            FunnelCandidate(
                page_url=page.url,
                entry_type="popup" if await form.locator("xpath=ancestor::*[@role='dialog']").count() else "form",
                offer_text=text,
                fields=fields,
                captcha_detected=bool(
                    await form.locator("iframe[src*='captcha'], [class*='captcha']").count()
                ),
                payment_detected=bool(re.search(r"card|checkout|payment|billing", text, re.I)),
                sensitive_detected=bool(
                    re.search(r"password|social security|medical|bank account", text, re.I)
                ),
                screenshot_path=screenshot_path,
                form_fingerprint=_fingerprint(fields, text),
            )
        )

    for iframe in await page.locator("iframe").all():
        if not await iframe.is_visible():
            continue
        src = await iframe.get_attribute("src") or ""
        if re.search(r"calendly|hubspot|typeform|tally|meeting", src, re.I):
            candidates.append(
                FunnelCandidate(
                    page_url=src or page.url,
                    entry_type="booking" if re.search(r"calendly|meeting", src, re.I) else "iframe",
                    offer_text=src,
                    screenshot_path=screenshot_path,
                )
            )
    return candidates


async def discover(url: str, evidence_dir: str, audit_id: str) -> list[FunnelCandidate]:
    target = Path(evidence_dir) / audit_id
    target.mkdir(parents=True, exist_ok=True)
    candidates: list[FunnelCandidate] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(35_000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.75)")
        await page.wait_for_timeout(2_000)
        screenshot = target / "discovery.png"
        await page.screenshot(path=str(screenshot), full_page=True)

        candidates.extend(await _scan(page, str(screenshot)))

        # Trigger common exit-intent implementations and rescan any newly
        # mounted dialog/form before following CTAs.
        await page.mouse.move(700, 800)
        await page.mouse.move(700, 0)
        await page.wait_for_timeout(3_000)
        exit_screenshot = target / "exit-intent.png"
        await page.screenshot(path=str(exit_screenshot), full_page=True)
        candidates.extend(await _scan(page, str(exit_screenshot)))

        ctas = page.locator("a, button").filter(has_text=CTA_PATTERN)
        for index in range(min(await ctas.count(), 4)):
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(2_000)
            current = page.locator("a, button").filter(has_text=CTA_PATTERN).nth(index)
            if not await current.is_visible():
                continue
            text = (await current.inner_text())[:500]
            href = await current.get_attribute("href")
            if href and re.search(r"calendly|meeting", href, re.I):
                candidates.append(
                    FunnelCandidate(
                        page_url=href,
                        entry_type="booking",
                        offer_text=text,
                        screenshot_path=str(screenshot),
                    )
                )
                continue
            try:
                await current.click(timeout=5_000)
                await page.wait_for_timeout(3_000)
                clicked_screenshot = target / f"cta-{index + 1}.png"
                await page.screenshot(path=str(clicked_screenshot), full_page=True)
                candidates.extend(await _scan(page, str(clicked_screenshot)))
                for candidate in candidates:
                    if candidate.screenshot_path == str(clicked_screenshot):
                        candidate.reveal_cta_text = text
                        candidate.reveal_cta_href = href or ""
            except Exception:
                continue

        if not candidates:
            ctas = page.get_by_role("link").filter(has_text=CTA_PATTERN)
            for index in range(min(await ctas.count(), 5)):
                href = await ctas.nth(index).get_attribute("href") or page.url
                entry_type = (
                    "booking"
                    if re.search(r"calendly|meeting|book", href, re.I)
                    else "unknown"
                )
                candidates.append(
                    FunnelCandidate(
                        page_url=href,
                        entry_type=entry_type,
                        offer_text=(await ctas.nth(index).inner_text())[:500],
                        screenshot_path=str(screenshot),
                    )
                )

        mobile = await browser.new_page(viewport={"width": 390, "height": 844})
        try:
            await mobile.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await mobile.wait_for_timeout(8_000)
            await mobile.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.75)")
            await mobile.wait_for_timeout(2_000)
            mobile_screenshot = target / "mobile.png"
            await mobile.screenshot(path=str(mobile_screenshot), full_page=True)
            candidates.extend(await _scan(mobile, str(mobile_screenshot)))
        finally:
            await mobile.close()
        await browser.close()
    unique: dict[tuple[str, str, str], FunnelCandidate] = {}
    for candidate in candidates:
        key = (candidate.page_url, candidate.entry_type, candidate.offer_text[:200])
        unique[key] = candidate
    return list(unique.values())


async def submit_candidate(
    candidate: FunnelCandidate,
    decision: SubmissionDecision,
    evidence_dir: str,
    audit_id: str,
) -> dict:
    if candidate.entry_type == "booking":
        return await submit_calendly(candidate, decision, evidence_dir, audit_id)
    if candidate.entry_type not in {"form", "popup"}:
        return {"submitted": False, "reason": "unsupported funnel adapter"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto(candidate.page_url, wait_until="domcontentloaded", timeout=45_000)
        if candidate.reveal_cta_text:
            reveal = page.locator("a, button").filter(
                has_text=re.compile(re.escape(candidate.reveal_cta_text[:120]), re.I)
            ).first
            if await reveal.count() and await reveal.is_visible():
                await reveal.click(timeout=5_000)
                await page.wait_for_timeout(2_000)

        form = None
        for visible_form in await page.locator("form").all():
            if not await visible_form.is_visible():
                continue
            text = (await visible_form.inner_text())[:2000]
            fields = await _fields_for_locator(visible_form)
            if _fingerprint(fields, text) == candidate.form_fingerprint:
                form = visible_form
                break
        if form is None:
            await browser.close()
            return {
                "submitted": False,
                "reason": "The exact form discovered earlier could not be reproduced.",
            }
        values = {item.field.casefold(): item.value for item in decision.field_values}
        for field in candidate.fields:
            value = values.get(field.name.casefold()) or values.get(field.label.casefold())
            if not value:
                continue
            locator = form.locator(field.selector)
            if field.field_type in {"checkbox", "radio"}:
                await locator.check()
            elif field.field_type == "select":
                await locator.select_option(label=value)
            else:
                await locator.fill(value)
        missing_required = []
        for field in candidate.fields:
            if not field.required:
                continue
            value = values.get(field.name.casefold()) or values.get(field.label.casefold())
            if not value and field.field_type not in {"hidden", "submit"}:
                missing_required.append(field.label or field.name or field.selector)
        if missing_required:
            await browser.close()
            return {
                "submitted": False,
                "reason": "Required fields have no truthful configured value: " + ", ".join(missing_required),
            }

        before_url = page.url
        before_text = (await page.locator("body").inner_text())[:12000]
        submit = form.locator("button[type=submit], input[type=submit]").first
        if not await submit.count():
            await browser.close()
            return {"submitted": False, "reason": "Submit control not found on the reproduced form."}
        await submit.click()
        await page.wait_for_timeout(5_000)
        screenshot = Path(evidence_dir) / audit_id / "submitted.png"
        await page.screenshot(path=str(screenshot), full_page=True)
        after_text = (await page.locator("body").inner_text())[:12000]
        url_success = page.url != before_url and bool(
            re.search(r"thank|confirm|success|complete|submitted", page.url, re.I)
        )
        text_changed = after_text != before_text
        text_success = bool(
            text_changed
            and SUCCESS_PATTERN.search(after_text)
            and not SUCCESS_PATTERN.search(before_text)
        )
        visible_error = bool(
            text_changed
            and ERROR_PATTERN.search(after_text)
            and not ERROR_PATTERN.search(before_text)
        )
        submitted = (url_success or text_success) and not visible_error
        result = {
            "submitted": submitted,
            "final_url": page.url,
            "confirmation_text": after_text[:5000],
            "screenshot_path": str(screenshot),
            "verification": {
                "url_changed_to_confirmation": url_success,
                "success_text_detected": text_success,
                "validation_or_error_detected": visible_error,
            },
        }
        if not submitted:
            result["reason"] = "Submission was clicked but no authoritative success state was observed."
        await browser.close()
        return result


async def _fields_for_locator(form) -> list[FormField]:
    return [
        FormField.model_validate(field)
        for field in await form.locator("input, textarea, select").evaluate_all(
            """
            els => els.map((el, i) => ({
              selector: el.id ? `#${CSS.escape(el.id)}` :
                el.name ? `[name="${CSS.escape(el.name)}"]` :
                `${el.tagName.toLowerCase()}:nth-of-type(${i + 1})`,
              name: el.name || "",
              label: el.labels?.[0]?.innerText || el.placeholder || el.getAttribute("aria-label") || "",
              field_type: el.type || el.tagName.toLowerCase(),
              required: !!el.required,
              options: el.tagName === "SELECT" ? [...el.options].map(o => o.text) : []
            }))
            """
        )
    ]


async def submit_calendly(
    candidate: FunnelCandidate,
    decision: SubmissionDecision,
    evidence_dir: str,
    audit_id: str,
) -> dict:
    if "calendly.com" not in candidate.page_url:
        return {"submitted": False, "reason": "unsupported booking provider"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto(candidate.page_url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(4_000)
        decline = page.get_by_role("button", name=re.compile("Decline all", re.I))
        if await decline.count():
            await decline.click()

        selected_day = False
        earliest = datetime.now(timezone.utc) + timedelta(hours=72)
        for _ in range(4):
            day_buttons = page.locator(
                "button[aria-label*='available']:not([aria-label*='No times'])"
            )
            for index in range(await day_buttons.count()):
                day = day_buttons.nth(index)
                aria = await day.get_attribute("aria-label") or ""
                date_text = aria.split(" - ", 1)[0]
                try:
                    candidate_date = datetime.strptime(
                        f"{date_text}, {earliest.year}", "%A, %B %d, %Y"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                # Use the following calendar day, not merely the same date,
                # so every selected slot is safely beyond the 72-hour floor.
                if candidate_date.date() <= earliest.date():
                    continue
                if await day.is_enabled() and await day.is_visible():
                    await day.click()
                    await page.wait_for_timeout(2_000)
                    selected_day = True
                    break
            if selected_day:
                break
            next_month = page.get_by_role("button", name="Go to next month")
            if not await next_month.is_enabled():
                break
            await next_month.click()
            await page.wait_for_timeout(1_000)
        if not selected_day:
            await browser.close()
            return {"submitted": False, "reason": "No Calendly slot available within four months."}

        time_button = None
        for _ in range(10):
            for button in await page.locator("button").all():
                if not await button.is_visible():
                    continue
                text = (await button.inner_text()).strip()
                if re.fullmatch(
                    r"\d{1,2}:\d{2}(?:\s?[ap]m)?",
                    text,
                    re.I,
                ):
                    time_button = button
                    break
            if time_button is not None:
                break
            await page.wait_for_timeout(1_000)
        if time_button is None:
            screenshot = Path(evidence_dir) / audit_id / "booking-no-times.png"
            await page.screenshot(path=str(screenshot), full_page=True)
            await browser.close()
            return {
                "submitted": False,
                "reason": "Calendly date had no selectable time.",
                "screenshot_path": str(screenshot),
            }
        selected_time = await time_button.inner_text()
        await time_button.click()
        next_button = None
        for button in await page.locator("button").all():
            if await button.is_visible() and (await button.inner_text()).strip().casefold() == "next":
                next_button = button
                break
        if next_button is not None:
            await next_button.click()
        await page.wait_for_timeout(2_000)

        decision_values = {
            item.field.casefold(): item.value for item in decision.field_values
        }
        values = {
            "name": decision_values.get("name", ""),
            "email": decision_values.get("email", ""),
            "phone": decision_values.get("phone", ""),
        }
        for label, value in values.items():
            if not value:
                continue
            locator = page.get_by_label(re.compile(label, re.I)).first
            if await locator.count():
                await locator.fill(value)
        for key, value in decision_values.items():
            if key.casefold() in values or not value:
                continue
            for locator in await page.locator("input, textarea").all():
                if not await locator.is_visible():
                    continue
                descriptor = " ".join(
                    filter(
                        None,
                        [
                            await locator.get_attribute("name"),
                            await locator.get_attribute("id"),
                            await locator.get_attribute("placeholder"),
                            await locator.get_attribute("aria-label"),
                        ],
                    )
                )
                element_id = await locator.get_attribute("id")
                if element_id:
                    label = page.locator(f"label[for='{element_id}']")
                    if await label.count():
                        descriptor += " " + (await label.first.inner_text())
                if key.casefold() in descriptor.casefold():
                    await locator.fill(value)
                    break

        schedule = page.get_by_role(
            "button", name=re.compile(r"Schedule|Book|Confirm", re.I)
        ).last
        if not await schedule.count():
            await browser.close()
            return {"submitted": False, "reason": "Calendly confirmation button not found."}
        await schedule.click()
        await page.wait_for_timeout(5_000)
        screenshot = Path(evidence_dir) / audit_id / "booking-confirmed.png"
        await page.screenshot(path=str(screenshot), full_page=True)
        confirmation_text = (await page.locator("body").inner_text())[:5000]
        rejected = bool(
            re.search(
                r"cannot be completed|not able to finalize|booking failed|"
                r"couldn't schedule|unable to schedule",
                confirmation_text,
                re.I,
            )
        )
        confirmed = bool(
            re.search(
                r"you are scheduled|confirmed|booking is scheduled|"
                r"meeting is scheduled",
                confirmation_text,
                re.I,
            )
        )
        result = {
            "submitted": confirmed and not rejected,
            "booking_created": confirmed and not rejected,
            "selected_time": selected_time,
            "final_url": page.url,
            "confirmation_text": confirmation_text,
            "screenshot_path": str(screenshot),
        }
        if rejected:
            result["reason"] = "Calendly rejected the automated cloud session."
        elif not confirmed:
            result["reason"] = "Calendly did not show an authoritative booking confirmation."
        await browser.close()
        return result


async def cancel_booking(cancellation_url: str, evidence_path: str) -> dict:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1200, "height": 900})
        await page.goto(cancellation_url, wait_until="domcontentloaded", timeout=45_000)
        cancel = page.get_by_role("button", name=re.compile("Cancel", re.I)).first
        if not await cancel.count():
            cancel = page.get_by_role("link", name=re.compile("Cancel", re.I)).first
        if not await cancel.count():
            await browser.close()
            return {"cancelled": False, "reason": "Cancellation control not found."}
        await cancel.click()
        await page.wait_for_timeout(1_000)
        confirm = page.get_by_role(
            "button", name=re.compile("Cancel event|Confirm cancellation|Yes", re.I)
        ).first
        if await confirm.count():
            await confirm.click()
        await page.wait_for_timeout(3_000)
        await page.screenshot(path=evidence_path, full_page=True)
        result = {
            "cancelled": bool(
                re.search(
                    r"cancelled|canceled",
                    (await page.locator("body").inner_text())[:5000],
                    re.I,
                )
            ),
            "final_url": page.url,
        }
        await browser.close()
        return result
