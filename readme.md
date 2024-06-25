# Cashbox Management System

## Overview
The Cashbox Management System is a web application designed to streamline the financial management of a communal living project. It provides tools for managing funds, expenses, user profiles, and transactions, ensuring transparency and efficiency in handling communal finances.

## Purpose
The primary purpose of this application is to facilitate the management of communal funds and expenses, allowing both administrators and users to interact with the system based on their roles. It ensures that all financial activities are logged, tracked, and managed efficiently.

## Key Features

### User Authentication
- **Login/Logout**: Secure user authentication to access the system.

### User Roles
- **Admin**: Full access to manage users, funds, expenses, and transactions.
- **User**: Limited access to manage personal profiles and submit expenses.

### Financial Management
- **Funds**: Create, edit, transfer, and delete communal funds.
- **Expenses**: Add, edit, and delete expenses, with detailed logging of changes.
- **Transactions**: Record and confirm financial transactions.

### Bidding System
- **Rent Bids**: Submit and evaluate rent bids for communal living spaces.

### User Profile Management
- **Profile**: View and update personal information, including rooms and members.

### Reporting and Visualization
- **Dashboard**: Visualize fund balances and transaction history over time.

## Usage
- **Login**: Users log in to access the system.
- **Navigate**: Use the sidebar to access different features based on user roles.
- **Manage Finances**: Admins manage funds and expenses, while users manage their profiles and submit expenses.

## Installation
1. Clone the repository:
    ```sh
    git clone <repository-url>
    ```
2. Install dependencies:
    ```sh
    poetry install
    ```
3. Run the application:
    ```sh
    streamlit run app.py
    ```