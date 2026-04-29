# WhatsApp CRM & Bot Engine

![Python](https://img.shields.io/badge/Python-3.x-blue.svg)
![Flask](https://img.shields.io/badge/Flask-Web-green.svg)
![Celery](https://img.shields.io/badge/Celery-Async-yellow.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue.svg)

A robust, asynchronous WhatsApp Bot and CRM system built with Python (Flask) and Celery. It integrates directly with the **Evolution API** to handle real-time WhatsApp messaging events. The system features a built-in conversational state machine to automate customer support workflows, routing, and ticket creation.

## 🚀 Key Features

*   **Asynchronous Processing:** Powered by Celery and Redis to handle high volumes of incoming messages without blocking the main application.
*   **State Machine Bot:** Context-aware bot engine that tracks user conversation states and dynamically serves interactive menus.
*   **Web Dashboard:** Built-in admin panel to manage settings, monitor active sessions, and track conversations.
*   **Third-Party Integrations:** Ready-to-use architecture for external API integrations (e.g., Ticketing systems like Desk Manager).
*   **Dockerized Infrastructure:** Simple deployment setup for PostgreSQL and Redis dependencies using `docker-compose`.

## 🛠️ Tech Stack

*   **Backend:** Python, Flask, Celery
*   **Database:** PostgreSQL, SQLAlchemy
*   **Message Broker / Cache:** Redis
*   **WhatsApp API:** Evolution API
*   **Frontend:** HTML, CSS, JavaScript

## ⚙️ Getting Started

1.  **Clone the repository**
2.  **Set up the environment:**
    Rename `.env.example` to `.env` and fill in your local database credentials and Evolution API keys.
3.  **Start database dependencies:**
    ```bash
    docker-compose up -d
    ```
4.  **Install Python requirements:**
    ```bash
    pip install -r requirements.txt
    ```
5.  **Run the Flask application:**
    ```bash
    python run.py
    ```
6.  **Run the Celery worker** (in a separate terminal):
    ```bash
    python run_celery.py
    ```
