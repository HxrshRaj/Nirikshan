"""Organisation -> Environment -> Service -> Instance topology + dependency edges."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nirikshan.domain.enums import ServiceHealth
from nirikshan.models.base import Base, Timestamps, UTCDateTime, UUIDPk


class Organization(UUIDPk, Timestamps, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    environments: Mapped[list[Environment]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Environment(UUIDPk, Timestamps, Base):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_env_org_name"),)

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)  # production, staging...
    kind: Mapped[str] = mapped_column(String(40), default="production")

    organization: Mapped[Organization] = relationship(back_populates="environments")
    services: Mapped[list[Service]] = relationship(
        back_populates="environment", cascade="all, delete-orphan"
    )


class Service(UUIDPk, Timestamps, Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("environment_id", "name", name="uq_service_env_name"),)

    environment_id: Mapped[str] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(40), default="service")  # service|datastore|cache|queue
    tier: Mapped[int] = mapped_column(default=2)  # 1 = user-facing critical
    owner_team: Mapped[str] = mapped_column(String(120), default="")
    runbook_url: Mapped[str] = mapped_column(String(400), default="")
    health: Mapped[str] = mapped_column(String(16), default=ServiceHealth.UNKNOWN.value)
    health_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    slo_latency_ms_p95: Mapped[float] = mapped_column(Float, default=300.0)
    slo_error_rate: Mapped[float] = mapped_column(Float, default=0.02)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)

    environment: Mapped[Environment] = relationship(back_populates="services")
    instances: Mapped[list[ServiceInstance]] = relationship(
        back_populates="service", cascade="all, delete-orphan"
    )
    dependencies_out: Mapped[list[ServiceDependency]] = relationship(
        back_populates="upstream",
        foreign_keys="ServiceDependency.upstream_id",
        cascade="all, delete-orphan",
    )
    dependencies_in: Mapped[list[ServiceDependency]] = relationship(
        back_populates="downstream",
        foreign_keys="ServiceDependency.downstream_id",
        cascade="all, delete-orphan",
    )


class ServiceInstance(UUIDPk, Timestamps, Base):
    __tablename__ = "service_instances"
    __table_args__ = (UniqueConstraint("service_id", "host", name="uq_instance_service_host"),)

    service_id: Mapped[str] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True
    )
    host: Mapped[str] = mapped_column(String(200), nullable=False)
    zone: Mapped[str] = mapped_column(String(60), default="")
    version: Mapped[str] = mapped_column(String(60), default="")
    healthy: Mapped[bool] = mapped_column(default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    service: Mapped[Service] = relationship(back_populates="instances")


class ServiceDependency(UUIDPk, Timestamps, Base):
    """Directed edge: ``upstream`` depends on / calls ``downstream``."""

    __tablename__ = "service_dependencies"
    __table_args__ = (
        UniqueConstraint("upstream_id", "downstream_id", name="uq_dep_pair"),
    )

    upstream_id: Mapped[str] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True
    )
    downstream_id: Mapped[str] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="sync")  # sync|async|datastore
    critical: Mapped[bool] = mapped_column(default=True)

    upstream: Mapped[Service] = relationship(
        back_populates="dependencies_out", foreign_keys=[upstream_id]
    )
    downstream: Mapped[Service] = relationship(
        back_populates="dependencies_in", foreign_keys=[downstream_id]
    )
