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
        funds_data = session.query(Fund).all()
        funds_overview = [
            {
                "Fonds": fund.name,
                "Aktueller Saldo": sum(
                    t.amount for t in fund.transactions if t.confirmed
                ),
                "Jährliches Ziel": fund.yearly_target,
            }
            for fund in funds_data
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
    df.sort_values(by=["Fonds", "Datum"], inplace=True)
    df["Betrag"].fillna(0, inplace=True)
    df["Saldo"] = df.groupby("Fonds")["Betrag"].cumsum()
    df["Person"].fillna(method="ffill", inplace=True)
    df["Kommentar"].fillna(method="ffill", inplace=True)

    # Create the plot
    fig = px.area(
        df,
        x="Datum",
        y="Saldo",
        color="Fonds",
        title="Fonds-Salden im Zeitverlauf",
        hover_data={"Betrag": True, "Person": True, "Kommentar": True},
    )

    # Display the overview table
    st.table(pd.DataFrame(funds_overview))

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
            if log.fund is not None
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
    st.subheader("Aktuelle Miete")
    with Session() as session:
        # Retrieve the current rent payment for the group
        current_cash, current_giro = current_payments(user, session)
        st.write(f"Bar: {current_cash}, Überweisung: {current_giro}")
        st.subheader("Persönliche Daten")

        group = session.query(Group).filter(Group.name == user.name).first()
        if group:
            new_name = st.text_input("Name", value=group.name)
            new_password = st.text_input("Passwort", type="password")
            col1, col2 = st.columns(2)
            with col2:
                with st.popover(
                    "ℹ",
                ):
                    st.info(
                        """#### Was muss ich hier angeben?
Am Ende geht es um die Summe, die monatlich auf eurem Konto landet abzüglich von Betreuungskosten (Kita, Hort) und allem was den Unterschied zwischen Brutto und Nettolohn macht (Kranken- ,Pflegeversichrung, Steuern Renteneinzahlung ...). Wenn du also angestellt bist also z.B. deinen Nettolohn plus Kindergeld minus Betreuungskosten. Wer von Vermögen lebt, rechnet mit ein, wie viel er oder sie davon im Monat nutzt.
#### Beschreibung der Berechnung des verfügbaren Einkommens für die Mietberechnung
Das verfügbare Einkommen eurer Gruppe wird berechnet, indem das Gesamteinkommen eurer Gruppe abzüglich des monatlichen Grundbedarfs aller Personen ermittelt wird. Der monatliche Grundbedarf jeder Person basiert auf ihrer Kategorie, die je nach Bedürfnis unterschiedlich sein kann (z.B. Erwachsene vs. Kinder).

##### Schritte der Berechnung
1. Einkommen der Gruppe: Jede Gruppe hat ein Gesamteinkommen.

2. Monatlicher Grundbedarf der Mitglieder: Jede Person gehört einer Kategorie an, die einen spezifischen monatlichen Grundbedarf festlegt.

3. Gesamtgrundbedarf: Der gesamte monatliche Grundbedarf der Gruppe wird durch die Summe der Grundbedarfe aller Mitglieder berechnet.

4. Verfügbares Einkommen: Das verfügbare Einkommen ergibt sich aus der Differenz zwischen dem Gesamteinkommen und dem gesamten monatlichen Grundbedarf.

##### Berücksichtigung von Kindern
Kinder haben in der Regel einen geringeren monatlichen Grundbedarf und eine andere Gewichtung als Erwachsene, wodurch sie finanziell anders berücksichtigt werden.

##### Beispielberechnung
Gesamteinkommen der Gruppe: 3000 €
Mitglieder: 2 Erwachsene und 2 Kinder
Kategorien:

Erwachsene: monatlicher Grundbedarf = 500 €
Kinder: monatlicher Grundbedarf = 300 €
Berechnung:

2 Erwachsene: 2 * 500 € = 1000 €
2 Kinder: 2 * 300 € = 600 €
Gesamtgrundbedarf: 1000 € + 600 € = 1600 €

Verfügbares Einkommen: 3000 € - 1600 € = 1400 €

Diese Berechnung berücksichtigt die unterschiedlichen Bedürfnisse der Mitglieder, einschließlich der Kinder, und stellt sicher, dass das verbleibende Einkommen fair verteilt wird.
    """
                    )
            with col1:
                new_income = st.number_input("Einkommen", value=group.income)

            if st.button("Eingabe bestätigen"):
                group.name = new_name
                if new_password:
                    group.password = new_password
                group.income = new_income
                group.last_updated = datetime.now()
                session.commit()
                st.success("Profil aktualisiert!")

            all_rooms = session.query(Room).all()
            all_categories = session.query(PeopleCategory).all()
            with st.form("Räume"):
                selected_rooms = st.multiselect(
                    "Gemietete Räume",
                    options=all_rooms,
                    default=group.rooms,
                    format_func=lambda x: x.name,
                )

                if st.form_submit_button("Speichern"):
                    selected_room_ids = [room.id for room in selected_rooms]
                    group.rooms = (
                        session.query(Room).where(Room.id.in_(selected_room_ids)).all()
                    )
                    session.commit()
                    st.success(f"Räume aktualisiert!")

            current_members = [
                (member.id, member.category.name) for member in group.members
            ]

            # Count the number of members per category
            category_counts = {}
            for member in group.members:
                category_name = member.category.name
                if category_name not in category_counts:
                    category_counts[category_name] = 0
                category_counts[category_name] += 1
            with st.form("members"):
                st.write("Aktuelle Mitglieder")
                # Select number of members per category
                category_selection = {}
                for category in all_categories:
                    count = st.number_input(
                        f"Anzahl der Mitglieder für Kategorie '{category.name}'",
                        min_value=0,
                        value=category_counts.get(category.name, 0),
                        step=1,
                    )
                    category_selection[category.id] = count

                if st.form_submit_button("Mitglieder aktualisieren"):
                    # Update group members based on selection
                    session.query(Person).filter(Person.group_id == group.id).delete()
                    for category_id, count in category_selection.items():
                        for _ in range(count):
                            new_person = Person(
                                category_id=category_id, group_id=group.id
                            )
                            session.add(new_person)
                    session.commit()
                    st.success("Mitglieder aktualisiert!")
                    st.rerun()


def manage_rooms_and_categories():
    st.header("Räume und Bewohnerinnen verwalten")
    with st.expander("Bewohnerinnen"):
        show_group_management()

    with Session() as session:

        room_management(session)

        people_category(session)


def room_management(session):
    with st.expander("Räume"):
        # Rooms Management
        st.subheader("Räume")
        rooms = session.query(Room).all()
        groups = session.query(Group).all()

        st.write("Aktuelle Räume:")
        room_data = [
            {"ID": room.id, "Name": room.name, "Fläche": room.area} for room in rooms
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
            selected_room: Room = (
                session.query(Room).filter(Room.id == selected_room_id[0]).first()
            )
            with st.form("edit_room_form"):
                edit_room_name = st.text_input("Raumname", value=selected_room.name)
                edit_room_area = st.number_input(
                    "Raumfläche (in Quadratmetern)",
                    value=selected_room.area,
                    min_value=0.0,
                )

                selected_tenants = st.multiselect(
                    "Mieterinnen",
                    options=groups,
                    default=selected_room.tenants,
                    format_func=lambda x: x.name,
                )

                update_room_submit = st.form_submit_button("Raum aktualisieren")
                delete_room_submit = st.form_submit_button("Raum löschen")

                if update_room_submit:
                    selected_room.name = edit_room_name
                    selected_room.area = edit_room_area
                    selected_tenant_ids = [tenant.id for tenant in selected_tenants]
                    selected_room.tenants = (
                        session.query(Group)
                        .where(Group.id.in_(selected_tenant_ids))
                        .all()
                    )
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


def people_category(session):
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
    with st.popover(
        "# Mietberechnung &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; ℹ",
        use_container_width=True,
    ):
        st.info(
            """
            Miete basierend auf Fläche:
Diese Berechnung berücksichtigt die gesamte Fläche, die von der Gruppe genutzt wird. Dabei wird auch die Fläche einbezogen, die von allen Gruppen gemeinsam genutzt wird (wenn ein Raum keine spezifischen Mieter hat, wird er als gemeinschaftlich genutzt betrachtet). Die Miete wird anteilig zur genutzten Fläche und zur Kopfzahl der Gruppe im Verhältnis zur Gesamtkopfzahl aller Gruppen aufgeteilt. Dies bedeutet, dass eine Gruppe, die mehr Fläche nutzt oder mehr Mitglieder hat, einen höheren Mietanteil zahlt.

Miete basierend auf Kopfzahl:
Bei dieser Berechnung wird die Miete proportional zur Anzahl der Personen der Gruppe im Verhältnis zur Gesamtzahl der Mitglieder aller aktiven Gruppen aufgeteilt. Dies bedeutet, dass eine größere Gruppe (mit mehr Menschen) mehr Miete zahlt, unabhängig von der genutzten Fläche oder ihrem Einkommen.

Miete basierend auf verfügbarem Einkommen:
Diese Berechnung teilt die Miete proportional zum verfügbaren Einkommen der Gruppe im Verhältnis zum Gesamteinkommen aller aktiven Gruppen auf. Das verfügbare Einkommen jeder Gruppe wird berücksichtigt, sodass Gruppen mit höherem Einkommen einen größeren Anteil der Miete tragen. Dies stellt sicher, dass die Miete basierend auf der finanziellen Leistungsfähigkeit der Gruppen verteilt wird.

Diese drei Berechnungen bieten verschiedene Ansätze zur fairen Verteilung der Mietkosten und können je nach Bedarf und Vereinbarung der Gruppen unterschiedlich gewichtet oder kombiniert werden.
        """
        )

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

    with st.form("Neue Person hinzufügen"):

        new_group_name = st.text_input("Name der Person", key="new_group_name")
        new_group_password = st.text_input(
            "Passwort", type="password", key="new_group_password"
        )
        new_group_role = st.selectbox("Rolle", ["user", "admin"], key="new_group_role")

        button = st.form_submit_button("Person hinzufügen")
    if button:
        add_group(new_group_name, new_group_password, new_group_role)
        st.success(f"Person {new_group_name} hinzugefügt!")

    # Personenübersicht und Bearbeitung

    st.subheader("Bezugsgruppenübersicht")
    with st.form("Personenübersicht"):
        with Session() as session:
            groups = session.query(Group).filter(Group.active == True).all()

            # Prepare data for st.data_editor
            data = []
            for group in groups:
                members = ", ".join([member.category.name for member in group.members])
                rooms = ", ".join([room.name for room in group.rooms])
                rent_calcs = calculate_rent_for_group(group.id)
                data.append(
                    {
                        "ID": group.id,
                        "Name": group.name,
                        "Rolle": group.role,
                        "Einkommen": group.income,
                        "Mitglieder": members,
                        "Räume": rooms,
                        "Passwort": group.password,
                        "Miete Kopf": rent_calcs["by_head_count"],
                        "Miete Fläche": rent_calcs["by_area"],
                        "Miete Einkommen": rent_calcs["by_available_income"],
                    }
                )

            df = pd.DataFrame(data)
            edited_df = st.data_editor(
                df,
                num_rows="fixed",
                key="group_editor",
                disabled=(
                    "Mitglieder",
                    "Räume",
                    "Miete Kopf",
                    "Miete Fläche",
                    "Miete Einkommen",
                ),
                hide_index=True,
                column_config={"ID": None},
            )
            button = st.form_submit_button("Änderungen speichern")
        # Save changes

        if button:
            for index, row in edited_df.iterrows():
                group = session.query(Group).filter(Group.id == row["ID"]).first()
                group.name = row["Name"]
                group.role = row["Rolle"]
                group.income = row["Einkommen"]
                group.password = row["Passwort"]
                session.commit()
            st.success("Änderungen gespeichert!")

        # Deactivate groups
    with st.form("deactivate_group"):
        st.selectbox("Bezugsgruppe", [group.name for group in groups])
        if st.form_submit_button("Gruppe deaktivieren"):
            for index, row in edited_df.iterrows():
                if row["ID"] in df["ID"].values:
                    group = session.query(Group).filter(Group.id == row["ID"]).first()
                    group.active = False
                    session.commit()
            st.success("Personen deaktiviert!")


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

        # Prepare data for st.data_editor
        data = []
        for expense in expenses:
            data.append(
                {
                    "ID": expense.id,
                    "Name": expense.name,
                    "Jährlicher Betrag": expense.yearly_amount,
                    "Typ": next(
                        key
                        for key, value in type_mapping.items()
                        if value == expense.type
                    ),
                    "Erklärung der Änderung": "",  # Placeholder for explanation
                }
            )

        df = pd.DataFrame(data)
        with st.form("edit_expenses"):
            edited_df = st.data_editor(
                df,
                num_rows="fixed",
                key="expense_editor",
                hide_index=True,
                column_config={"ID": None},
            )

            update_button = st.form_submit_button("Änderungen speichern")
        if update_button:
            for index, row in edited_df.iterrows():
                expense = session.query(Expense).filter(Expense.id == row["ID"]).first()
                if expense:
                    old_amount = expense.yearly_amount
                    expense.name = row["Name"]
                    expense.yearly_amount = row["Jährlicher Betrag"]
                    expense.type = type_mapping[row["Typ"]]
                    explanation = row[
                        "Erklärung der Änderung"
                    ]  # Use the explanation from the DataFrame
                    session.commit()
                    log_change(
                        session,
                        expense.id,
                        "edit",
                        explanation,
                        old_amount,
                        row["Jährlicher Betrag"],
                        "expense",
                    )
            st.success("Änderungen für Ausgaben gespeichert!")

        delete_button = st.button("Ausgabe löschen")

        if delete_button:
            selected_expense_id = st.selectbox(
                "Wählen Sie die zu löschende Ausgabe aus",
                options=[expense.id for expense in expenses],
                format_func=lambda id: next(
                    expense.name for expense in expenses if expense.id == id
                ),
                key="delete_expense_id",
            )

            explanation = st.text_input("Erklärung", key="delete_expense_explanation")
            confirm_delete_button = st.button("Löschen bestätigen")

            if confirm_delete_button:
                expense_to_delete = (
                    session.query(Expense)
                    .filter(Expense.id == selected_expense_id)
                    .first()
                )
                if expense_to_delete:
                    log_change(
                        session,
                        expense_to_delete.id,
                        "delete",
                        explanation,
                        expense_to_delete.yearly_amount,
                        None,
                        "expense",
                    )
                    session.delete(expense_to_delete)
                    session.commit()
                    st.success(f"Ausgabe {expense_to_delete.name} gelöscht!")


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
        with Session() as session:
            # Prepare data for st.data_editor
            data = []
            for fund in funds:
                if fund.name != "Einzahlungsfonds":
                    data.append(
                        {
                            "ID": fund.id,
                            "Name": fund.name,
                            "Jährliches Ziel": fund.yearly_target,
                            "Erklärung der Änderung": "",  # Placeholder for explanation
                            "Aktueller Stand": fund.current_balance,
                        }
                    )

            df = pd.DataFrame(data)
            with st.form("edit_funds"):
                edited_df = st.data_editor(
                    df,
                    num_rows="fixed",
                    key="fund_editor",
                    disabled=("Aktueller Stand",),
                    hide_index=True,
                    column_config={"ID": None},
                )

                update_button = st.form_submit_button("Änderungen speichern")
            if update_button:
                for index, row in edited_df.iterrows():
                    fund = session.query(Fund).filter(Fund.id == row["ID"]).first()
                    if fund:
                        old_yearly_target = fund.yearly_target
                        fund.name = row["Name"]
                        fund.yearly_target = row["Jährliches Ziel"]
                        explanation = row[
                            "Erklärung der Änderung"
                        ]  # Use the explanation from the DataFrame
                        session.commit()
                        log_change(
                            session,
                            fund.id,
                            "edit",
                            explanation,
                            old_yearly_target,
                            row["Jährliches Ziel"],
                            "fund",
                        )
                st.success("Fonds aktualisiert!")
            delete_button = st.button("Fonds löschen")

            if delete_button:
                selected_fund_id = st.selectbox(
                    "Wählen Sie den zu löschenden Fonds aus",
                    options=[
                        fund.id for fund in funds if fund.name != "Einzahlungsfonds"
                    ],
                    format_func=lambda id: next(
                        fund.name for fund in funds if fund.id == id
                    ),
                    key="delete_fund_id",
                )

                transfer_to_fund_id = st.selectbox(
                    "Übertragen verbleibender Saldo zu",
                    options=[
                        fund.id for fund in funds if fund.name != "Einzahlungsfonds"
                    ],
                    format_func=lambda id: next(
                        fund.name for fund in funds if fund.id == id
                    ),
                    key="transfer_to_fund_id",
                )

                explanation = st.text_input("Erklärung", key="delete_fund_explanation")
                confirm_delete_button = st.button("Löschen bestätigen")

                if confirm_delete_button:
                    fund_to_delete = (
                        session.query(Fund).filter(Fund.id == selected_fund_id).first()
                    )
                    transfer_to_fund = (
                        session.query(Fund)
                        .filter(Fund.id == transfer_to_fund_id)
                        .first()
                    )
                    if fund_to_delete and transfer_to_fund:
                        log_change(
                            session,
                            fund_to_delete.id,
                            "delete",
                            explanation,
                            fund_to_delete.current_balance,
                            None,
                            "fund",
                        )
                        delete_fund(fund_to_delete.id, transfer_to_fund.id, user.id)
                        st.success(
                            f"Fonds {fund_to_delete.name} gelöscht und verbleibender Saldo zu {transfer_to_fund.name} übertragen!"
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
    with st.popover(
        "# Einzahlungen Verteilen &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; ℹ",
        use_container_width=True,
    ):
        st.info(
            """
            Verteile die Summe im Einzahlungsfonds auf alle Fonds proportional zu ihren jährlichen Zielbeträgen.
            Transaktionen müssen noch bestätigt werden.
        """
        )

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
    with st.popover(
        "# Bestätigungen &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; ℹ",
        use_container_width=True,
    ):
        st.info(
            """
            Die Bestätigung einer Transaktion bedeutet, dass die Transaktion überprüft und als korrekt anerkannt wurde. 
            Nach der Bestätigung wird der Betrag dem entsprechenden Fonds gutgeschrieben.
        """
        )

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
                    cols[0].write(transaction.fund.name)
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

    admin_tabs = [
        "Dashboard",
        "Bargeldverwaltung",
        "Kosten verwalten",
        "Bietrunde",
        "Räume und Bewohner*innen",
        "Mein Profil",
    ]
    user_tabs = [
        "Mein Profil",
        "Dashboard",
        "Einzahlungen",
        "Ausgabenrückerstatung",
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
