# Container image for Azure App Service (Web App for Containers).
# Bundles the Microsoft ODBC Driver 18 so pyodbc can reach Azure SQL — the reason a
# plain App Service Python image won't work for this app.
FROM python:3.12-slim

# --- Microsoft ODBC Driver 18 for SQL Server (Debian 12 / bookworm) ---
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg apt-transport-https \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] \
https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# App Service routes to the port in WEBSITES_PORT (set it to 8000). Streamlit listens here.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "streamlit run streamlit_app.py --server.port ${PORT:-8000} --server.address 0.0.0.0 --server.headless true"]
