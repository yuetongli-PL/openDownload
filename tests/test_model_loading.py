"""Actor cold-cache requests must return without waiting for the crawler."""
from unittest.mock import patch

from server import jable_lists, jable_page


def test_model_list_uses_nonblocking_page_reader():
    result = {"items": [], "pending": True}
    with patch.object(jable_lists, "_ensure_model_title"), patch.object(jable_lists, "_ensure_model_pages"), patch.object(jable_page, "page_feed", return_value=result) as reader, patch.object(jable_lists, "_fetch_site_page", side_effect=AssertionError("blocking fetch")):
        assert jable_lists.list_feed(kind="model", slug="sample-actor", page=2) is result
        assert reader.call_args.kwargs["page"] == 2


def test_model_first_page_is_interactive_priority():
    import jable_http
    import jable_user

    spec = jable_lists._resolve_list("model", "sample-actor", "")
    with patch.object(jable_http, "fetch_html", return_value=("", "")) as fetch, patch.object(jable_user, "looks_like_model_page", return_value=False):
        assert jable_lists._fetch_site_page(spec, 1) == []
        assert fetch.call_args.kwargs["priority"] is True
        assert fetch.call_args.kwargs["timeout"] == 12


def test_cold_model_page_is_pending_and_does_not_fan_out():
    from server import jable_index

    with patch.object(jable_lists, "_ensure_model_title"), patch.object(jable_lists, "_ensure_model_pages"), patch.object(jable_lists, "_declared_total", return_value=0), patch.object(jable_index, "seed_order"), patch.object(jable_page, "_load_works"), patch.object(jable_page, "order_len", return_value=0), patch.object(jable_page, "order_total_hint", return_value=0), patch.object(jable_page, "display_len", return_value=0), patch.object(jable_page, "items_for_ui_page", return_value=[]), patch.object(jable_page, "_disk_ui_items", return_value=[]), patch.object(jable_page, "prefetch_around", side_effect=AssertionError("duplicate crawler")):
        data = jable_page.page_feed(kind="model", slug="sample-actor")
        assert data["pending"] is True
        assert data["cached"] is False
        assert data["items"] == []
