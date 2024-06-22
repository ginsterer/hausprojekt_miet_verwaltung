import enum
import logging
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    ForeignKey,
    Boolean,
    create_engine,
    Table,
    Enum,
    DateTime,
)
from sqlalchemy.orm import relationship, sessionmaker, declarative_base

Base = declarative_base()
engine = create_engine("sqlite:///cash_management.db")
Session = sessionmaker(bind=engine)


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    last_full_payment_date = Column(Date, default=datetime.utcnow)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # e.g., 'admin', 'user'
    active = Column(Boolean)
    transactions = relationship("Transaction", back_populates="group")
    rooms = relationship("Room", secondary="room_tenants", back_populates="tenants")
    members = relationship("Person", back_populates="group")
    income = Column(Integer)
    bids = relationship("Bid", back_populates="group")
    last_updated = Column(Date, default=datetime.utcnow)

    @property
    def head_count(self) -> float:
        return sum(member.category.head_count for member in self.members)

    @property
    def available_income(self) -> int:
        total_base_need = sum(
            person.category.monthly_base_need for person in self.members
        )
        return self.income - total_base_need


class BiddingStatus(Base):
    __tablename__ = "bidding_status"
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String)  # e.g., 'open', 'closed', 'evaluated'
    total_giro_needed = Column(Float)
    total_cash_needed = Column(Float)
    total_amount_pledged = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    bids = relationship("Bid", back_populates="bidding_status")
    period_start = Column(Date)
    period_end = Column(Date)

    @property
    def total_amount_needed(self) -> float:
        return self.total_cash_needed + self.total_giro_needed

    @property
    def amount_shortfall(self) -> float:
        return self.total_amount_needed - self.total_amount_pledged


class Bid(Base):
    __tablename__ = "bids"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    group = relationship("Group", back_populates="bids")
    bidding_status_id = Column(Integer, ForeignKey("bidding_status.id"))
    bidding_status = relationship("BiddingStatus", back_populates="bids")
    amount = Column(Float)
    submitted_at = Column(DateTime, default=datetime.utcnow)


class Person(Base):
    __tablename__ = "persons"
    id = Column(Integer, primary_key=True)
    category = relationship("PeopleCategory")
    category_id = Column(Integer, ForeignKey("people_categories.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    group = relationship("Group", back_populates="members")


class PeopleCategory(Base):
    __tablename__ = "people_categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    monthly_base_need = Column(Integer)
    head_count = Column(Float, nullable=False, default=0.0)


class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    area = Column(Float)
    tenants = relationship("Group", secondary="room_tenants", back_populates="rooms")


room_tenants = Table(
    "room_tenants",
    Base.metadata,
    Column("group_id", Integer, ForeignKey("groups.id")),
    Column("room_id", Integer, ForeignKey("rooms.id")),
)


class MonthlyCash(Base):
    __tablename__ = "monthly_cash_amounts"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    amount = Column(Float)
    start_date = Column(Date)
    end_date = Column(Date)


class MonthlyGiro(Base):
    __tablename__ = "monthly_giro_amounts"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    amount = Column(Float)
    start_date = Column(Date)
    end_date = Column(Date)


class Fund(Base):
    __tablename__ = "funds"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    current_balance = Column(Float, default=0)
    yearly_target = Column(Float)
    history = Column(String, default="{}")  # JSON-encoded string
    transactions = relationship("Transaction", back_populates="fund")


class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    yearly_amount = Column(Float)
    type = Column(Enum("ancillary", "rent", name="rent_type"), nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    fund_id = Column(Integer, ForeignKey("funds.id"))
    fund = relationship("Fund", back_populates="transactions")
    amount = Column(Float)
    date = Column(Date)
    comment = Column(String, nullable=True)
    confirmed = Column(Boolean, default=False)
    group_id = Column(Integer, ForeignKey("groups.id"))
    group = relationship("Group", back_populates="transactions")
    transfer_id = Column(Integer, nullable=True)


Base.metadata.create_all(bind=engine)
