# -*- coding: utf-8 -*-
import json
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

from ui_support import BASE, shot


def api(method: str, path: str, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


def wait_task(task_id: str, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        data = api("GET", "/api/tasks?limit=50")
        for row in data.get("items") or []:
            if row.get("id") == task_id:
                last = row
                if row.get("status") in {"error", "done", "cancelled"}:
                    return row
        time.sleep(0.4)
    return last


def main() -> None:
    before = api("GET", "/api/tasks?limit=50")
    existing = len(before.get("items") or [])
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE + "/#/tasks", wait_until="domcontentloaded")
        page.locator(".view-tasks").wait_for(state="visible", timeout=10000)
        if existing == 0:
            title = page.locator(".view-tasks .empty h3").inner_text().strip()
            assert title == "还没有任务", title
            assert "解析并确认保存" in page.locator(".view-tasks .empty p").inner_text()
            shot(page, "_ui_tasks_empty.png")
        else:
            print("skip empty state; existing tasks", existing)
            shot(page, "_ui_tasks_existing.png")

        created = api("POST", "/api/parse", {"query": "zzz-not-a-link", "site": "auto"})
        task_id = created.get("id")
        assert task_id, created
        rec = wait_task(task_id)
        print("created", task_id, rec.get("status"), rec.get("error"))
        assert rec.get("status") == "error", rec

        page.reload(wait_until="domcontentloaded")
        page.locator(".view-tasks").wait_for(state="visible", timeout=10000)
        row = page.locator(f'.task-row[data-task="{task_id}"]')
        row.wait_for(timeout=10000)
        text = row.inner_text()
        assert "失败" in text or (rec.get("error") or "")[:8] in text
        shot(page, "_ui_tasks_error.png")
        row.locator('[data-act="dismiss"]').click()
        page.wait_for_function(
            f"() => !document.querySelector('.task-row[data-task=\"{task_id}\"]')",
            timeout=8000,
        )
        browser.close()

    after = api("GET", "/api/tasks?limit=80")
    ids = [row.get("id") for row in (after.get("items") or [])]
    assert task_id not in ids, ids
    print("ui tasks ok", task_id)


if __name__ == "__main__":
    main()
