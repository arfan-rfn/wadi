"""Identity-stability tests (§7 day-zero rule) — the highest-stakes contract."""

import pytest

from wadi_contracts.ids import (
    data_model_id,
    endpoint_id,
    method_id,
    mq_interaction_id,
    normalize_repo_source,
    remote_call_id,
    service_id,
    simplify_uri,
)


class TestSimplifyUri:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("/orders", "/orders"),
            ("orders", "/orders"),
            ("/orders/", "/orders"),
            ("//orders//items/", "/orders/items"),
            ("/", "/"),
            ("", "/"),
            ("/orders/{id}", "/orders/{?}"),
            ("/orders/{orderId}", "/orders/{?}"),
            ("/orders/{orderId:[0-9]+}", "/orders/{?}"),
            ("/orders/{id}/items/{itemId}", "/orders/{?}/items/{?}"),
            ("/orders/:id", "/orders/{?}"),
            ("/orders?page=1", "/orders"),
            ("/orders#section", "/orders"),
            ("http://svc-b:8080/orders/{id}", "/orders/{?}"),
            ("https://svc-b/orders?x=1", "/orders"),
            ("/Orders/Items", "/Orders/Items"),  # literal case preserved
            ("/{}", "/{?}"),  # anonymous template segment
            ("/a-b_c.d/e", "/a-b_c.d/e"),
        ],
    )
    def test_normalization(self, raw: str, expected: str) -> None:
        assert simplify_uri(raw) == expected

    def test_equivalent_forms_share_identity(self) -> None:
        forms = ["/orders/{id}", "/orders/{orderId}", "orders/{oid}/", "/orders/{x:[0-9]+}"]
        assert len({simplify_uri(f) for f in forms}) == 1

    def test_mid_segment_braces_are_not_templates(self) -> None:
        # A segment that merely contains braces mid-text is not a path variable.
        assert simplify_uri("/weird{x}name") == "/weird{x}name"

    def test_idempotent(self) -> None:
        once = simplify_uri("/orders/{id}/items")
        assert simplify_uri(once) == once


class TestNormalizeRepoSource:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://github.com/acme/shop.git", "github.com/acme/shop"),
            ("https://github.com/acme/shop", "github.com/acme/shop"),
            ("https://GitHub.com/acme/shop/", "github.com/acme/shop"),
            ("git@github.com:acme/shop.git", "github.com/acme/shop"),
            ("ssh://git@github.com/acme/shop.git", "github.com/acme/shop"),
            ("http://gitlab.internal:8443/team/repo.git", "gitlab.internal/team/repo"),
            ("/Users/dev/projects/shop", "/Users/dev/projects/shop"),
            ("/Users/dev/projects/shop/", "/Users/dev/projects/shop"),
            (".", "."),
        ],
    )
    def test_normalization(self, raw: str, expected: str) -> None:
        assert normalize_repo_source(raw) == expected

    def test_case_preserved_in_repo_path(self) -> None:
        # Repo *paths* can be case-sensitive on the host; only the host is lowercased.
        assert normalize_repo_source("https://github.com/Acme/Shop") == "github.com/Acme/Shop"

    def test_all_url_forms_of_same_repo_share_identity(self) -> None:
        forms = [
            "https://github.com/acme/shop.git",
            "git@github.com:acme/shop.git",
            "ssh://git@github.com/acme/shop",
            "https://github.com/acme/shop",
        ]
        assert len({normalize_repo_source(f) for f in forms}) == 1


class TestDeterministicIds:
    def test_service_id_stable(self) -> None:
        a = service_id("https://github.com/acme/shop.git", "services/orders")
        b = service_id("git@github.com:acme/shop.git", "services/orders/")
        assert a == b
        assert a.startswith("svc_")
        assert len(a) == 4 + 16

    def test_service_id_differs_by_build_root(self) -> None:
        repo = "https://github.com/acme/shop.git"
        assert service_id(repo, "services/orders") != service_id(repo, "services/billing")

    def test_endpoint_id_stable_across_param_renames(self) -> None:
        svc = service_id("https://github.com/acme/shop.git", ".")
        a = endpoint_id(svc, "GET", "/orders/{orderId}")
        b = endpoint_id(svc, "get", "/orders/{id}/")
        assert a == b
        assert a.startswith("ep_")

    def test_endpoint_id_differs_by_method(self) -> None:
        svc = service_id("repo", ".")
        assert endpoint_id(svc, "GET", "/orders") != endpoint_id(svc, "POST", "/orders")

    def test_endpoint_id_differs_by_service(self) -> None:
        svc_a = service_id("repo", "a")
        svc_b = service_id("repo", "b")
        assert endpoint_id(svc_a, "GET", "/orders") != endpoint_id(svc_b, "GET", "/orders")

    def test_kind_domain_separation(self) -> None:
        # Same inputs through different id kinds must never produce the same digest.
        svc = service_id("repo", ".")
        ids = {
            method_id(svc, "x"),
            data_model_id(svc, "x"),
        }
        assert len(ids) == 2
        digests = {i.split("_", 1)[1] for i in ids}
        assert len(digests) == 2

    def test_remote_call_id_per_candidate(self) -> None:
        svc = service_id("repo", ".")
        a = remote_call_id(svc, "src/A.java", 42, "http://svc-b/orders")
        b = remote_call_id(svc, "src/A.java", 42, "http://svc-c/orders")
        assert a != b
        assert a.startswith("rc_")

    def test_mq_interaction_id_direction_matters(self) -> None:
        svc = service_id("repo", ".")
        pub = mq_interaction_id(svc, "src/A.java", 10, "publish", "orders")
        con = mq_interaction_id(svc, "src/A.java", 10, "consume", "orders")
        assert pub != con

    def test_no_delimiter_injection(self) -> None:
        # Concatenation ambiguity must not create colliding ids.
        svc = service_id("repo", ".")
        assert method_id(svc, "ab") != method_id(svc, "a\x1fb")
        assert endpoint_id(svc, "GET", "/ab") != endpoint_id(svc, "GETA", "/b")
