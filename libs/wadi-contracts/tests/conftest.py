"""Shared builders for contract tests."""

import pytest

from wadi_contracts.ids import method_id, service_id
from wadi_contracts.source import MethodRef, SourceAnchor


@pytest.fixture
def svc_id() -> str:
    return service_id("https://github.com/acme/shop.git", "services/orders")


@pytest.fixture
def handler_ref(svc_id: str) -> MethodRef:
    signature = "com.acme.orders.OrderController.getOrder(java.lang.String)"
    return MethodRef(id=method_id(svc_id, signature), signature=signature)


@pytest.fixture
def anchor() -> SourceAnchor:
    return SourceAnchor(
        file="src/main/java/com/acme/OrderController.java", start_line=42, end_line=42
    )
