import datetime
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # completed, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
