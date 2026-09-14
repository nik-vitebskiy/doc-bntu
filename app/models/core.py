from datetime import date
from sqlalchemy import String, ForeignKey, Text, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(500), unique=True)
    full_name: Mapped[str] = mapped_column(String(700), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    profile: Mapped[str] = mapped_column(String(500), default="")
    phones: Mapped[str] = mapped_column(String(300), default="")
    department: Mapped[str] = mapped_column(String(500), default="")
    contact: Mapped[str] = mapped_column(String(500), default="")
    contracts: Mapped[list["Contract"]] = relationship(back_populates="organization", cascade="all, delete-orphan")

class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    faculty: Mapped[str] = mapped_column(String(300), default="")
    number: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(100), default="Активен")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    organization: Mapped[Organization] = relationship(back_populates="contracts")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    uploads: Mapped[list["Upload"]] = relationship(back_populates="contract", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    specialty: Mapped[str] = mapped_column(String(300), default="")
    qualification: Mapped[str] = mapped_column(String(300), default="")
    demand_json: Mapped[str] = mapped_column(Text, default="{}")
    contract: Mapped[Contract] = relationship(back_populates="items")

class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    filename: Mapped[str] = mapped_column(String(500))
    stored_name: Mapped[str] = mapped_column(String(500))
    contract: Mapped[Contract] = relationship(back_populates="uploads")
