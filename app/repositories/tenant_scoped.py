from __future__ import annotations

from app.models import BotConfig, ConnectionState, Subscription, UsageCounter

from .base import TenantScopedRepository


class BotConfigRepository(TenantScopedRepository):
    def get(self) -> BotConfig | None:
        return self.scoped_query(BotConfig).one_or_none()

    def update(
        self,
        *,
        business_name: str | None = None,
        ai_persona_prompt: str | None = None,
    ) -> BotConfig | None:
        config = self.get()
        if config is None:
            return None
        if business_name is not None:
            config.business_name = business_name
        if ai_persona_prompt is not None:
            config.ai_persona_prompt = ai_persona_prompt
        return config


class SubscriptionRepository(TenantScopedRepository):
    def get(self) -> Subscription | None:
        return self.scoped_query(Subscription).order_by(Subscription.updated_at.desc()).first()

    def delete(self) -> int:
        return self.scoped_query(Subscription).delete(synchronize_session=False)


class UsageCounterRepository(TenantScopedRepository):
    def get(self) -> UsageCounter | None:
        return self.scoped_query(UsageCounter).one_or_none()

    def update_block_state(self, *, is_blocked: bool) -> UsageCounter | None:
        usage = self.get()
        if usage is None:
            return None
        usage.is_blocked = bool(is_blocked)
        return usage


class ConnectionStateRepository(TenantScopedRepository):
    def get(self) -> ConnectionState | None:
        return self.scoped_query(ConnectionState).one_or_none()

    def update_connection(
        self,
        *,
        status: str | None = None,
        evolution_instance: str | None = None,
    ) -> ConnectionState | None:
        connection = self.get()
        if connection is None:
            return None
        if status is not None:
            connection.status = status
        if evolution_instance is not None:
            connection.evolution_instance = evolution_instance
        return connection