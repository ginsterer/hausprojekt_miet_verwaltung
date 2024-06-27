from typing import Literal
import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import sessionmaker
import streamlit_authenticator as stauth
from functions import (
    add_group,
    add_fund,
    add_transaction,
    distribute_funds,
    check_missing_payments,
    transfer_funds,
    delete_fund,
    add_monthly_amount,
    confirm_transaction,
    bids_to_rent,
    calculate_rent_for_group,
    current_payments,
    log_change,
)
from models import (
    Group,
    Fund,
    Base,
    engine,
    MonthlyCash,
    Transaction,
    Room,
    PeopleCategory,
    Person,
    BiddingStatus,
    Bid,
    Expense,
    ExpenseChangeLog,
    FundChangeLog,
)

Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)


# Retrieve data from the database
def get_groups():
    with Session() as session:
        return session.query(Group).all()


def get_funds():
    with Session() as session:
        return session.query(Fund).all()


groups = get_groups()
funds = get_funds()

# Authentication setup
credentials = {"usernames": {}}

for group in groups:
    credentials["usernames"][group.name] = {
        "password": group.password,
        "name": group.name,
    }
roles = {group.name: group.role for group in groups}

authenticator = stauth.Authenticate(
    credentials, "Hausprojekt_verwaltung", "verwaltung123", cookie_expiry_days=30
)

name, authentication_status, _ = authenticator.login("main")


def show_dashboard():
    st.header("Dashboard")
    with st.expander("Gesamtmiete Entwicklung"):

        if st.button("Aktualisieren", key="rent_plot"):
            # Call the function to display the plot
            st.plotly_chart(plot_rent_development())

    with st.expander(
        "Fonds Übersicht",
    ):
        if st.button("Aktualisieren", key="fund_plot"):
            fig = plot_funds()

            st.plotly_chart(fig)


def plot_funds():
    with Session() as session:
        confirmed_transactions = (
            session.query(Transaction).filter(Transaction.confirmed == True).all()
        )
        transactions_data = [
            {
                "Datum": transaction.date,
                "Fonds": transaction.fund.name,
                "Betrag": transaction.amount,
                "Person": transaction.group.name,
                "Kommentar": transaction.comment,
            }
            for transaction in confirmed_transactions
        ]
    df = pd.DataFrame(transactions_data)
    df["Datum"] = pd.to_datetime(df["Datum"])
    df.sort_values(by="Datum", inplace=True)
    date_range = pd.date_range(start=df["Datum"].min(), end=df["Datum"].max())
    funds = df["Fonds"].unique()
    complete_df = pd.MultiIndex.from_product(
        [date_range, funds], names=["Datum", "Fonds"]
    ).to_frame(index=False)
    df = pd.merge(complete_df, df, on=["Datum", "Fonds"], how="left").sort_values(
        by=["Datum", "Fonds"]
    )
    df["Betrag"].fillna(0, inplace=True)
    df["Saldo"] = df.groupby("Fonds")["Betrag"].cumsum()
    df["Person"].fillna(method="ffill", inplace=True)
    df["Kommentar"].fillna(method="ffill", inplace=True)
    fig = px.area(
        df,
        x="Datum",
        y="Saldo",
        color="Fonds",
        title="Fonds-Salden im Zeitverlauf",
        hover_data={"Betrag": True, "Person": True, "Kommentar": True},
    )
    return fig


def plot_rent_development():
    with Session() as session:
        # Retrieve change logs for expenses and funds
        expense_logs = session.query(ExpenseChangeLog).all()
        fund_logs = session.query(FundChangeLog).all()

        # Retrieve current values for expenses and funds
        current_expenses = session.query(Expense).all()
        current_funds = session.query(Fund).all()

        # Process expense logs
        expense_data = [
            {
                "date": log.timestamp,
                "name": log.expense.name,
                "amount": log.new_amount - (log.previous_amount or 0),
                "type": "expense",
                "details": log.details,
            }
            for log in expense_logs
        ]

        # Process fund logs
        fund_data = [
            {
                "date": log.timestamp,
                "name": log.fund.name,
                "amount": log.new_amount - (log.previous_amount or 0),
                "type": "fund",
                "details": log.details,
            }
            for log in fund_logs
        ]

        # Combine data
        data = expense_data + fund_data
        df = pd.DataFrame(data)

        # Display overview of changes in a scrollable table
        st.subheader("Übersicht der Änderungen")
        st.dataframe(df[["date", "name", "amount", "details"]])

        # Ensure data points for all expenses and funds at each timestamp
        all_names = [expense.name for expense in current_expenses] + [
            fund.name for fund in current_funds
        ]
        date_range = pd.date_range(
            start=df["date"].min(), end=df["date"].max(), inclusive="both"
        )
        df["date"] = df["date"].dt.normalize()
        df = df.groupby(["date", "name"]).sum().reindex()

        complete_df = pd.MultiIndex.from_product(
            [date_range, all_names], names=["date", "name"]
        ).to_frame(index=False)
        df = pd.merge(complete_df, df, on=["date", "name"], how="left").sort_values(
            by=["date", "name"]
        )

        # Fill missing values
        df["amount"].fillna(0, inplace=True)
        # Calculate cumulative sum per month
        df["cumulative_amount"] = df.groupby(["name"])["amount"].cumsum() / 12

        # Display current total rent per month
        st.subheader("Aktuelle Gesamtmiete pro Monat")
        # Calculate current total rent per month
        current_total_rent = df.loc[
            df["date"] == df["date"].max(), "cumulative_amount"
        ].sum()
        st.write(
            f"Die aktuelle Gesamtmiete pro Monat beträgt: {current_total_rent:.2f} EUR"
        )

        # Plot using Plotly
        fig = px.area(
            df,
            x="date",
            y="cumulative_amount",
            color="name",
            title="Entwicklung der Miete",
        )

        return fig


#
# def plot_development():
#     with Session() as session:
#         # Retrieve change logs for expenses and funds
#         expense_logs = session.query(ExpenseChangeLog).all()
#         fund_logs = session.query(FundChangeLog).all()
#
#         # Retrieve current values for expenses and funds
#         current_expenses = session.query(Expense).all()
#         current_funds = session.query(Fund).all()
#
#         # Process expense logs
#         expense_data = [
#             {
#                 "date": log.timestamp,
#                 "name": session.query(Expense)
#                 .filter(Expense.id == log.expense_id)
#                 .first()
#                 .name,
#                 "amount": log.new_amount - (log.previous_amount or 0),
#                 "type": "expense",
#             }
#             for log in expense_logs
#         ]
#
#         # Process fund logs
#         fund_data = [
#             {
#                 "date": log.timestamp,
#                 "name": session.query(Fund).filter(Fund.id == log.fund_id).first().name,
#                 "amount": log.new_amount - (log.previous_amount or 0),
#                 "type": "fund",
#             }
#             for log in fund_logs
#         ]
#
#         # Combine data
#         data = expense_data + fund_data
#         df = pd.DataFrame(data)
#
#         # Ensure data points for all expenses and funds at each timestamp
#         all_names = [expense.name for expense in current_expenses] + [
#             fund.name for fund in current_funds
#         ]
#         date_range = pd.date_range(
#             start=df["date"].min(), end=df["date"].max(), freq="M"
#         )
#         complete_df = pd.MultiIndex.from_product(
#             [date_range, all_names], names=["date", "name"]
#         ).to_frame(index=False)
#         df = pd.merge(complete_df, df, on=["date", "name"], how="left").sort_values(
#             by=["date", "name"]
#         )
#
#         # Fill missing values
#         df["amount"].fillna(0, inplace=True)
#
#         # Calculate cumulative sum per month
#         df["cumulative_amount"] = df.groupby(["name"])["amount"].cumsum()
#
#         # Plot using Plotly
#         fig = px.area(
#             df,
#             x="date",
#             y="cumulative_amount",
#             color="name",
#             title="Entwicklung der Miete",
#         )
#         st.plotly_chart(fig)
#


def show_user_profile(user: Group):
    st.header("Mein Profil")
    st.subheader("Persönliche Daten")

    with Session() as session:
        group = session.query(Group).filter(Group.name == user.name).first()
        if group:
            new_name = st.text_input("Name", value=group.name)
            new_password = st.text_input("Passwort", type="password")
            new_income = st.number_input("Einkommen", value=group.income)

            if st.button("Eingabe bestätigen"):
                group.name = new_name
                if new_password:
                    group.password = new_password
                group.income = new_income
                group.last_updated = datetime.now()
                session.commit()
                st.success("Profil aktualisiert!")

            st.subheader("Räume")
            current_rooms = [room.name for room in group.rooms]
            st.write("Aktuelle Räume:", ", ".join(current_rooms))

            all_rooms = session.query(Room).all()
            available_rooms = [
                (room.id, room.name)
                for room in all_rooms
                if room.name not in current_rooms
            ]
            selected_room = st.selectbox(
                "Neuen Raum hinzufügen",
                options=available_rooms,
                format_func=lambda x: x[1],
            )
            if st.button("Raum hinzufügen"):
                room_to_add = (
                    session.query(Room).filter(Room.id == selected_room[0]).first()
                )
                group.rooms.append(room_to_add)
                session.commit()
                st.success(f"Raum {room_to_add.name} hinzugefügt!")

            st.subheader("Mitglieder")
            current_members = [
                (member.id, member.category.name) for member in group.members
            ]
            st.write("Aktuelle Mitglieder:")
            for member in current_members:
                st.write(f"ID: {member[0]}, Kategorie: {member[1]}")

            all_categories = session.query(PeopleCategory).all()
            available_categories = [(cat.id, cat.name) for cat in all_categories]
            selected_category = st.selectbox(
                "Kategorie für neues Mitglied",
                options=available_categories,
                format_func=lambda x: x[1],
            )
            if st.button("Mitglied hinzufügen"):
                new_person = Person(category_id=selected_category[0], group_id=group.id)
                session.add(new_person)
                session.commit()
                st.success("Mitglied hinzugefügt!")


def manage_rooms_and_categories():
    st.header("Räume und Bewohnerinnen verwalten")
    with st.expander("Bewohnerinnen"):
        show_group_management
    with st.expander("Räume"):

        with Session() as session:
            # Rooms Management
            st.subheader("Räume")
            rooms = session.query(Room).all()
            groups = session.query(Group).all()

            st.write("Aktuelle Räume:")
            room_data = [
                {"ID": room.id, "Name": room.name, "Fläche": room.area}
                for room in rooms
            ]
            st.table(room_data)

            with st.form("add_room_form"):
                new_room_name = st.text_input("Neuer Raumname")
                new_room_area = st.number_input(
                    "Raumfläche (in Quadratmetern)", min_value=0.0
                )
                add_room_submit = st.form_submit_button("Raum hinzufügen")

                if add_room_submit and new_room_name:
                    new_room = Room(name=new_room_name, area=new_room_area)
                    session.add(new_room)
                    session.commit()
                    st.success("Neuer Raum hinzugefügt!")

            # Edit or Delete Existing Rooms
            st.subheader("Bestehende Räume bearbeiten oder löschen")
            room_options = [(room.id, room.name) for room in rooms]
            selected_room_id = st.selectbox(
                "Raum auswählen zum Bearbeiten oder Löschen",
                options=room_options,
                format_func=lambda x: x[1],
            )

            if selected_room_id:
                selected_room = (
                    session.query(Room).filter(Room.id == selected_room_id[0]).first()
                )
                with st.form("edit_room_form"):
                    edit_room_name = st.text_input("Raumname", value=selected_room.name)
                    edit_room_area = st.number_input(
                        "Raumfläche (in Quadratmetern)",
                        value=selected_room.area,
                        min_value=0.0,
                    )
                    update_room_submit = st.form_submit_button("Raum aktualisieren")
                    delete_room_submit = st.form_submit_button("Raum löschen")

                    if update_room_submit:
                        selected_room.name = edit_room_name
                        selected_room.area = edit_room_area
                        session.commit()
                        st.success("Raum aktualisiert!")
                    if delete_room_submit:
                        session.delete(selected_room)
                        session.commit()
                        st.success("Raum gelöscht!")

                with st.form("manage_tenants_form"):
                    tenants = [tenant.name for tenant in selected_room.tenants]
                    st.write("Aktuelle Mieterinnen: " + ", ".join(tenants))
                    group_options = [(group.id, group.name) for group in groups]
                    selected_group_id = st.selectbox(
                        "Gruppe auswählen",
                        options=group_options,
                        format_func=lambda x: x[1],
                    )
                    add_group_to_room_submit = st.form_submit_button(
                        "Gruppe zum Raum hinzufügen"
                    )
                    remove_group_from_room_submit = st.form_submit_button(
                        "Gruppe aus dem Raum entfernen"
                    )

                    if add_group_to_room_submit:
                        selected_group = (
                            session.query(Group)
                            .filter(Group.id == selected_group_id[0])
                            .first()
                        )
                        selected_room.tenants.append(selected_group)
                        session.commit()
                        st.success("Gruppe zum Raum hinzugefügt!")

                    if remove_group_from_room_submit:
                        selected_group = (
                            session.query(Group)
                            .filter(Group.id == selected_group_id[0])
                            .first()
                        )
                        selected_room.tenants.remove(selected_group)
                        session.commit()
                        st.success("Gruppe aus dem Raum entfernt!")

        # PeopleCategory Management
        with st.expander("Personenekategorien"):

            st.subheader("Personenkategorien")
            categories = session.query(PeopleCategory).all()

            st.write("Aktuelle Kategorien:")
            category_data = [
                {
                    "ID": category.id,
                    "Name": category.name,
                    "Monatliches Grundbedarf": category.monthly_base_need,
                }
                for category in categories
            ]
            st.table(category_data)

            with st.form("add_category_form"):
                new_category_name = st.text_input("Neue Kategorie Name")
                new_category_income = st.number_input(
                    "Monatlicher Grundbedarf", min_value=0
                )
                new_category_head_count = st.number_input(
                    "Personenzählwert", value=1, min_value=0
                )
                add_category_submit = st.form_submit_button("Kategorie hinzufügen")

                if add_category_submit and new_category_name:
                    new_category = PeopleCategory(
                        name=new_category_name,
                        monthly_base_need=new_category_income,
                        head_count=new_category_head_count,
                    )
                    session.add(new_category)
                    session.commit()
                    st.success("Neue Kategorie hinzugefügt!")

            # Edit or Delete Existing Categories
            st.subheader("Bestehende Kategorien bearbeiten oder löschen")
            category_options = [(cat.id, cat.name) for cat in categories]
            selected_category_id = st.selectbox(
                "Kategorie auswählen zum Bearbeiten oder Löschen",
                options=category_options,
                format_func=lambda x: x[1],
            )

            if selected_category_id:
                selected_category = (
                    session.query(PeopleCategory)
                    .filter(PeopleCategory.id == selected_category_id[0])
                    .first()
                )
                with st.form("edit_category_form"):
                    edit_category_name = st.text_input(
                        "Kategorie Name", value=selected_category.name
                    )
                    edit_category_income = st.number_input(
                        "Monatlicher Grundbedarf",
                        value=selected_category.monthly_base_need,
                        min_value=0,
                    )
                    edit_category_head_count = st.number_input(
                        "Personenzählwert",
                        value=float(selected_category.head_count),
                        min_value=0.0,
                    )
                    update_category_submit = st.form_submit_button(
                        "Kategorie aktualisieren"
                    )
                    delete_category_submit = st.form_submit_button("Kategorie löschen")

                    if update_category_submit:
                        selected_category.name = edit_category_name
                        selected_category.monthly_base_need = edit_category_income
                        selected_category.head_count = edit_category_head_count
                        session.commit()
                        st.success("Kategorie aktualisiert!")
                    if delete_category_submit:
                        session.delete(selected_category)
                        session.commit()
                        st.success("Kategorie gelöscht!")


def evaluate_bids_and_start_round():
    st.header("Gebote auswerten und Bietrunde starten")

    with Session() as session:
        # Check for existing open bidding round
        bidding_status: BiddingStatus = (
            session.query(BiddingStatus)
            .filter(BiddingStatus.status == "open")
            .order_by(BiddingStatus.created_at.desc())
            .first()
        )

        if bidding_status:
            st.subheader("Aktuelle Bietrunde")

            total_needed = bidding_status.total_amount_needed
            total_pledged = bidding_status.total_amount_pledged

            active_groups = session.query(Group).filter(Group.active == True).all()
            active_groups_count = len(active_groups)
            submitted_bids = (
                session.query(Bid)
                .filter(Bid.bidding_status_id == bidding_status.id)
                .all()
            )
            submitted_bids_count = len(submitted_bids)
            groups_with_bids = {bid.group_id for bid in submitted_bids}
            groups_missing_bids = [
                group.name
                for group in active_groups
                if group.id not in groups_with_bids
            ]

            if submitted_bids_count >= active_groups_count:
                if total_pledged >= total_needed:
                    st.success(
                        "Alle Gebote abgegeben. Gesamtbetrag erreicht! "
                        f"Um {bidding_status.amount_shortfall:.2f} überboten."
                    )
                    accept_button = st.button(
                        "Miete so festlegen. Überschuss auf alle verteilen."
                    )
                else:
                    st.warning(
                        f"Es fehlen noch {bidding_status.amount_shortfall:.2f} EUR."
                    )
                    accept_button = st.button(
                        "Miete so festlegen. Fehlbetrag von Puffern abziehen."
                    )

                decline_button = st.button("Gebot ablehnen und neue Runde starten")

                if accept_button:
                    bidding_status.status = "accepted"
                    session.commit()
                    bids_to_rent(bidding_status, session)
                elif decline_button:
                    bidding_status.status = "declined"
                    session.commit()
                    start_new_bidding_round(session, bidding_status)
            else:
                st.warning("Noch nicht alle Gebote abgegeben.")
                st.write("Gruppen ohne Gebot:")
                for group_name in groups_missing_bids:
                    st.write(group_name)
        else:
            st.subheader("Keine offene Bietrunde verfügbar oder bereits ausgewertet.")

            st.header("Bietrunde starten")
            with st.form("start_bidding"):

                total_yearly_expenses = session.query(
                    func.sum(Expense.yearly_amount)
                ).scalar()
                total_yearly_target = session.query(
                    func.sum(Fund.yearly_target)
                ).scalar()
                month_start = pd.Timestamp.today().replace(day=1) + pd.DateOffset(
                    months=1
                )
                period_start = st.date_input(
                    "Beginn des Mietzeitraums", value=month_start
                )
                period_end = st.date_input(
                    "Ende des Mietzeitraums", month_start + pd.DateOffset(months=6)
                )
                if st.form_submit_button("Bietrunde starten"):
                    new_bidding_status = BiddingStatus(
                        status="open",
                        total_cash_needed=total_yearly_target / 12,
                        total_giro_needed=total_yearly_expenses / 12,
                        total_amount_pledged=0,
                        period_start=period_start,
                        period_end=period_end,
                    )
                    session.add(new_bidding_status)
                    session.commit()
                    st.success("Neue Bietrunde gestartet!")


def start_new_bidding_round(session, previous_bidding_status):
    new_bidding_status = BiddingStatus(
        status="open",
        total_cash_needed=previous_bidding_status.total_cash_needed,
        total_giro_needed=previous_bidding_status.total_giro_needed,
        total_amount_pledged=0,
        period_start=previous_bidding_status.period_start,
        period_end=previous_bidding_status.period_end,
    )
    session.add(new_bidding_status)
    session.commit()
    st.success("Neue Bietrunde gestartet!")


def submit_rent_bid(user: Group):
    st.header("Mietberechnung")

    with Session() as session:
        # Check if all active groups were updated in the last month
        one_month_ago = datetime.now() - pd.Timedelta(days=30)
        active_groups_updated = (
            session.query(Group)
            .filter(Group.active, Group.last_updated < one_month_ago)
            .count()
            == 0
        )
        missing_income = (
            session.query(Group).filter(Group.active, Group.income == None).count() != 0
        )

        if missing_income or not active_groups_updated:
            st.warning(
                "Alle aktiven Gruppen müssen im letzten Monat aktualisiert worden sein, um die Mietberechnung anzuzeigen."
            )
            return

        group = session.query(Group).filter(Group.name == user.name).first()
        if group:
            rent_calculation = calculate_rent_for_group(group.id)
            st.write(
                f"Miete berechnet nach Fläche: {rent_calculation['by_area']:.2f} EUR"
            )
            st.write(
                f"Miete berechnet nach Kopfanzahl: {rent_calculation['by_head_count']:.2f} EUR"
            )
            st.write(
                f"Miete berechnet nach verfügbarem Einkommen: {rent_calculation['by_available_income']:.2f} EUR"
            )

    st.header("Mietgebot abgeben")

    with Session() as session:
        group = session.query(Group).filter(Group.name == user.name).first()
        if group:
            current_bidding_status: BiddingStatus = (
                session.query(BiddingStatus)
                .filter(BiddingStatus.status == "open")
                .first()
            )
            if not current_bidding_status:
                st.warning("Keine offene Bietrunde verfügbar.")
                return

            # Retrieve the last declined bidding round
            last_declined_bidding_status = (
                session.query(BiddingStatus)
                .filter(BiddingStatus.status == "declined")
                .filter(BiddingStatus.period_end == current_bidding_status.period_end)
                .filter(
                    BiddingStatus.period_start == current_bidding_status.period_start
                )
                .order_by(BiddingStatus.created_at.desc())
                .first()
            )

            if last_declined_bidding_status:
                shortfall = last_declined_bidding_status.amount_shortfall
                if shortfall > 0:
                    st.warning(
                        f"Es fehlen noch {shortfall:.2f} EUR aus der letzten Bietrunde."
                    )
                else:
                    st.info(
                        f"Die letzte Bietrunde hatte einen Überschuss von {-shortfall:.2f} EUR."
                    )

                # Retrieve the previous bid amount for the group
                previous_bid = (
                    session.query(Bid)
                    .filter(
                        Bid.group_id == group.id,
                        Bid.bidding_status_id == last_declined_bidding_status.id,
                    )
                    .first()
                )
                previous_bid_amount = previous_bid.amount if previous_bid else 0.0
            else:
                previous_bid_amount = 0.0

            existing_bid = (
                session.query(Bid)
                .filter(
                    Bid.group_id == group.id,
                    Bid.bidding_status_id == current_bidding_status.id,
                )
                .first()
            )
            if existing_bid:
                st.warning(
                    "Sie haben bereits ein Gebot für die aktuelle Bietrunde abgegeben."
                )
                return

            # Retrieve the current rent payment for the group
            current_cash, current_giro = current_payments(group, session)

            # Display the period start and end dates for the current bidding round
            st.write(f"Aktuelle Mietzahlung: {current_cash+current_giro:.2f} EUR")
            st.write(
                f"Zeitraum der aktuellen Bietrunde: {current_bidding_status.period_start} bis {current_bidding_status.period_end}"
            )

            bid_amount = st.number_input(
                "Gebot für Miete (EUR)", min_value=0.0, value=previous_bid_amount
            )
            if st.button("Eingabe bestätigen"):
                current_bidding_status.bids.append(
                    Bid(
                        group_id=group.id,
                        bidding_status_id=current_bidding_status.id,
                        amount=bid_amount,
                    )
                )

                # Update BiddingStatus
                total_pledged = sum(bid.amount for bid in current_bidding_status.bids)
                current_bidding_status.total_amount_pledged = total_pledged
                session.commit()
                # Check if all active groups have submitted a bid
                active_groups_count = (
                    session.query(func.count(Group.id))
                    .filter(Group.active == True)
                    .scalar()
                )
                submitted_bids_count = len(current_bidding_status.bids)

                if submitted_bids_count >= active_groups_count:
                    st.success(
                        "Alle Gebote abgegeben. Sag doch der Verwaltungs-AG Bescheid."
                    )
                else:
                    st.success(
                        "Gebot erfolgreich abgegeben! Warten auf weitere Gebote."
                    )


def show_group_management():
    st.subheader("Personenverwaltung")

    # Neue Person hinzufügen
    with st.expander("Neue Person hinzufügen"):
        with st.form("Neue Person hinzufügen"):

            new_group_name = st.text_input("Name der Person", key="new_group_name")
            new_group_password = st.text_input(
                "Passwort", type="password", key="new_group_password"
            )
            new_group_role = st.selectbox(
                "Rolle", ["user", "admin"], key="new_group_role"
            )

            button = st.form_submit_button("Person hinzufügen")
        if button:
            add_group(new_group_name, new_group_password, new_group_role)
            st.success(f"Person {new_group_name} hinzugefügt!")

    # Personenübersicht und Bearbeitung
    st.subheader("Personenübersicht")
    with Session() as session:
        groupen = session.query(Group).filter(Group.active == True).all()
        for group in groupen:
            with st.expander(f"{group.name} (ID: {group.id}, Rolle: {group.role})"):
                edit_name = st.text_input(
                    "Name", value=group.name, key=f"edit_name_{group.id}"
                )
                edit_password = st.text_input(
                    "Passwort", type="password", key=f"edit_password_{group.id}"
                )
                edit_role = st.selectbox(
                    "Rolle",
                    ["user", "admin"],
                    index=["user", "admin"].index(group.role),
                    key=f"edit_role_{group.id}",
                )

                if st.button(f"Änderungen speichern", key=f"save_changes_{group.id}"):
                    group.name = edit_name
                    if edit_password:
                        group.password = edit_password
                    group.role = edit_role
                    session.commit()
                    st.success(f"Änderungen für {group.name} gespeichert!")
                if st.button(
                    f"Person deaktivieren", key=f"deactivate_group_{group.id}"
                ):
                    group.active = False
                    session.commit()
                    st.success(f"Person {group.name} deaktiviert!")


def show_expenses_management():
    st.header("Ausgabenverwaltung")

    # Add new expense
    with st.expander("Neue Ausgabe hinzufügen"):
        with st.form("Neue Ausgabe hinzufügen"):
            new_expense_name = st.text_input("Name der Ausgabe", key="new_expense_name")
            new_expense_amount = st.number_input(
                "Jährlicher Betrag", min_value=0.0, key="new_expense_amount"
            )
            new_expense_type = st.selectbox(
                "Typ", ["Festkosten", "pro Kopf"], key="new_expense_type"
            )
            type_mapping = {"Festkosten": "rent", "pro Kopf": "ancillary"}
            new_expense_type = type_mapping[new_expense_type]
            explanation = st.text_input("Erklärung", key="new_expense_explanation")
            add_button = st.form_submit_button("Ausgabe hinzufügen")
            if add_button:
                with Session() as session:
                    new_expense = Expense(
                        name=new_expense_name,
                        yearly_amount=new_expense_amount,
                        type=new_expense_type,
                    )
                    session.add(new_expense)
                    session.commit()
                    log_change(
                        session,
                        new_expense.id,
                        "add",
                        explanation,
                        None,
                        new_expense_amount,
                        "expense",
                    )
                    st.success(f"Ausgabe {new_expense_name} hinzugefügt!")

    # List and manage existing expenses
    st.subheader("Bestehende Ausgaben")
    with Session() as session:
        expenses = session.query(Expense).all()
        for expense in expenses:
            with st.expander(f"{expense.name}"):
                with st.form(f"edit_expense_{expense.id}"):
                    edit_name = st.text_input(
                        "Name", value=expense.name, key=f"edit_name_{expense.id}"
                    )
                    edit_amount = st.number_input(
                        "Jährlicher Betrag",
                        value=expense.yearly_amount,
                        key=f"edit_amount_{expense.id}",
                    )
                    expense_type_index = list(type_mapping.keys())[
                        list(type_mapping.values()).index(expense.type)
                    ]
                    edit_type = st.selectbox(
                        "Typ",
                        ["Festkosten", "pro Kopf"],
                        index=["Festkosten", "pro Kopf"].index(expense_type_index),
                        key=f"edit_type_{expense.id}",
                    )
                    explanation = st.text_input(
                        "Erklärung", key=f"edit_explanation_{expense.id}"
                    )
                    save_changes_button = st.form_submit_button("Änderungen speichern")
                    delete_expense_button = st.form_submit_button("Ausgabe löschen")

                    if save_changes_button:
                        old_amount = expense.yearly_amount
                        expense.name = edit_name
                        expense.yearly_amount = edit_amount
                        expense.type = type_mapping[edit_type]
                        session.commit()
                        log_change(
                            session,
                            expense.id,
                            "edit",
                            explanation,
                            old_amount,
                            edit_amount,
                            "expense",
                        )
                        st.success(f"Änderungen für {expense.name} gespeichert!")

                    if delete_expense_button:
                        explanation = st.text_input(
                            "Erklärung", key=f"delete_explanation_{expense.id}"
                        )
                        log_change(
                            session,
                            expense.id,
                            "delete",
                            explanation,
                            expense.yearly_amount,
                            None,
                            "expense",
                        )
                        session.delete(expense)
                        session.commit()
                        st.success(f"Ausgabe {expense.name} gelöscht!")


def show_funds_management(user: Group):
    st.header("Bargeldverwaltung")
    with st.expander("Einzahlungstopf leeren"):
        show_distribution(user)
    with st.expander("Einzahlungen prüfen"):
        show_deposits(user.role, user.name)
    with st.expander("Ausgaben"):
        show_expenses(role, current_user)
    with st.expander("Kassentransaktionen bestätigen"):
        show_confirmation()
    with st.expander("Geld zwischen Fonds verschieben"):
        with st.form("Übertragung durchführen"):
            from_fund_name = st.selectbox(
                "Von Fonds",
                [fund.name for fund in funds if fund.name != "Einzahlungsfonds"],
                key="transfer_from_fund",
            )
            to_fund_name = st.selectbox(
                "Zu Fonds",
                [fund.name for fund in funds if fund.name != "Einzahlungsfonds"],
                key="transfer_to_fund",
            )
            transfer_amount = st.number_input(
                "Betrag", min_value=0.0, key="transfer_amount"
            )

            button = st.form_submit_button("Übertragung durchführen")
        if button:
            with Session() as session:
                from_fund = (
                    session.query(Fund).filter(Fund.name == from_fund_name).first()
                )
                to_fund = session.query(Fund).filter(Fund.name == to_fund_name).first()
                transfer_funds(from_fund.id, to_fund.id, transfer_amount, user.id)
                st.success(
                    f"{transfer_amount} EUR von {from_fund_name} zu {to_fund_name} übertragen!"
                )

    with st.expander("Fonds bearbeiten oder löschen"):

        delete_fund_name = st.selectbox(
            "Fonds",
            [fund.name for fund in funds if fund.name != "Einzahlungsfonds"],
            key="delete_fund_name",
        )
        with Session() as session:
            delete_fund_obj = (
                session.query(Fund).filter(Fund.name == delete_fund_name).first()
            )

            with st.form("Fonds löschen"):

                new_fund_name = st.text_input(
                    "Fondsname", key="update_fund_name", value=delete_fund_name
                )
                new_fund_yearly_target = st.number_input(
                    "Jährliches Ziel",
                    min_value=0.0,
                    key="update_fund_yearly_target",
                    value=delete_fund_obj.yearly_target,
                )
                explanation = st.text_input("Erklärung", key="update_fund_explanation")
                update_fund_submit = st.form_submit_button("Fonds aktualisieren")
                transfer_to_fund_name = st.selectbox(
                    "Übertragen verbleibender Saldo zu",
                    [fund.name for fund in funds if fund.name != "Einzahlungsfonds"],
                    key="delete_transfer_to_fund_name",
                )

                delete_button = st.form_submit_button("Fonds löschen")
                if update_fund_submit:
                    old_yearly_target = delete_fund_obj.yearly_target
                    delete_fund_obj.name = new_fund_name
                    delete_fund_obj.yearly_target = new_fund_yearly_target
                    session.commit()
                    log_change(
                        session,
                        delete_fund_obj.id,
                        "edit",
                        explanation,
                        old_yearly_target,
                        new_fund_yearly_target,
                        "fund",
                    )
                    st.success("Fonds aktualisiert!")

                if delete_button:
                    explanation = st.text_input(
                        "Erklärung", key="delete_fund_explanation"
                    )
                    transfer_to_fund = (
                        session.query(Fund)
                        .filter(Fund.name == transfer_to_fund_name)
                        .first()
                    )
                    log_change(
                        session,
                        delete_fund_obj.id,
                        "delete",
                        explanation,
                        delete_fund_obj.current_balance,
                        None,
                        "fund",
                    )
                    delete_fund(delete_fund_obj.id, transfer_to_fund.id, user.id)
                    st.success(
                        f"Fonds {delete_fund_name} gelöscht und verbleibender Saldo zu {transfer_to_fund_name} übertragen!"
                    )

    with st.expander("Neuen Fonds hinzufügen"):
        with st.form("Neuen Fonds hinzufügen"):
            new_fund_name = st.text_input("Fondsname", key="new_fund_name")
            new_fund_yearly_target = st.number_input(
                "Jährliches Ziel", min_value=0.0, key="new_fund_yearly_target"
            )
            explanation = st.text_input("Erklärung", key="new_fund_explanation")

            b = st.form_submit_button("Fonds hinzufügen")
        if b:
            with Session() as session:
                new_fund = Fund(
                    name=new_fund_name,
                    yearly_target=new_fund_yearly_target,
                )
                session.add(new_fund)
                session.commit()
                log_change(
                    session,
                    new_fund.id,
                    "add",
                    explanation,
                    None,
                    new_fund_yearly_target,
                    "fund",
                )
                st.success(
                    f"Fonds {new_fund_name} mit einem jährlichen Ziel von {new_fund_yearly_target} EUR hinzugefügt!"
                )


def show_deposits(role: Literal["admin", "user"], name: str):
    st.header("Einzahlungsprotokoll")
    missing_payments = check_missing_payments()
    if missing_payments:
        for group, payments in missing_payments.items():
            if role == "user" and group != name:
                continue
            st.write(f"{group}:")
            for payment in payments:
                st.write(
                    f"  Monat {payment[0].month}/{payment[0].year}: {payment[1]} EUR fehlen"
                )
    else:
        st.write("Keine fehlenden Einzahlungen.")

    group_name = (
        st.selectbox("Person", [group.name for group in groups])
        if role == "admin"
        else name
    )
    missing_date = missing_payments[group_name][0][0]
    month = st.number_input(
        "Monat",
        min_value=1,
        max_value=12,
        value=missing_date.month,
        key="deposit_month",
    )
    year = st.number_input(
        "Jahr",
        min_value=datetime.now().year - 10,
        max_value=datetime.now().year + 10,
        value=missing_date.year,
        key="deposit_year",
    )

    with Session() as session:
        group = session.query(Group).filter(Group.name == group_name).first()
        month_date = date(year, month, 1)
        monthly_amount = (
            session.query(MonthlyCash)
            .filter(
                MonthlyCash.group_id == group.id,
                MonthlyCash.start_date <= month_date,
                MonthlyCash.end_date >= month_date,
            )
            .first()
        )

        if monthly_amount:
            amount = monthly_amount.amount
            st.write(f"Betrag für {group_name} im {month}/{year}: {amount} EUR")
            deposit_amount = st.number_input(
                "Einzahlungsbetrag", min_value=0.0, value=amount, key="deposit_amount"
            )

            if st.button("Einzahlung bestätigen"):
                deposit_fund = (
                    session.query(Fund).filter(Fund.name == "Einzahlungsfonds").first()
                )
                add_transaction(
                    deposit_fund.id,
                    deposit_amount,
                    month_date,
                    group.id,
                    comment=group_name,
                )
                st.success(
                    f"Einzahlung von {deposit_amount} EUR für {group_name} im {month}/{year} bestätigt! Bitte geben Sie das Geld an die Verwaltung."
                )


def show_distribution(user: Group):
    st.header("Einzahlungen verteilen")
    with Session() as session:
        deposit_fund = (
            session.query(Fund).filter(Fund.name == "Einzahlungsfonds").first()
        )
        st.write(f"{deposit_fund.current_balance} € im Einzahlungsfonds.")
        if st.button("Verteilung durchführen"):
            result = distribute_funds(user.id)
            if result:
                st.write("Verteilung abgeschlossen:")
                for fund_name, balance in result.items():
                    st.write(f"{fund_name}: {balance} EUR")


def show_expenses(role: Literal["admin", "user"], user: Group):
    st.header("Ausgabe aufzeichnen")
    with st.form(key="Ausgabenrückerstatung"):
        fund_name = (
            st.selectbox(
                "Fonds",
                [fund.name for fund in funds if fund.name != "Einzahlungsfonds"],
            )
            if role == "admin"
            else "Ausgabenpuffer"
        )
        expense_amount = st.number_input("Betrag", min_value=0.0, key="expense_amount")
        expense_comment = st.text_input("Kommentar", key="expense_comment")
        expense_date = st.date_input(
            "Datum der Ausgabe", value=date.today(), key="expense_date"
        )
        submit_button = st.form_submit_button(label="Ausgabe bestätigen")
    if submit_button:
        with Session() as session:
            fund = session.query(Fund).filter(Fund.name == fund_name).first()
            add_transaction(
                fund.id, -expense_amount, expense_date, user.id, comment=expense_comment
            )
            st.success(
                "Ausgabe bestätigt. Geld kann bei der Verwaltung abgeholt werden."
            )


def show_confirmation():
    st.header("Bestätigungen")
    with Session() as session:
        unconfirmed_transactions = (
            session.query(Transaction).filter(Transaction.confirmed == False).all()
        )

        if unconfirmed_transactions:
            # Group transactions by transfer_id
            grouped_transactions = {}
            for transaction in unconfirmed_transactions:
                if transaction.transfer_id:
                    if transaction.transfer_id not in grouped_transactions:
                        grouped_transactions[transaction.transfer_id] = []
                    grouped_transactions[transaction.transfer_id].append(transaction)
                else:
                    grouped_transactions[transaction.id] = [transaction]

            # Create table headers
            st.markdown("### Unbestätigte Transaktionen")
            cols = st.columns([1, 1, 1, 1, 1, 1])
            cols[0].write("Topf")
            cols[1].write("Person")
            cols[2].write("Kommentar")
            cols[3].write("Betrag")
            cols[4].write("Bestätigen")
            cols[5].write("Löschen")

            for transfer_id, transactions in grouped_transactions.items():
                for transaction in transactions:
                    cols = st.columns([1, 1, 1, 1, 1, 1])
                    cols[0].write(transaction.topf.name)
                    cols[1].write(transaction.group.name)
                    cols[2].write(transaction.comment)
                    cols[3].write(f"{transaction.amount} EUR")

                    with cols[4]:
                        if st.button("Bestätigen", key=f"confirm_{transaction.id}"):
                            confirm_transaction(transaction.id)
                            st.success(
                                f"Transaktion {transaction.id} bestätigt!"
                                if not transaction.transfer_id
                                else f"Transfer {transfer_id} bestätigt!"
                            )
                            st.experimental_rerun()

                    with cols[5]:
                        if st.button("Löschen", key=f"delete_{transaction.id}"):

                            for trans in transactions:
                                session.delete(trans)
                            session.commit()
                            st.success(
                                f"Transaktion {transaction.id} gelöscht!"
                                if not transaction.transfer_id
                                else f"Transfer {transfer_id} gelöscht!"
                            )
                            st.experimental_rerun()
        else:
            st.write("Keine unbestätigten Transaktionen.")


if authentication_status:
    with Session() as session:
        current_user = session.query(Group).filter(Group.name == name).first()

    role = roles[name]
    with st.sidebar:
        st.title("Projekte-Miet-Verwaltung")
        authenticator.logout("Abmelden")

    tab_functions = {
        "Dashboard": show_dashboard,
        "Einzahlungen": show_deposits,
        "Ausgabenrückerstatung": show_expenses,
        "Bargeldverwaltung": show_funds_management,
        "Mein Profil": show_user_profile,
    }

    admin_tabs = [
        "Dashboard",
        "Bargeldverwaltung",
        "Kosten verwalten",
        "Bietrunde",
        "Räume und Bewohner*innen",
        "Mein Profil",
    ]
    user_tabs = [
        "Dashboard",
        "Einzahlungen",
        "Ausgabenrückerstatung",
        "Mein Profil",
        "Mietgebot abgeben",
    ]

    tabs = admin_tabs if role == "admin" else user_tabs

    selected_tab = st.sidebar.radio("Registerkarte auswählen", tabs)

    if selected_tab == "Einzahlungen":
        show_deposits(role, name)
    elif selected_tab == "Ausgabenrückerstatung":
        show_expenses(role, current_user)
    elif selected_tab == "Bargeldverwaltung" and role == "admin":
        show_funds_management(current_user)
    elif selected_tab == "Mein Profil":
        show_user_profile(current_user)
    elif selected_tab == "Räume und Bewohner*innen":
        manage_rooms_and_categories()
    elif selected_tab == "Kosten verwalten":
        show_expenses_management()
    elif selected_tab == "Bietrunde":
        evaluate_bids_and_start_round()
    elif selected_tab == "Mietgebot abgeben":
        submit_rent_bid(current_user)
    else:
        show_dashboard()
else:
    if authentication_status == False:
        st.error("Benutzername/Passwort ist falsch")
    elif authentication_status == None:
        st.warning("Bitte geben Sie Ihren Benutzernamen und Ihr Passwort ein")
