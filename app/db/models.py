"""
@Project: Trimr
@File: app/db/models.py
@Description: Database models and initialization
"""
import uuid
import json
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Integer,
    Float, Boolean, DateTime, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger()

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


class RequestLog(Base):
    __tablename__ = "requests"

    id                    = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp             = Column(DateTime, default=datetime.utcnow, index=True)
    model                 = Column(String(100), nullable=False)
    provider              = Column(String(50), nullable=False)
    strategy_type = Column(String(20), default="balance")  # economy/balance/quality/custom
    is_streaming          = Column(Boolean, default=False)
    input_tokens_original = Column(Integer, default=0)
    input_tokens_actual   = Column(Integer, default=0)
    output_tokens         = Column(Integer, default=0)
    saved_tokens          = Column(Integer, default=0)
    cost_actual           = Column(Float, default=0.0)
    cost_original         = Column(Float, default=0.0)
    cost_saved            = Column(Float, default=0.0)
    latency_ms            = Column(Integer, default=0)
    strategies_used       = Column(String(200), default="none")
    cache_hit             = Column(Boolean, default=False)
    compression_triggered = Column(Boolean, default=False)
    error                 = Column(Text, nullable=True)
    agent_slug = Column(String(50), default="openclaw")

    def to_dict(self):
        return {
            "id":                    self.id,
            "timestamp":             self.timestamp.isoformat() if self.timestamp else None,
            "model":                 self.model,
            "provider":              self.provider,
            "is_streaming":          self.is_streaming,
            "input_tokens_original": self.input_tokens_original,
            "input_tokens_actual":   self.input_tokens_actual,
            "output_tokens":         self.output_tokens,
            "saved_tokens":          self.saved_tokens,
            "cost_actual":           round(self.cost_actual, 6),
            "cost_original":         round(self.cost_original, 6),
            "cost_saved":            round(self.cost_saved, 6),
            "latency_ms":            self.latency_ms,
            "strategies_used":       self.strategies_used,
            "cache_hit":             self.cache_hit,
            "compression_triggered": self.compression_triggered,
            "error":                 self.error,
            "agent_slug": self.agent_slug,
        }


class StrategyConfig(Base):
    __tablename__ = "strategy_configs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(50), unique=True, nullable=False)
    enabled     = Column(Boolean, default=True)
    config_json = Column(Text, default="{}")
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "name":       self.name,
            "enabled":    self.enabled,
            "config":     json.loads(self.config_json or "{}"),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ActionLog(Base):
    __tablename__ = "action_logs"

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id  = Column(String(36), nullable=True, index=True)
    timestamp   = Column(DateTime, default=datetime.utcnow, index=True)
    action_type = Column(String(50), nullable=False)
    summary     = Column(Text, nullable=True)
    synced      = Column(Boolean, default=False, index=True)

    def to_dict(self):
        return {
            "id":          self.id,
            "request_id":  self.request_id,
            "timestamp":   self.timestamp.isoformat() if self.timestamp else None,
            "action_type": self.action_type,
            "summary":     self.summary,
            "synced":      self.synced,
        }


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if not db.query(StrategyConfig).filter_by(name="dedup").first():
            db.add(StrategyConfig(
                name        = "dedup",
                enabled     = True,
                config_json = json.dumps({"ttl_seconds": 3600})
            ))
        db.commit()
        logger.debug("DB init success ok")
    except Exception as e:
        logger.debug(f"DB init error: {e}")
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
