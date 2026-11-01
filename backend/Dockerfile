FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./alembic.ini
COPY backend ./backend
COPY generator ./generator
COPY data/generated/employees.csv \
     data/generated/leave_policies.csv \
     data/generated/leave_balances.csv \
     data/generated/leave_requests.csv \
     data/generated/public_holidays.csv \
     data/generated/expense_policies.csv \
     data/generated/cost_centers.csv \
     data/generated/expense_claims.csv \
     data/generated/expense_lines.csv \
     data/generated/approval_rules.csv \
     data/generated/approval_steps.csv \
     data/generated/reimbursements.csv \
     ./data/seed/
RUN sed -i 's/\r$//' backend/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["sh", "backend/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--root-path", "/api", "--proxy-headers", "--forwarded-allow-ips", "*"]
