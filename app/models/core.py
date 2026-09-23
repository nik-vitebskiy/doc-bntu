import json
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, event, func
from sqlalchemy.dialects.postgresql import JSONB
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
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True)


class Faculty(Base):
    __tablename__ = "faculty"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)


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
    applications: Mapped[list["Application"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
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
    number: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Активен")
    organization: Mapped[Organization] = relationship(back_populates="contracts")
    orders: Mapped[list["Order"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    agreements: Mapped[list["AdditionalAgreement"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="contract")
    faculty_links: Mapped[list["ContractFaculty"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    @property
    def items(self): return [item for order in self.orders if order.is_current for item in order.items]
    @property
    def specialty_codes(self): return list(dict.fromkeys(item.specialty for item in self.items))
    @property
    def faculty_names(self): return [link.faculty.name for link in self.faculty_links]
    @property
    def attachments(self): return [attachment for document in self.documents for attachment in document.attachments]
    @property
    def active_attachments(self): return [attachment for attachment in self.attachments if attachment.deleted_at is None]
    @property
    def has_signed_scan(self):
        own_scan = any(attachment.file_kind == "signed_scan" for attachment in self.active_attachments)
        return own_scan or bool(self.active_agreement and self.active_agreement.has_signed_scan)
    @property
    def active_agreement(self):
        return next((agreement for agreement in self.agreements if agreement.status == "Активен"), None)


class ContractFaculty(Base):
    __tablename__ = "contract_faculty"
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract.id", ondelete="CASCADE"), primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"), primary_key=True)
    contract: Mapped[Contract] = relationship(back_populates="faculty_links")
    faculty: Mapped[Faculty] = relationship()


class ContractRedirect(Base):
    __tablename__ = "contract_redirect"
    old_contract_id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contract.id", ondelete="CASCADE"))


class OrderRedirect(Base):
    __tablename__ = "order_redirect"
    old_order_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))


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
    documents: Mapped[list["Document"]] = relationship(back_populates="additional_agreement")
    @property
    def attachments(self): return [attachment for document in self.documents for attachment in document.attachments]
    @property
    def active_attachments(self): return [attachment for attachment in self.attachments if attachment.deleted_at is None]
    @property
    def has_signed_scan(self): return any(attachment.file_kind == "signed_scan" for attachment in self.active_attachments)


class Application(Base):
    __tablename__ = "application"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organization.id", ondelete="CASCADE"))
    number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    received_date: Mapped[date] = mapped_column(Date)
    signed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Заявка")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    organization: Mapped[Organization] = relationship(back_populates="applications")
    faculty_links: Mapped[list["ApplicationFaculty"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="application")
    documents: Mapped[list["Document"]] = relationship(back_populates="application")
    @property
    def faculty_names(self): return [link.faculty.name for link in self.faculty_links]
    @property
    def current_order(self): return next((order for order in self.orders if order.is_current), None)
    @property
    def items(self): return self.current_order.items if self.current_order else []
    @property
    def attachments(self): return [attachment for document in self.documents for attachment in document.attachments]
    @property
    def active_attachments(self): return [attachment for attachment in self.attachments if attachment.deleted_at is None]
    @property
    def has_signed_scan(self): return any(attachment.file_kind == "signed_scan" for attachment in self.active_attachments)


class ApplicationFaculty(Base):
    __tablename__ = "application_faculty"
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"), primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"), primary_key=True)
    application: Mapped[Application] = relationship(back_populates="faculty_links")
    faculty: Mapped[Faculty] = relationship()


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
    application_id: Mapped[int | None] = mapped_column(ForeignKey("application.id", ondelete="SET NULL"), nullable=True)
    previous_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    contract: Mapped[Contract | None] = relationship(back_populates="orders")
    additional_agreement: Mapped[AdditionalAgreement | None] = relationship(back_populates="orders")
    application: Mapped[Application | None] = relationship(back_populates="orders")
    creator: Mapped[AppUser | None] = relationship(foreign_keys=[created_by])
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    specialty_id: Mapped[int] = mapped_column(ForeignKey("specialty.id"))
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id"), nullable=True)
    qualification_value: Mapped[str | None] = mapped_column("qualification", String(255), nullable=True)
    profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order: Mapped[Order] = relationship(back_populates="items")
    specialty_ref: Mapped[Specialty] = relationship()
    faculty: Mapped[Faculty | None] = relationship()
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
    application_id: Mapped[int | None] = mapped_column(ForeignKey("application.id", ondelete="SET NULL"), nullable=True)
    additional_agreement_id: Mapped[int | None] = mapped_column(ForeignKey("additional_agreement.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    contract: Mapped[Contract | None] = relationship(back_populates="documents")
    application: Mapped[Application | None] = relationship(back_populates="documents")
    additional_agreement: Mapped[AdditionalAgreement | None] = relationship(back_populates="documents")
    attachments: Mapped[list["DocumentAttachment"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentAttachment(Base):
    __tablename__ = "document_attachment"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id", ondelete="CASCADE"), index=True)
    file_kind: Mapped[str] = mapped_column(String(30), index=True)
    original_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # Card/list queries never need the blob. Loading is explicit for tests and
    # chunked with SQL substring() for downloads.
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    document: Mapped[Document] = relationship(back_populates="attachments")
    uploader: Mapped[AppUser | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(nullable=True)
    entity_label: Mapped[str] = mapped_column(String(500))
    diff: Mapped[dict] = mapped_column(JSONB, default=lambda: {"old": {}, "new": {}})
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    parent_event_id: Mapped[int | None] = mapped_column(ForeignKey("audit_log.id", ondelete="RESTRICT"), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _reject_audit_mutation(_mapper, _connection, _target):
    raise ValueError("Audit records are immutable")


event.listen(AuditLog, "before_update", _reject_audit_mutation)
event.listen(AuditLog, "before_delete", _reject_audit_mutation)
