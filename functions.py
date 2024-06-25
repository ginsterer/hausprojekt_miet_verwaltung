import hashlib
import math
from typing import Optional, Literal, List, Dict, Tuple
from datetime import datetime, timedelta, date
import json
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from functools import lru_cache
from streamlit_authenticator.utilities import hasher
from models import (
    Group,
    Fund,
    Transaction,
    Expense,
    Room,
    BiddingStatus,
    MonthlyCash,
    MonthlyGiro,
    engine,
    ExpenseChangeLog,
)


Session = sessionmaker(bind=engine)


def add_group(name: str, password: str, role: Literal["user", "admin"]) -> None:
    """Adds a new group to the database."""
    hashed_password = hasher.Hasher._hash(password)
    with Session() as session:
        group = Group(name=name, password=hashed_password, role=role, active=True)
        session.add(group)
        session.commit()


def add_monthly_amount(
    group_id: int, amount: float, start_date: datetime, end_date: datetime
) -> None:
    """Adds a monthly amount for a group."""
    with Session() as session:
        monthly_amount = MonthlyCash(
            group_id=group_id, amount=amount, start_date=start_date, end_date=end_date
        )
        session.add(monthly_amount)
        session.commit()


def add_fund(name: str, yearly_target: float) -> None:
    """Adds a new fund."""
    with Session() as session:
        fund = Fund(
            name=name,
            yearly_target=yearly_target,
            history=json.dumps({datetime.now().year: yearly_target}),
        )
        session.add(fund)
        session.commit()


def confirm_transaction(transaction_id: int) -> None:
    """Confirms a transaction."""
    with Session() as session:
        transaction = (
            session.query(Transaction).filter(Transaction.id == transaction_id).first()
        )
        if transaction.transfer_id:
            related_transactions = (
                session.query(Transaction)
                .filter(Transaction.transfer_id == transaction.transfer_id)
                .all()
            )
        else:
            related_transactions = [transaction]
        for tx in related_transactions:
            tx.confirmed = True
            fund = session.query(Fund).filter(Fund.id == tx.fund_id).first()
            fund.current_balance += tx.amount

        session.commit()


def distribute_funds(group_id: int) -> Optional[Dict[str, float]]:
    """Distributes funds from the Einzahlungstopf to other funds."""
    with Session() as session:
        einzahlungsfonds = (
            session.query(Fund).filter(Fund.name == "Einzahlungsfonds").first()
        )
        if not einzahlungsfonds or einzahlungsfonds.current_balance == 0:
            return

        funds = session.query(Fund).filter(Fund.name != "Einzahlungstopf").all()
        total_target = sum(fund.yearly_target for fund in funds)
        if total_target == 0:
            return

        einzahlungstopf_balance = einzahlungsfonds.current_balance
        for fund in funds:
            ratio = fund.yearly_target / total_target
            amount = round(ratio * einzahlungstopf_balance)
            add_transaction(
                fund.id, amount, datetime.now(), group_id, f"Distribution of deposits"
            )
            add_transaction(
                einzahlungsfonds.id,
                -amount,
                datetime.now(),
                group_id,
                f"Distributed to {fund.name}",
            )

        einzahlungsfonds.current_balance = 0
        session.commit()

        result = {fund.name: fund.current_balance for fund in funds}
        return result


def check_missing_payments() -> Dict[str, List[Tuple[date, float]]]:
    """Checks for missing payments from all groups."""
    with Session() as session:
        groups = session.query(Group).all()
        einzahlungsfonds = (
            session.query(Fund).filter(Fund.name == "Einzahlungsfonds").first()
        )

        missing_payments = {}
        current_year = date(year=2022, month=1, day=1)

        for group in groups:
            last_payment_date = (
                group.last_full_payment_date
                if group.last_full_payment_date
                else current_year
            )
            monthly_amounts = (
                session.query(MonthlyCash)
                .filter(
                    MonthlyCash.group_id == group.id,
                    MonthlyCash.end_date >= last_payment_date,
                )
                .all()
            )

            while last_payment_date < datetime.now().date():
                current_monthly_amount = next(
                    (
                        amount
                        for amount in monthly_amounts
                        if amount.start_date <= last_payment_date <= amount.end_date
                    ),
                    None,
                )

                if current_monthly_amount:
                    required_amount = current_monthly_amount.amount
                    start_date = last_payment_date.replace(day=1)
                    end_date = (
                        last_payment_date.replace(day=28) + timedelta(days=4)
                    ).replace(day=1) - timedelta(days=1)

                    deposited_amount = sum(
                        tx.amount
                        for tx in session.query(Transaction).filter(
                            Transaction.fund_id == einzahlungsfonds.id,
                            Transaction.group == group,
                            Transaction.date.between(start_date, end_date),
                        )
                    )

                    if deposited_amount < required_amount:
                        if group.name not in missing_payments:
                            missing_payments[group.name] = []
                        missing_payments[group.name].append(
                            (start_date, required_amount - deposited_amount)
                        )
                    else:
                        group.last_full_payment_date = start_date + timedelta(days=30)
                        session.commit()

                last_payment_date = (
                    last_payment_date.replace(day=28) + timedelta(days=4)
                ).replace(day=1)

        return missing_payments


def add_transaction(
    fund_id: int,
    amount: float,
    tx_date: date,
    group_id: int,
    comment: Optional[str] = None,
    confirmed: bool = False,
    transfer_id: Optional[int] = None,
) -> None:
    """Adds a transaction."""
    with Session() as session:
        transaction = Transaction(
            fund_id=fund_id,
            amount=amount,
            date=tx_date,
            comment=comment,
            group_id=group_id,
            confirmed=confirmed,
            transfer_id=transfer_id,
        )
        session.add(transaction)
        session.commit()


def transfer_funds(
    from_fund_id: int, to_fund_id: int, amount: float, group_id: int
) -> None:
    """Transfers funds from one fund to another."""
    with Session() as session:
        transfer_id = (
            session.query(Transaction).count() + 1
        )  # Generate a unique transfer_id
        add_transaction(
            from_fund_id,
            -amount,
            datetime.now().date(),
            group_id,
            transfer_id=transfer_id,
            comment=f"Transfer to {to_fund_id}",
        )
        add_transaction(
            to_fund_id,
            amount,
            datetime.now().date(),
            group_id,
            transfer_id=transfer_id,
            comment=f"Transfer from {from_fund_id}",
        )
        session.commit()


def delete_fund(fund_id: int, transfer_to_fund_id: int, group_id: int) -> None:
    """Deletes a fund and transfers its balance to another fund."""
    with Session() as session:
        fund_to_delete = session.query(Fund).filter(Fund.id == fund_id).first()
        transfer_to_fund = (
            session.query(Fund).filter(Fund.id == transfer_to_fund_id).first()
        )
        if fund_to_delete and transfer_to_fund:
            remaining_balance = fund_to_delete.current_balance
            add_transaction(
                transfer_to_fund_id,
                remaining_balance,
                datetime.now().date(),
                group_id,
                f"Transfer from {fund_to_delete.name}",
            )
            session.delete(fund_to_delete)
            session.commit()


def calculate_rent_for_group(
    group_id: int,
) -> Dict[Literal["by_area", "by_head_count", "by_available_income"], float]:
    with Session() as session:
        # Step 1: Calculate the total yearly expenses
        total_yearly_expenses = session.query(func.sum(Expense.yearly_amount)).scalar()

        # Step 2: Calculate the total yearly target from all funds
        total_yearly_target = session.query(func.sum(Fund.yearly_target)).scalar()

        # Step 3: Calculate the monthly total rent
        monthly_total_rent = (total_yearly_expenses + total_yearly_target) / 12

        # Step 4: Calculate the proportion of rent each group should pay by different methods
        # Calculate the total area of rooms and the total head count and income of all members
        total_area = session.query(func.sum(Room.area)).scalar()
        groups_active = session.query(Group).where(Group.active).all()
        total_head_count = sum(group.head_count for group in groups_active)
        all_incomes = [group.available_income for group in groups_active]
        total_available_income = sum(all_incomes)

        # Retrieve the group
        group = session.query(Group).filter(Group.id == group_id).first()
        # Calculate head count for the group
        group_total_head_count: float = group.head_count

        # ### rent by area ### #
        all_rooms = session.query(Room).all()
        room_area_rented_by_all = sum(
            room.area for room in all_rooms if room.tenants == []
        )

        # Distribute the rent for each room among its tenants proportionally to their head count
        group_rent_by_area_count = (
            (room_area_rented_by_all / total_area)  # portion of communal area
            * monthly_total_rent
            * (group_total_head_count / total_head_count)
        )  # portion of heads
        for room in group.rooms:
            room_total_head_count = sum(tenant.head_count for tenant in room.tenants)
            room_rent = (room.area / total_area) * monthly_total_rent
            group_rent_by_area_count += (
                group_total_head_count / room_total_head_count
            ) * room_rent

        # ### rent by head_count ### #
        group_rent_by_head_count = (
            group_total_head_count * monthly_total_rent / total_head_count
        )
        # ### rent by available_income ### #
        group_rent_by_available_income = (
            group.available_income * monthly_total_rent / total_available_income
        )

        return {
            "by_area": group_rent_by_area_count,
            "by_head_count": group_rent_by_head_count,
            "by_available_income": group_rent_by_available_income,
        }


def bids_to_rent(bidding_status: BiddingStatus, session: Session) -> None:
    total_needed = bidding_status.total_amount_needed
    total_pledged = bidding_status.total_amount_pledged

    # Calculate proportion of each bid
    if total_pledged < total_needed:
        cash_needed = bidding_status.total_cash_needed - (total_needed - total_pledged)
    else:
        cash_needed = bidding_status.total_cash_needed
    for bid in bidding_status.bids:
        group = session.query(Group).filter(Group.id == bid.group_id).first()
        proportion = bid.amount / total_pledged
        cash_part = math.ceil(cash_needed * proportion / 5) * 5
        giro_part = (bidding_status.total_giro_needed * proportion) - cash_part

        # Adjust existing MonthlyCash records
        existing_cash_records = (
            session.query(MonthlyCash)
            .filter(
                MonthlyCash.group_id == group.id,
                MonthlyCash.end_date >= bidding_status.period_start,
            )
            .all()
        )
        for record in existing_cash_records:
            record.end_date = bidding_status.period_start

        # Adjust existing MonthlyGiro records
        existing_giro_records = (
            session.query(MonthlyGiro)
            .filter(
                MonthlyGiro.group_id == group.id,
                MonthlyGiro.end_date >= bidding_status.period_start,
            )
            .all()
        )
        for record in existing_giro_records:
            record.end_date = bidding_status.period_start

        # add new records
        new_cash_transfer = MonthlyCash(
            group_id=group.id,
            amount=cash_part,
            start_date=bidding_status.period_start,
            end_date=bidding_status.period_end,
        )
        session.add(new_cash_transfer)

        new_giro_transfer = MonthlyGiro(
            group_id=group.id,
            amount=giro_part,
            start_date=bidding_status.period_start,
            end_date=bidding_status.period_end,
        )
        session.add(new_giro_transfer)
    session.commit()


def current_payments(group, session):
    """
    Retrieve the current monthly cash and giro payments for a specific group.

    Parameters:
    - group: Group object representing the group for which to retrieve the payments.
    - session: SQLAlchemy session object for interacting with the database.

    Returns:
    Tuple containing the current monthly cash payment (float) and the current monthly giro payment amount (float).
    """

    current_cash_payment = (
        session.query(MonthlyCash)
        .filter(
            MonthlyCash.group_id == group.id,
            MonthlyCash.start_date < datetime.now(),
            MonthlyCash.end_date > datetime.now(),
        )
        .first()
    )
    current_giro_payment = (
        session.query(MonthlyGiro)
        .filter(
            MonthlyGiro.group_id == group.id,
            MonthlyGiro.start_date < datetime.now(),
            MonthlyGiro.end_date > datetime.now(),
        )
        .first()
    )
    cash = current_cash_payment.amount if current_cash_payment else 0
    giro = current_giro_payment.amount if current_giro_payment else 0

    return cash, giro


def log_change(session, expense_id, change_type, details, previous_amount, new_amount):
    change_log = ExpenseChangeLog(
        expense_id=expense_id,
        change_type=change_type,
        details=details,
        previous_amount=previous_amount,
        new_amount=new_amount,
    )
    session.add(change_log)
    session.commit()
