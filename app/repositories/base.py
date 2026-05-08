from __future__ import annotations

from typing import Any


class TenantGuard:
    """Guard and base helper for tenant-scoped SaaS data access.

    Every tenant-scoped query must provide ``tenant_id``. Unscoped access
    raises a clear ``ValueError`` instead of executing a cross-tenant query.

    Usage::

        class SubscriptionRepository(TenantGuard):
            def get_active(self):
                return self.scoped_query(Subscription).first()
    """

    def __init__(self, session: Any, tenant_id: str | None) -> None:
        if not tenant_id or not str(tenant_id).strip():
            raise ValueError(
                "tenant_id is required for all repository operations. "
                "Unscoped database access is not permitted."
            )
        self._session = session
        self._tenant_id = str(tenant_id).strip()

    def require_tenant(self) -> str:
        """Explicit guard that raises if somehow tenant_id is missing or blank.

        Subclasses should call this at the top of every data-access method as
        defence-in-depth, even though the constructor already validates.
        """
        if not self._tenant_id:
            raise ValueError(
                "tenant_id must be set before performing a repository operation."
            )
        return self._tenant_id

    def scoped_query(self, model: Any):
        """Return a tenant-scoped query for models that define tenant_id."""
        tenant_id = self.require_tenant()
        if not hasattr(model, "tenant_id"):
            raise ValueError(
                f"Model '{getattr(model, '__name__', str(model))}' is not tenant-scoped; "
                "tenant_id guard cannot be applied."
            )
        return self._session.query(model).filter(model.tenant_id == tenant_id)


class TenantScopedRepository(TenantGuard):
    """Backwards-compatible alias for the previous repository base name."""
