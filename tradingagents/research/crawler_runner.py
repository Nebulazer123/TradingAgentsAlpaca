"""Read-only Crawlee + Playwright packet runner for research targets."""

from __future__ import annotations

import asyncio
import datetime
import importlib.util
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tradingagents.research.crawler_policy import (
    DEFAULT_CRAWLER,
    CrawlerPolicy,
    crawler_run_packet,
    evaluate_crawler_target,
)
from tradingagents.schemas.research import CrawlerRunPacket

UTC = datetime.timezone.utc
CRAWLEE_DOCS_URL = "https://crawlee.dev/python/docs/quick-start"
CRAWLER_INSTALL_COMMANDS = {
    "python_dependencies": r"uv pip install --python .\.venv\Scripts\python.exe -r requirements-crawler.txt",
    "browser_binaries": r".\.venv\Scripts\python.exe -m playwright install chromium",
}


@dataclass(frozen=True)
class CrawlerRuntimeStatus:
    crawlee_available: bool
    playwright_available: bool
    greenlet_available: bool = True

    @property
    def ready(self) -> bool:
        return self.crawlee_available and self.playwright_available and self.greenlet_available

    def as_dict(self) -> dict[str, object]:
        missing = []
        if not self.crawlee_available:
            missing.append("crawlee")
        if not self.playwright_available:
            missing.append("playwright")
        if not self.greenlet_available:
            missing.append("greenlet")
        if not missing:
            operator_summary = "Crawlee and Playwright are importable. The crawler lane can try read-only packet runs."
            self_heal_actions = []
        else:
            operator_summary = (
                "Codex cannot run the Crawlee browser crawler yet because "
                f"{', '.join(missing)} is missing. The bot will write a blocked analysis-only packet "
                "and Codex can try the install commands instead of asking you to edit code."
            )
            self_heal_actions = [
                "install_crawlee_playwright_python_extra",
                "install_playwright_chromium_browser",
                "repair_greenlet_dependency",
                "rerun_crawler_runtime_doctor",
                "fall_back_to_fetch_google_news_reddit_or_other_read_only_routes",
            ]
        return {
            "crawlee_available": self.crawlee_available,
            "playwright_available": self.playwright_available,
            "greenlet_available": self.greenlet_available,
            "ready": self.ready,
            "docs": CRAWLEE_DOCS_URL,
            "install_commands": dict(CRAWLER_INSTALL_COMMANDS),
            "self_heal_actions": self_heal_actions,
            "operator_summary": operator_summary,
        }


@dataclass(frozen=True)
class CrawlEvidence:
    fetched_urls: list[str] = field(default_factory=list)
    page_titles: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, object] = field(default_factory=dict)


CrawlerCallable = Callable[[str, CrawlerPolicy], CrawlEvidence]


def crawler_runtime_status() -> CrawlerRuntimeStatus:
    greenlet_available = False
    try:
        import greenlet

        greenlet_available = hasattr(greenlet, "greenlet")
    except Exception:  # noqa: BLE001 - import integrity is what the doctor reports.
        greenlet_available = False
    return CrawlerRuntimeStatus(
        crawlee_available=importlib.util.find_spec("crawlee") is not None,
        playwright_available=importlib.util.find_spec("playwright") is not None,
        greenlet_available=greenlet_available,
    )


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _packet(
    *,
    run_id: str,
    target: str,
    policy: CrawlerPolicy,
    status: str,
    fetched_urls: list[str] | None = None,
    blocked_urls: list[str] | None = None,
    freshness: dict[str, object] | None = None,
) -> CrawlerRunPacket:
    base = crawler_run_packet(
        run_id=run_id,
        target=target,
        policy=policy,
        fetched_urls=fetched_urls,
        crawler=DEFAULT_CRAWLER,
    )
    payload = base.model_dump()
    payload["status"] = status
    if blocked_urls is not None:
        payload["blocked_urls"] = list(blocked_urls)
    payload["freshness"] = {
        **base.freshness,
        **(freshness or {}),
        "generated_at": _now_iso(),
    }
    return CrawlerRunPacket.model_validate(payload)


async def _crawl_with_python_crawlee(target: str, policy: CrawlerPolicy) -> CrawlEvidence:
    from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext

    logging.getLogger("crawlee").setLevel(logging.WARNING)
    fetched_urls: list[str] = []
    titles: dict[str, str] = {}
    crawler = PlaywrightCrawler(max_requests_per_crawl=policy.max_pages)

    @crawler.router.default_handler
    async def request_handler(context: PlaywrightCrawlingContext) -> None:
        url = str(context.request.url)
        fetched_urls.append(url)
        titles[url] = await context.page.title()

    await crawler.run([target])
    return CrawlEvidence(
        fetched_urls=fetched_urls[: policy.max_pages],
        page_titles=titles,
        metrics={"page_count": len(fetched_urls)},
    )


def run_crawlee_research_packet(
    *,
    run_id: str,
    target: str,
    policy: CrawlerPolicy,
    crawler: CrawlerCallable | None = None,
    runtime_status: CrawlerRuntimeStatus | None = None,
    storage_dir: str | Path = "results/crawler_storage",
) -> CrawlerRunPacket:
    decision = evaluate_crawler_target(target, policy)
    if not decision.allowed:
        return _packet(
            run_id=run_id,
            target=target,
            policy=policy,
            status="blocked",
            blocked_urls=[target],
            freshness={
                "blocked_reason": decision.reason,
                "read_only": True,
            },
        )

    status = runtime_status or crawler_runtime_status()
    if crawler is None and not status.ready:
        return _packet(
            run_id=run_id,
            target=target,
            policy=policy,
            status="blocked",
            blocked_urls=[target],
            freshness={
                "blocked_reason": "Crawlee + Playwright runtime is not installed",
                "runtime": status.as_dict(),
                "read_only": True,
            },
        )

    try:
        if crawler is None:
            storage_root = Path(storage_dir).resolve()
            safe_run_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in run_id)
            run_storage_dir = storage_root / safe_run_id
            previous_storage_dir = os.environ.get("CRAWLEE_STORAGE_DIR")
            os.environ["CRAWLEE_STORAGE_DIR"] = str(run_storage_dir)
            try:
                evidence = asyncio.run(_crawl_with_python_crawlee(target, policy))
            finally:
                if previous_storage_dir is None:
                    os.environ.pop("CRAWLEE_STORAGE_DIR", None)
                else:
                    os.environ["CRAWLEE_STORAGE_DIR"] = previous_storage_dir
        else:
            evidence = crawler(target, policy)
    except Exception as exc:  # noqa: BLE001 - failure belongs in the evidence packet.
        return _packet(
            run_id=run_id,
            target=target,
            policy=policy,
            status="failed",
            blocked_urls=[],
            freshness={
                "error_summary": str(exc)[:500],
                "runtime": status.as_dict(),
                "read_only": True,
            },
        )

    return _packet(
        run_id=run_id,
        target=target,
        policy=policy,
        status="success" if evidence.fetched_urls else "failed",
        fetched_urls=evidence.fetched_urls,
        freshness={
            "runtime": status.as_dict(),
            "page_titles": evidence.page_titles,
            "metrics": evidence.metrics,
            "read_only": True,
        },
    )
