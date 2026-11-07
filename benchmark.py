import pandas as pd
import time
from sqlalchemy import create_engine
from clickhouse_driver import Client

# Настройки
CLICKHOUSE_HOST = 'localhost'
CLICKHOUSE_PORT = 9000
CLICKHOUSE_USER = 'dwh_user'
CLICKHOUSE_PASSWORD = 'dwh_password'
CLICKHOUSE_DB = 'benchmark'
GREENPLUM_URL = "postgresql+psycopg2://gpadmin:dwh_password@localhost:5433/postgres"

# Загрузка данных
print("Читаем CSV (397k строк)...")
df = pd.read_csv('online_retail.csv', encoding='ISO-8859-1')
df = df.dropna(subset=['CustomerID'])
df = df[df['Quantity'] > 0]
df.columns = ['invoice_no', 'stock_code', 'description', 'quantity', 'invoice_date', 'unit_price', 'customer_id', 'country']

# Приводим типы (чтобы ClickHouse не ругался)
df['invoice_date'] = pd.to_datetime(df['invoice_date'])
df['customer_id'] = df['customer_id'].astype('int32')
df['quantity'] = df['quantity'].astype('int32')

print(f"Строк после очистки: {len(df)}")

# --- 1. CLICKHOUSE ---
print("\n1. Загрузка в ClickHouse...")
ch_client = Client(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    user=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD,
    database=CLICKHOUSE_DB
)

ch_client.execute("DROP TABLE IF EXISTS sales")
ch_client.execute("""
    CREATE TABLE sales (
        invoice_no String,
        stock_code String,
        description String,
        quantity Int32,
        invoice_date DateTime,
        unit_price Float64,
        customer_id Int32,
        country String
    ) ENGINE = MergeTree()
    ORDER BY (invoice_no)
""")

data = list(df.itertuples(index=False, name=None))
start = time.time()
for i in range(0, len(data), 10000):
    ch_client.execute("INSERT INTO sales VALUES", data[i:i+10000])
ch_load = time.time() - start
print(f"   Загрузка заняла: {ch_load:.2f} сек.")

# --- 2. GREENPLUM ---
print("\n2. Загрузка в Greenplum...")
gp_engine = create_engine(GREENPLUM_URL)
start = time.time()
df.to_sql('sales', gp_engine, if_exists='replace', index=False, chunksize=10000)
gp_load = time.time() - start
print(f"   Загрузка заняла: {gp_load:.2f} сек.")

# --- 3. БЕНЧМАРК ---
query = """
    SELECT country, SUM(quantity * unit_price) AS total_revenue
    FROM sales
    GROUP BY country
    ORDER BY total_revenue DESC
    LIMIT 10
"""

print("\n3. Аналитический запрос (Топ-10 стран)...")
start = time.time()
result_ch = ch_client.execute(query)
ch_time = time.time() - start

with gp_engine.connect() as conn:
    start = time.time()
    result_gp = pd.read_sql(query, conn)
    gp_time = time.time() - start

print(f"\n⏱ Результаты:")
print(f"   ClickHouse: {ch_time:.4f} сек.")
print(f"   Greenplum:  {gp_time:.4f} сек.")
print(f"   Ускорение:  {gp_time / ch_time:.2f}x")
print("\n✅ Готово!")
