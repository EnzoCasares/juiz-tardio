from app.tools.db import get_conn


def migrar_financeiro() -> None:
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS moeda TEXT")
            cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS source_text TEXT")
            cur.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conrelid = 'transactions'::regclass
                        AND conname = 'transactions_moeda_check'
                    ) THEN
                        ALTER TABLE transactions ADD CONSTRAINT transactions_moeda_check
                        CHECK (moeda IN ('BRL', 'USD'));
                    END IF;
                END $$
            """)
    finally:
        conn.close()


if __name__ == "__main__":
    migrar_financeiro()
