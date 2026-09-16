import json
from datetime import date, datetime
from pathlib import Path
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(30), default="SYSTEM")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Faculty(Base):
    __tablename__ = "faculty"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    contracts: Mapped[list["Contract"]] = relationship(back_populates="faculty")


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[int] = mapped_column(primary_key=True)
    unp: Mapped[str] = mapped_column(String(9), unique=True)
    short_name: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(Text)
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    authority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contracts: Mapped[list["Contract"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    @property
    def name(self): return self.short_name
    @property
    def address(self): return self.legal_address
    @property
    def department(self): return self.authority
    @property
    def phones(self): return self.phone
class Contract(Base):
    __tablename__ = "contract"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organization.id", ondelete="CASCADE"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"))
    number: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    organization: Mapped[Organization] = relationship(back_populates="contracts")
    faculty: Mapped[Faculty] = relationship(back_populates="contracts")
    orders: Mapped[list["Order"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    agreements: Mapped[list["AdditionalAgreement"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="contract")
    @property
    def faculty_name(self): return self.faculty.name
    @property
    def items(self): return [item for order in self.orders if order.is_current for item in order.items]
    @property
    def specialty_codes(self): return list(dict.fromkeys(item.specialty for item in self.items))
    @property
    def uploads(self): return [doc for doc in self.documents if doc.type == "SIGNED_SCAN"]


class AdditionalAgreement(Base):
    __tablename__ = "additional_agreement"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract.id", ondelete="CASCADE"))
    number: Mapped[str] = mapped_column(String(100))
    date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="Активен")
    previous_agreement_id: Mapped[int | None] = mapped_column(ForeignKey("additional_agreement.id"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contract: Mapped[Contract] = relationship(back_populates="agreements")
    orders: Mapped[list["Order"]] = relationship(back_populates="additional_agreement")


class Specialty(Base):
    __tablename__ = "specialty"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    qualification: Mapped[str | None] = mapped_column(String(255), nullable=True)
    faculty: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organization.id", ondelete="CASCADE"))
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contract.id", ondelete="SET NULL"), nullable=True)
    additional_agreement_id: Mapped[int | None] = mapped_column(ForeignKey("additional_agreement.id", ondelete="SET NULL"), nullable=True)
    application_id: Mapped[int | None] = mapped_column(nullable=True)
    previous_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    contract: Mapped[Contract | None] = relationship(back_populates="orders")
    additional_agreement: Mapped[AdditionalAgreement | None] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    specialty_id: Mapped[int] = mapped_column(ForeignKey("specialty.id"))
    qualification_value: Mapped[str | None] = mapped_column("qualification", String(255), nullable=True)
    profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order: Mapped[Order] = relationship(back_populates="items")
    specialty_ref: Mapped[Specialty] = relationship()
    annual_demands: Mapped[list["AnnualDemand"]] = relationship(back_populates="order_item", cascade="all, delete-orphan")
    @property
    def contract_id(self): return self.order.contract_id
    @property
    def contract(self): return self.order.contract
    @property
    def specialty(self): return self.specialty_ref.code
    @property
    def qualification(self): return self.qualification_value or self.specialty_ref.qualification or ""
    @property
    def demand_json(self): return json.dumps({str(row.year): row.quantity for row in self.annual_demands}, ensure_ascii=False)


class AnnualDemand(Base):
    __tablename__ = "annual_demand"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_item.id", ondelete="CASCADE"))
    year: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    order_item: Mapped[OrderItem] = relationship(back_populates="annual_demands")


class Document(Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organization.id", ondelete="CASCADE"))
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contract.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract: Mapped[Contract | None] = relationship(back_populates="documents")
    @property
    def stored_name(self): return self.file_id or ""
    @property
    def filename(self):
        value = self.file_id or ""
        return value.split("-", 1)[1] if "-" in value else Path(value).name


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
